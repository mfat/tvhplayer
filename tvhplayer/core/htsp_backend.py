"""HTSP control-plane backend.

Kodi pvr.hts uses HTSP for metadata/DVR and optionally HTTP
`/stream/channelid/{id}` for playback (`GetChannelStreamProperties`).
TVHplayer always uses that HTTP path because VLC cannot demux HTSP muxpkt.
"""

from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

from .backend import TvhBackend, channel_sort_key
from .dvr import (
    GRID_LIMIT,
    HtspRecordingFile,
    MOVE_CATEGORIES,
    PREVREC_ACTIONS,
    RERECORD_ACTIONS,
    autorec_htsp_args,
    autorec_http_conf,
    check_choice,
    dvr_update_htsp_args,
    entry_htsp_id,
    entry_uuid,
    file_move_args,
    parse_autorec_entry,
    parse_cutpoints,
    parse_dvr_config,
    parse_dvr_entry,
    parse_timerec_entry,
    response_id,
    rule_htsp_id,
    ticket_url,
    timerec_htsp_args,
    timerec_http_conf,
)
from .errors import TvhError
from .htsp_connection import HtspConnection
from .models import (
    AutorecEntry,
    AutorecSpec,
    Channel,
    DvrConfig,
    DvrCutpoint,
    DvrEntry,
    DvrEntryUpdate,
    EpgEvent,
    ServerInfo,
    TimerecEntry,
    TimerecSpec,
)
from .urls import http_base_url, htsp_host_port, insert_basic_auth

log = logging.getLogger(__name__)

SYNC_METHODS = frozenset({'initialSyncCompleted', 'initialSyncComplete'})


class HtspBackend(TvhBackend):
    def __init__(self, server):
        super().__init__(server)
        host, port = htsp_host_port(server.url, server.htsp_port)
        self._conn = HtspConnection(host, port)
        self._channels = {}
        self._dvr = {}
        self._synced = False
        self._ready = False

    def close(self):
        self._ready = False
        self._synced = False
        self._conn.close()

    def _on_async(self, msg):
        method = msg.get('method')
        if method in ('channelAdd', 'channelUpdate'):
            self._store_channel(msg, replace=(method == 'channelAdd'))
        elif method == 'channelDelete':
            channel_id = msg.get('channelId')
            self._channels.pop(channel_id, None)
        elif method in ('dvrEntryAdd', 'dvrEntryUpdate'):
            self._store_dvr(msg)
        elif method == 'dvrEntryDelete':
            self._dvr.pop(msg.get('id'), None)
        elif method in SYNC_METHODS:
            self._synced = True

    def _store_channel(self, msg, replace=False):
        channel_id = msg.get('channelId')
        if channel_id is None:
            return
        existing = None if replace else self._channels.get(channel_id)
        name = msg.get('channelName') or (existing.name if existing else 'Unknown Channel')
        number = msg.get('channelNumber')
        if number in (None, 0) and existing:
            number = existing.number
        number = int(number or 0)
        uuid = msg.get('channelIdStr') or (existing.uuid if existing else str(channel_id))
        raw = dict(existing.raw) if existing else {}
        raw.update(msg)
        self._channels[channel_id] = Channel(
            uuid=str(uuid),
            name=name,
            number=number,
            htsp_id=int(channel_id),
            raw=raw,
        )

    def _store_dvr(self, msg):
        entry_id = msg.get('id')
        if entry_id is None:
            return
        try:
            entry_id = int(entry_id)
        except (TypeError, ValueError):
            return
        existing = self._dvr.get(entry_id)
        raw = dict(existing.raw) if existing else {}
        raw.update(msg)

        if 'start' in msg:
            start = int(msg.get('start') or 0)
        elif existing:
            start = existing.start
        else:
            start = 0
        if 'stop' in msg:
            stop = int(msg.get('stop') or 0)
            duration = max(0, stop - start)
        elif existing:
            duration = existing.duration
        else:
            duration = 0

        if 'state' in msg:
            state = msg.get('state') or ''
        elif existing:
            state = existing.raw.get('state') or ''
        else:
            state = ''
        status, sched = _htsp_state_to_http(state)

        channel_id = msg.get('channel') if 'channel' in msg else raw.get('channel')
        if 'channelName' in msg and msg.get('channelName'):
            channel_name = msg.get('channelName')
        elif channel_id in self._channels:
            channel_name = self._channels[channel_id].name
        elif existing:
            channel_name = existing.channel_name
        else:
            channel_name = 'Unknown'

        if 'title' in msg and msg.get('title'):
            title = msg.get('title')
        elif existing:
            title = existing.title
        else:
            title = 'Unknown'

        if msg.get('idStr'):
            uuid = str(msg.get('idStr'))
        elif existing and existing.uuid:
            uuid = existing.uuid
        else:
            uuid = str(entry_id)

        if 'error' in msg:
            error = msg.get('error') or ''
        elif existing:
            error = existing.error
        else:
            error = ''

        self._dvr[entry_id] = DvrEntry(
            uuid=uuid,
            title=title,
            channel_name=channel_name,
            start=start,
            duration=duration,
            status=status,
            sched_status=sched,
            error=error,
            htsp_id=entry_id,
            raw=raw,
        )

    def _ensure(self):
        if self._ready and self._conn._sock is not None:
            return
        self._channels.clear()
        self._dvr.clear()
        self._synced = False
        self._conn.connect()
        self._conn.hello()
        self._conn.authenticate(
            self.server.username,
            self.server.password,
            on_async=self._on_async,
        )
        self._conn.rpc('enableAsyncMetadata', {'epg': 0}, on_async=self._on_async)
        if not self._synced:
            self._conn.recv_until(
                lambda msg: msg.get('method') in SYNC_METHODS,
                timeout=30.0,
                on_async=self._on_async,
            )
        self._ready = True

    def _api(self, path, args=None):
        self._ensure()
        reply = self._conn.rpc(
            'api',
            {'path': path, 'args': args or {}},
            on_async=self._on_async,
        )
        return reply.get('response') or {}

    def get_channels(self) -> List[Channel]:
        self._ensure()
        channels = list(self._channels.values())
        channels.sort(key=channel_sort_key)
        return channels

    def get_epg(self, channel: Channel, limit: int = 24) -> List[EpgEvent]:
        self._ensure()
        if channel.htsp_id is None:
            raise TvhError('Channel has no HTSP id')
        max_time = int(time.time()) + max(limit, 1) * 3600
        reply = self._conn.rpc(
            'getEvents',
            {'channelId': int(channel.htsp_id), 'maxTime': max_time},
            on_async=self._on_async,
        )
        events = []
        for raw in reply.get('events') or []:
            if not isinstance(raw, dict):
                continue
            events.append(
                EpgEvent(
                    start=int(raw.get('start') or 0),
                    stop=int(raw.get('stop') or 0),
                    title=raw.get('title') or 'No title',
                    description=raw.get('description') or raw.get('summary') or '',
                    channel_uuid=channel.uuid,
                    event_id=raw.get('eventId'),
                    raw=raw,
                )
            )
            if len(events) >= limit:
                break
        return events

    def create_dvr_entry(
        self,
        channel: Channel,
        start: int,
        stop: int,
        title: str,
        description: str = '',
        comment: str = '',
        event_id: Optional[int] = None,
    ) -> None:
        self._ensure()
        args = {'enabled': 1}
        if event_id:
            args['eventId'] = int(event_id)
        else:
            if channel.htsp_id is None:
                raise TvhError('Channel has no HTSP id')
            args['channelId'] = int(channel.htsp_id)
            args['start'] = int(start)
            args['stop'] = int(stop)
            args['title'] = title
            if description:
                args['description'] = description
        if comment:
            args['comment'] = comment
        reply = self._conn.rpc('addDvrEntry', args, on_async=self._on_async)
        if not reply.get('success'):
            raise TvhError(reply.get('error') or 'addDvrEntry failed')

    def list_dvr_entries(self) -> List[DvrEntry]:
        self._ensure()
        # Apply dvrEntryUpdate messages queued since the last RPC so a
        # recording that has already started is not still listed as scheduled.
        self._conn.drain_async(self._on_async)
        return list(self._dvr.values())

    def stop_dvr_entry(self, entry: DvrEntry) -> None:
        self._rpc_ok('stopDvrEntry', {'id': entry_htsp_id(entry)}, 'stopDvrEntry')

    def cancel_dvr_entry(self, entry: DvrEntry) -> None:
        self._rpc_ok('cancelDvrEntry', {'id': entry_htsp_id(entry)}, 'cancelDvrEntry')

    def remove_dvr_entry(self, entry: DvrEntry) -> None:
        self._proxy('dvr/entry/remove', {'uuid': entry_uuid(entry)})

    def delete_dvr_entry(self, entry: DvrEntry) -> None:
        self._rpc_ok('deleteDvrEntry', {'id': entry_htsp_id(entry)}, 'deleteDvrEntry')

    def set_dvr_rerecord(self, entry: DvrEntry, action: str) -> None:
        action = check_choice(action, RERECORD_ACTIONS, 'Rerecord action')
        self._proxy(f'dvr/entry/rerecord/{action}', {'uuid': entry_uuid(entry)})

    def set_dvr_prevrec(self, entry: DvrEntry, action: str) -> None:
        action = check_choice(action, PREVREC_ACTIONS, 'Previously-recorded action')
        self._proxy(f'dvr/entry/prevrec/{action}', {'uuid': entry_uuid(entry)})

    def update_dvr_entry(self, entry: DvrEntry, update: DvrEntryUpdate) -> None:
        self._rpc_ok('updateDvrEntry', dvr_update_htsp_args(entry, update), 'updateDvrEntry')

    def move_dvr_entry(self, entry: DvrEntry, category: str) -> None:
        category = check_choice(category, MOVE_CATEGORIES, 'DVR category')
        self._proxy(f'dvr/entry/move/{category}', {'uuid': entry_uuid(entry)})

    def recording_url(self, entry: DvrEntry) -> str:
        reply = self._rpc('getTicket', {'dvrId': entry_htsp_id(entry)})
        url = ticket_url(
            http_base_url(self.server.url),
            str(reply.get('path') or ''),
            str(reply.get('ticket') or ''),
        )
        return insert_basic_auth(url, self.server.username, self.server.password)

    def open_recording(self, entry: DvrEntry) -> HtspRecordingFile:
        htsp_id = entry_htsp_id(entry)
        reply = self._rpc('fileOpen', {'file': f'/dvrfile/{htsp_id}'})
        handle = reply.get('id')
        if handle is None:
            raise TvhError('fileOpen returned no handle')
        size = reply.get('size')
        mtime = reply.get('mtime')
        return HtspRecordingFile(
            lambda method, args=None: self._rpc(method, args),
            handle,
            size=int(size) if size is not None else None,
            mtime=int(mtime) if mtime is not None else None,
        )

    def get_dvr_cutpoints(self, entry: DvrEntry) -> List[DvrCutpoint]:
        reply = self._rpc('getDvrCutpoints', {'id': entry_htsp_id(entry)})
        return parse_cutpoints(reply.get('cutpoints'))

    def notify_dvr_file_moved(self, src: str, dst: str) -> None:
        self._proxy('dvr/entry/filemoved', file_move_args(src, dst))

    def list_dvr_configs(self) -> List[DvrConfig]:
        return [parse_dvr_config(raw) for raw in self._grid('dvr/config/grid')]

    def list_removed_dvr_entries(self) -> List[DvrEntry]:
        return [parse_dvr_entry(raw) for raw in self._grid('dvr/entry/grid_removed')]

    def create_dvr_entry_by_event(self, event_id: int, config_uuid: str = '') -> str:
        args = {'eventId': int(event_id), 'enabled': 1}
        if config_uuid:
            args['configName'] = config_uuid
        reply = self._rpc_ok('addDvrEntry', args, 'addDvrEntry')
        if reply.get('id') is None:
            return ''
        return str(reply['id'])

    def list_autorec_entries(self) -> List[AutorecEntry]:
        return [parse_autorec_entry(raw) for raw in self._grid('dvr/autorec/grid')]

    def create_autorec_entry(self, spec: AutorecSpec) -> str:
        reply = self._rpc_ok('addAutorecEntry', autorec_htsp_args(spec, creating=True), 'addAutorecEntry')
        if reply.get('id') is None:
            return ''
        return str(reply['id'])

    def update_autorec_entry(self, entry: AutorecEntry, spec: AutorecSpec) -> None:
        htsp_id = rule_htsp_id(entry)
        if htsp_id:
            self._rpc_ok(
                'updateAutorecEntry',
                autorec_htsp_args(spec, htsp_id=htsp_id),
                'updateAutorecEntry',
                require_success=False,
            )
            return
        self._save_http_node(entry_uuid(entry), autorec_http_conf(spec))

    def delete_autorec_entry(self, entry: AutorecEntry) -> None:
        htsp_id = rule_htsp_id(entry)
        if htsp_id:
            self._rpc_ok('deleteAutorecEntry', {'id': htsp_id}, 'deleteAutorecEntry')
            return
        self._proxy('idnode/delete', {'uuid': entry_uuid(entry)})

    def create_autorec_by_series(self, event_id: int, config_uuid: str = '') -> str:
        data = {'event_id': int(event_id)}
        if config_uuid:
            data['config_uuid'] = config_uuid
        return response_id(self._proxy('dvr/autorec/create_by_series', data))

    def list_timerec_entries(self) -> List[TimerecEntry]:
        return [parse_timerec_entry(raw) for raw in self._grid('dvr/timerec/grid')]

    def create_timerec_entry(self, spec: TimerecSpec) -> str:
        reply = self._rpc_ok('addTimerecEntry', timerec_htsp_args(spec, creating=True), 'addTimerecEntry')
        if reply.get('id') is None:
            return ''
        return str(reply['id'])

    def update_timerec_entry(self, entry: TimerecEntry, spec: TimerecSpec) -> None:
        htsp_id = rule_htsp_id(entry)
        if htsp_id:
            self._rpc_ok(
                'updateTimerecEntry',
                timerec_htsp_args(spec, htsp_id=htsp_id),
                'updateTimerecEntry',
                require_success=False,
            )
            return
        self._save_http_node(entry_uuid(entry), timerec_http_conf(spec))

    def delete_timerec_entry(self, entry: TimerecEntry) -> None:
        htsp_id = rule_htsp_id(entry)
        if htsp_id:
            self._rpc_ok('deleteTimerecEntry', {'id': htsp_id}, 'deleteTimerecEntry')
            return
        self._proxy('idnode/delete', {'uuid': entry_uuid(entry)})

    def _rpc(self, method, args=None):
        self._ensure()
        return self._conn.rpc(method, args or {}, on_async=self._on_async)

    def _rpc_ok(self, method, args, label, require_success=True):
        reply = self._rpc(method, args)
        # updateAutorecEntry and updateTimerecEntry document no success field.
        if require_success:
            if not reply.get('success'):
                raise TvhError(reply.get('error') or f'{label} failed')
        elif 'success' in reply and not reply.get('success'):
            raise TvhError(reply.get('error') or f'{label} failed')
        return reply

    def _proxy(self, path, args=None):
        response = self._api(path, args or {})
        if isinstance(response, dict) and response.get('error'):
            raise TvhError(str(response['error']))
        return response

    def _grid(self, path):
        data = self._proxy(path, {'limit': GRID_LIMIT})
        if not isinstance(data, dict):
            return []
        return data.get('entries') or []

    def _save_http_node(self, uuid, fields):
        node = {'uuid': uuid}
        node.update(fields)
        self._proxy('idnode/save', {'node': json.dumps(node)})

    def get_server_info(self) -> ServerInfo:
        self._ensure()
        return ServerInfo(
            name=self._conn.server_name,
            version=f'{self._conn.server_version} (HTSP v{self._conn.htsp_version})',
            api_version=str(self._conn.htsp_version),
            capabilities=list(self._conn.capabilities),
            raw={
                'servername': self._conn.server_name,
                'serverversion': self._conn.server_version,
                'htspversion': self._conn.htsp_version,
                'webroot': self._conn.webroot,
            },
        )

    def get_inputs(self) -> list:
        return (self._api('status/inputs') or {}).get('entries') or []

    def get_connections(self) -> list:
        return (self._api('status/connections') or {}).get('entries') or []

    def get_subscriptions(self) -> list:
        return (self._api('status/subscriptions') or {}).get('entries') or []

    def stream_url(self, channel: Channel) -> str:
        """Same HTTP streaming URL Kodi builds when streaming_http is enabled."""
        if channel.htsp_id is None:
            raise TvhError('Channel has no HTSP id')
        base = http_base_url(self.server.url)
        webroot = (self._conn.webroot or '').rstrip('/')
        path = f'{webroot}/stream/channelid/{int(channel.htsp_id)}'
        return insert_basic_auth(base + path, self.server.username, self.server.password)


def _htsp_state_to_http(state: str):
    """Map HTSP dvrEntry state strings onto the HTTP status fields the UI already understands."""
    state = (state or '').lower()
    if 'recording' in state:
        return 'Running', 'recording'
    if 'scheduled' in state:
        return 'Scheduled', 'scheduled'
    if 'completed' in state:
        return 'Completed', 'completed'
    if 'missed' in state:
        return 'Missed', 'failed'
    if 'invalid' in state:
        return 'Invalid', 'failed'
    return state.title() if state else '', state

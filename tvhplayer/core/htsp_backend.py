"""HTSP control-plane backend.

Kodi pvr.hts uses HTSP for metadata/DVR and optionally HTTP
`/stream/channelid/{id}` for playback (`GetChannelStreamProperties`).
TVHplayer always uses that HTTP path because mpv/ffmpeg cannot demux HTSP muxpkt.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from .backend import TvhBackend, channel_sort_key
from .dvr import (
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
    grid_rows,
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
from .guide import (
    epg_htsp_args,
    epg_htsp_transport,
    epg_http_params,
    parse_activity,
    parse_channel_tag,
    parse_connection,
    parse_content_type,
    parse_epg_event,
    parse_events,
    parse_input_status,
    parse_profile,
    parse_subscription,
    sort_channel_tags,
    _rows,
)
from .htsp_connection import HtspConnection
from .models import (
    AutorecEntry,
    AutorecSpec,
    Channel,
    ChannelTag,
    ConnectionStatus,
    ContentType,
    DvrConfig,
    DvrCutpoint,
    DvrEntry,
    DvrEntryUpdate,
    EpgEvent,
    EpgQuery,
    InputStatus,
    ServerActivity,
    ServerInfo,
    StreamProfile,
    SubscriptionStatus,
    TimerecEntry,
    TimerecSpec,
)
from .urls import append_profile, http_base_url, htsp_host_port, insert_basic_auth, resolve_reference

log = logging.getLogger(__name__)

SYNC_METHODS = frozenset({'initialSyncCompleted', 'initialSyncComplete'})


class HtspBackend(TvhBackend):
    def __init__(self, server):
        super().__init__(server)
        host, port = htsp_host_port(server.url, server.htsp_port)
        self._conn = HtspConnection(host, port)
        self._channels = {}
        self._tags = {}
        self._dvr = {}
        self._synced = False
        self._ready = False
        # Whether the server sends this connection its channels, tags, and recordings.
        self._metadata = False

    def close(self):
        self._ready = False
        self._synced = False
        self._metadata = False
        self._conn.close()

    def _on_async(self, msg):
        method = msg.get('method')
        if method in ('channelAdd', 'channelUpdate'):
            self._store_channel(msg, replace=(method == 'channelAdd'))
        elif method == 'channelDelete':
            channel_id = msg.get('channelId')
            self._channels.pop(channel_id, None)
        elif method in ('tagAdd', 'tagUpdate'):
            self._store_tag(msg, replace=(method == 'tagAdd'))
        elif method == 'tagDelete':
            self._tags.pop(_tag_key(msg.get('tagId')), None)
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
        raw = dict(existing.raw) if existing else {}
        raw.update(msg)
        raw['htsp_id'] = int(channel_id)
        if msg.get('channelNumber') in (None, 0) and existing and existing.number:
            raw['channelNumber'] = existing.number
        self._channels[channel_id] = Channel.from_raw(raw)

    def _store_tag(self, msg, replace=False):
        tag_id = _tag_key(msg.get('tagId'))
        if tag_id is None:
            return
        existing = None if replace else self._tags.get(tag_id)
        raw = dict(existing.raw) if existing else {}
        raw.update(msg)
        raw['tagId'] = tag_id
        self._tags[tag_id] = parse_channel_tag(raw)

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

    def _connect(self):
        """Log in, without asking for the channel list.

        Status, guide, recording actions, and stream and logo addresses need
        no more. The server sends a new connection's metadata only after
        enableAsyncMetadata, and for tens of thousands of channels reading it
        took seconds of Python work that slowed the window.
        """
        if self._ready and self._conn._sock is not None:
            return
        self._channels.clear()
        self._tags.clear()
        self._dvr.clear()
        self._synced = False
        self._metadata = False
        self._conn.connect()
        self._conn.hello()
        self._conn.authenticate(
            self.server.username,
            self.server.password,
            on_async=self._on_async,
        )
        self._ready = True

    def _ensure(self):
        """Log in and read the channels, tags, and recordings, which then stay up to date."""
        self._connect()
        if self._metadata:
            return
        try:
            self._conn.rpc('enableAsyncMetadata', {'epg': 0}, on_async=self._on_async)
            if not self._synced:
                self._conn.recv_until(
                    lambda msg: msg.get('method') in SYNC_METHODS,
                    timeout=30.0,
                    on_async=self._on_async,
                )
        except Exception:
            self.close()
            raise
        self._metadata = True

    def _api(self, path, args=None):
        self._connect()
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

    def list_channel_tags(self) -> List[ChannelTag]:
        self._ensure()
        return sort_channel_tags(list(self._tags.values()))

    def query_epg(self, query: EpgQuery) -> List[EpgEvent]:
        self._connect()
        query = query or EpgQuery()
        transport = epg_htsp_transport(query)
        if transport == 'getEvents':
            return self._events_for_channel(query)
        if transport == 'epgQuery':
            reply = self._rpc('epgQuery', epg_htsp_args(query))
            events = parse_events(reply.get('events') or [], query.channel)
            if query.limit is not None:
                return events[:int(query.limit)]
            return events
        return parse_events(self._grid('epg/events/grid', epg_http_params(query)))

    def _events_for_channel(self, query: EpgQuery) -> List[EpgEvent]:
        limit = query.limit if query.limit is not None else 24
        max_time = int(time.time()) + max(int(limit), 1) * 3600
        reply = self._rpc('getEvents', {
            'channelId': int(query.channel.htsp_id),
            'maxTime': max_time,
        })
        events = parse_events(reply.get('events') or [], query.channel)
        if query.limit is not None:
            return events[:int(query.limit)]
        return events

    def get_event(self, event_id: int) -> EpgEvent:
        reply = self._rpc('getEvent', {'eventId': int(event_id)})
        events = parse_events(reply.get('events') or [])
        if events:
            return events[0]
        if reply.get('eventId') is not None or reply.get('title'):
            return parse_epg_event(reply)
        raise TvhError(f'EPG event {event_id} was not found')

    def load_events(self, event_ids: List[int]) -> List[EpgEvent]:
        ids = [int(event_id) for event_id in event_ids or []]
        if not ids:
            return []
        return parse_events(_rows(self._proxy('epg/events/load', {'eventId': ids})))

    def list_related_events(self, event_id: int) -> List[EpgEvent]:
        return self._epg_list('epg/events/related', event_id)

    def list_alternative_events(self, event_id: int) -> List[EpgEvent]:
        return self._epg_list('epg/events/alternative', event_id)

    def list_content_types(self) -> List[ContentType]:
        data = self._proxy('epg/content_type/list')
        return [parse_content_type(row) for row in _rows(data) if isinstance(row, dict)]

    def list_profiles(self) -> List[StreamProfile]:
        reply = self._rpc('getProfiles')
        return [parse_profile(row) for row in _rows(reply, 'profiles') if isinstance(row, dict)]

    def _epg_list(self, path, event_id: int) -> List[EpgEvent]:
        data = self._proxy(path, {'eventId': int(event_id)})
        return parse_events(_rows(data))

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
        self._connect()
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
        return self._ticket_auth(url, reply)

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
        self._connect()
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

    def _grid(self, path, params=None):
        return grid_rows(lambda args: self._proxy(path, args), params)

    def _save_http_node(self, uuid, fields):
        node = {'uuid': uuid}
        node.update(fields)
        # HTSP api args are HTS messages. idnode/save takes node as a list of
        # maps there; the HTTP form post is the path that sends a JSON string.
        self._proxy('idnode/save', {'node': [node]})

    def get_server_info(self) -> ServerInfo:
        self._connect()
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

    def get_inputs(self) -> List[InputStatus]:
        return [parse_input_status(row) for row in self._grid('status/inputs') if isinstance(row, dict)]

    def get_connections(self) -> List[ConnectionStatus]:
        return [parse_connection(row) for row in self._grid('status/connections') if isinstance(row, dict)]

    def get_subscriptions(self) -> List[SubscriptionStatus]:
        return [parse_subscription(row) for row in self._grid('status/subscriptions') if isinstance(row, dict)]

    def get_activity(self) -> ServerActivity:
        data = self._proxy('status/activity')
        return parse_activity(data if isinstance(data, dict) else {})

    def stream_url(self, channel: Channel, profile: Optional[str] = None) -> str:
        """Same HTTP streaming URL Kodi builds when streaming_http is enabled."""
        if channel.htsp_id is None:
            raise TvhError('Channel has no HTSP id')
        self._connect()
        base = http_base_url(self.server.url)
        try:
            reply = self._rpc('getTicket', {'channelId': int(channel.htsp_id)})
            url = self._ticket_auth(ticket_url(base, str(reply.get('path') or ''),
                                               str(reply.get('ticket') or '')), reply)
        except TvhError as exc:
            log.debug('getTicket for channel %s failed: %s', channel.htsp_id, exc)
            webroot = getattr(self._conn, 'webroot', '') or ''
            url = resolve_reference(base, f'stream/channelid/{int(channel.htsp_id)}', webroot)
            url = insert_basic_auth(url, self.server.username, self.server.password)
        return append_profile(url, profile)

    def _ticket_auth(self, url, reply):
        # A ticket stands in for the login. Basic auth beside it gets a 401
        # from a digest-only server, and the player cannot answer digest.
        if reply.get('ticket'):
            return url
        return insert_basic_auth(url, self.server.username, self.server.password)

    def image_url(self, reference: str) -> str:
        reference = (reference or '').strip()
        if not reference:
            return ''
        if reference.startswith(('http://', 'https://')):
            return reference
        self._connect()
        webroot = getattr(self._conn, 'webroot', '') or ''
        url = resolve_reference(http_base_url(self.server.url), reference, webroot)
        return insert_basic_auth(url, self.server.username, self.server.password)


def _tag_key(tag_id):
    if isinstance(tag_id, bool) or tag_id is None:
        return None
    try:
        return int(tag_id)
    except (TypeError, ValueError):
        return None


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

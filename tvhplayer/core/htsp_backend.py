"""HTSP control-plane backend.

Kodi pvr.hts uses HTSP for metadata/DVR and optionally HTTP
`/stream/channelid/{id}` for playback (`GetChannelStreamProperties`).
TVHplayer always uses that HTTP path because VLC cannot demux HTSP muxpkt.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from .backend import TvhBackend, channel_sort_key
from .errors import TvhError
from .htsp_connection import HtspConnection
from .models import Channel, DvrEntry, EpgEvent, ServerInfo
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
        start = int(msg.get('start') or 0)
        stop = int(msg.get('stop') or 0)
        state = msg.get('state') or ''
        channel_name = msg.get('channelName') or 'Unknown'
        channel_id = msg.get('channel')
        if channel_id in self._channels:
            channel_name = self._channels[channel_id].name
        uuid = msg.get('idStr') or str(entry_id)
        status, sched = _htsp_state_to_http(state)
        self._dvr[entry_id] = DvrEntry(
            uuid=str(uuid),
            title=msg.get('title') or 'Unknown',
            channel_name=channel_name,
            start=start,
            duration=max(0, stop - start),
            status=status,
            sched_status=sched,
            error=msg.get('error') or '',
            htsp_id=int(entry_id),
            raw=msg,
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
        return list(self._dvr.values())

    def stop_dvr_entry(self, entry: DvrEntry) -> None:
        self._ensure()
        if entry.htsp_id is None:
            raise TvhError('DVR entry has no HTSP id')
        reply = self._conn.rpc('stopDvrEntry', {'id': int(entry.htsp_id)}, on_async=self._on_async)
        if not reply.get('success'):
            raise TvhError(reply.get('error') or 'stopDvrEntry failed')

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

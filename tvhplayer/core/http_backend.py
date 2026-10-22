"""TVHeadend HTTP JSON API backend."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import requests

from .backend import TvhBackend, channel_sort_key
from .errors import TvhAuthError, TvhConnectionError, TvhError
from .models import Channel, DvrEntry, EpgEvent, ServerInfo
from .urls import http_auth, http_base_url, insert_basic_auth

log = logging.getLogger(__name__)

GRID_LIMIT = 10000
DEFAULT_TIMEOUT = 10


def _localized(value, default=''):
    if isinstance(value, dict):
        if 'eng' in value and value['eng']:
            return str(value['eng'])
        for item in value.values():
            if item:
                return str(item)
        return default
    if value is None:
        return default
    return str(value)


class HttpBackend(TvhBackend):
    def __init__(self, server):
        super().__init__(server)
        self._base = http_base_url(server.url)
        self._auth = http_auth(server.to_dict())
        self._session = requests.Session()
        self._timeout = DEFAULT_TIMEOUT

    def close(self):
        self._session.close()

    def _request(self, method, path, **kwargs):
        url = f'{self._base}/{path.lstrip("/")}'
        kwargs.setdefault('timeout', self._timeout)
        kwargs.setdefault('auth', self._auth)
        try:
            response = self._session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise TvhConnectionError(str(exc)) from exc
        if response.status_code in (401, 403):
            raise TvhAuthError(f'HTTP {response.status_code} for {path}')
        if response.status_code >= 400:
            raise TvhError(f'HTTP {response.status_code} for {path}: {response.text[:200]}')
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise TvhError(f'Invalid JSON from {path}') from exc

    def _grid(self, path, params=None):
        query = {'limit': GRID_LIMIT}
        if params:
            query.update(params)
        data = self._request('GET', path, params=query)
        return data.get('entries') or []

    def get_channels(self) -> List[Channel]:
        entries = self._grid('api/channel/grid')
        channels = [Channel.from_raw(entry) for entry in entries]
        channels.sort(key=channel_sort_key)
        return channels

    def get_epg(self, channel: Channel, limit: int = 24) -> List[EpgEvent]:
        entries = self._request(
            'GET',
            'api/epg/events/grid',
            params={'channel': channel.uuid, 'limit': limit},
        ).get('entries') or []
        events = []
        for entry in entries:
            events.append(
                EpgEvent(
                    start=int(entry.get('start') or 0),
                    stop=int(entry.get('stop') or 0),
                    title=_localized(entry.get('title'), 'No title'),
                    description=_localized(entry.get('description') or entry.get('summary')),
                    channel_uuid=entry.get('channelUuid') or channel.uuid,
                    event_id=entry.get('eventId'),
                    raw=entry,
                )
            )
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
        conf = {
            'start': int(start),
            'stop': int(stop),
            'channel': channel.uuid,
            'title': {'eng': title},
            'subtitle': {'eng': description or 'Recorded via TVHplayer'},
            'description': {'eng': description},
            'comment': comment or 'Scheduled via TVHplayer',
        }
        if event_id:
            conf['eventId'] = int(event_id)
        self._request('POST', 'api/dvr/entry/create', data={'conf': json.dumps(conf)})

    def list_dvr_entries(self) -> List[DvrEntry]:
        entries = []
        for raw in self._grid('api/dvr/entry/grid'):
            start = int(raw.get('start') or 0)
            duration = int(raw.get('duration') or 0)
            if not duration:
                stop = int(raw.get('stop') or 0)
                duration = max(0, stop - start)
            entries.append(
                DvrEntry(
                    uuid=str(raw.get('uuid') or ''),
                    title=_localized(raw.get('disp_title') or raw.get('title'), 'Unknown'),
                    channel_name=raw.get('channelname') or 'Unknown',
                    start=start,
                    duration=duration,
                    status=raw.get('status') or '',
                    sched_status=raw.get('sched_status') or '',
                    errors=int(raw.get('errors') or 0),
                    errorcode=int(raw.get('errorcode') or 0),
                    error=raw.get('error') or '',
                    raw=raw,
                )
            )
        return entries

    def stop_dvr_entry(self, entry: DvrEntry) -> None:
        if not entry.uuid:
            raise TvhError('DVR entry has no uuid')
        self._request('POST', 'api/dvr/entry/stop', data={'uuid': entry.uuid})

    def get_server_info(self) -> ServerInfo:
        data = self._request('GET', 'api/serverinfo')
        return ServerInfo(
            name=data.get('server_name') or self.server.name,
            version=str(data.get('sw_version') or ''),
            api_version=str(data.get('api_version') or ''),
            capabilities=list(data.get('capabilities') or []),
            raw=data,
        )

    def get_inputs(self) -> list:
        return self._grid('api/status/inputs')

    def get_connections(self) -> list:
        return self._grid('api/status/connections')

    def get_subscriptions(self) -> list:
        return self._grid('api/status/subscriptions')

    def stream_url(self, channel: Channel) -> str:
        url = f'{self._base}/stream/channel/{channel.uuid}'
        return insert_basic_auth(url, self.server.username, self.server.password)

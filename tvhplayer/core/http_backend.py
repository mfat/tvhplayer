"""TVHeadend HTTP JSON API backend."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import requests

from .backend import TvhBackend, channel_sort_key
from .dvr import (
    GRID_LIMIT,
    HttpRecordingFile,
    autorec_http_conf,
    check_choice,
    dvr_update_http_node,
    entry_uuid,
    file_move_args,
    localized_text,
    parse_autorec_entry,
    parse_dvr_config,
    parse_dvr_entry,
    parse_timerec_entry,
    response_id,
    timerec_http_conf,
    MOVE_CATEGORIES,
    PREVREC_ACTIONS,
    RERECORD_ACTIONS,
)
from .errors import TvhAuthError, TvhConnectionError, TvhError
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
from .urls import http_auth, http_base_url, insert_basic_auth

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10


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
            # Tvheadend can embed raw control characters in JSON strings.
            # The JSON API Python example decodes with strict=False.
            return json.loads(response.text, strict=False)
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
                    title=localized_text(entry.get('title'), 'No title'),
                    description=localized_text(entry.get('description') or entry.get('summary')),
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
        return [parse_dvr_entry(raw) for raw in self._grid('api/dvr/entry/grid')]

    def stop_dvr_entry(self, entry: DvrEntry) -> None:
        self._post_uuid('dvr/entry/stop', entry)

    def cancel_dvr_entry(self, entry: DvrEntry) -> None:
        self._post_uuid('dvr/entry/cancel', entry)

    def remove_dvr_entry(self, entry: DvrEntry) -> None:
        self._post_uuid('dvr/entry/remove', entry)

    def delete_dvr_entry(self, entry: DvrEntry) -> None:
        self._post_form('idnode/delete', {'uuid': entry_uuid(entry)})

    def set_dvr_rerecord(self, entry: DvrEntry, action: str) -> None:
        action = check_choice(action, RERECORD_ACTIONS, 'Rerecord action')
        self._post_uuid(f'dvr/entry/rerecord/{action}', entry)

    def set_dvr_prevrec(self, entry: DvrEntry, action: str) -> None:
        action = check_choice(action, PREVREC_ACTIONS, 'Previously-recorded action')
        self._post_uuid(f'dvr/entry/prevrec/{action}', entry)

    def update_dvr_entry(self, entry: DvrEntry, update: DvrEntryUpdate) -> None:
        node = dvr_update_http_node(entry, update)
        self._post_form('idnode/save', {'node': json.dumps(node)})

    def move_dvr_entry(self, entry: DvrEntry, category: str) -> None:
        category = check_choice(category, MOVE_CATEGORIES, 'DVR category')
        self._post_uuid(f'dvr/entry/move/{category}', entry)

    def recording_url(self, entry: DvrEntry) -> str:
        return insert_basic_auth(
            self._recording_http_url(entry),
            self.server.username,
            self.server.password,
        )

    def open_recording(self, entry: DvrEntry) -> HttpRecordingFile:
        url = self._recording_http_url(entry)
        size = None
        try:
            response = self._session.head(
                url,
                auth=self._auth,
                timeout=self._timeout,
                allow_redirects=True,
            )
        except requests.RequestException:
            response = None
        if response is not None and response.status_code < 400:
            length = response.headers.get('Content-Length')
            if length and str(length).isdigit():
                size = int(length)
        return HttpRecordingFile(self._session, url, self._auth, self._timeout, size=size)

    def get_dvr_cutpoints(self, entry: DvrEntry) -> List[DvrCutpoint]:
        raise TvhError('DVR cutpoints are available over HTSP only (getDvrCutpoints).')

    def notify_dvr_file_moved(self, src: str, dst: str) -> None:
        self._post_form('dvr/entry/filemoved', file_move_args(src, dst))

    def list_dvr_configs(self) -> List[DvrConfig]:
        return [parse_dvr_config(raw) for raw in self._grid('api/dvr/config/grid')]

    def list_removed_dvr_entries(self) -> List[DvrEntry]:
        return [parse_dvr_entry(raw) for raw in self._grid('api/dvr/entry/grid_removed')]

    def create_dvr_entry_by_event(self, event_id: int, config_uuid: str = '') -> str:
        data = {'event_id': int(event_id)}
        if config_uuid:
            data['config_uuid'] = config_uuid
        return response_id(self._post_form('dvr/entry/create_by_event', data))

    def list_autorec_entries(self) -> List[AutorecEntry]:
        return [parse_autorec_entry(raw) for raw in self._grid('api/dvr/autorec/grid')]

    def create_autorec_entry(self, spec: AutorecSpec) -> str:
        conf = autorec_http_conf(spec, creating=True)
        return response_id(self._post_form('dvr/autorec/create', {'conf': json.dumps(conf)}))

    def update_autorec_entry(self, entry: AutorecEntry, spec: AutorecSpec) -> None:
        node = {'uuid': entry_uuid(entry)}
        node.update(autorec_http_conf(spec, creating=False))
        self._post_form('idnode/save', {'node': json.dumps(node)})

    def delete_autorec_entry(self, entry: AutorecEntry) -> None:
        self._post_form('idnode/delete', {'uuid': entry_uuid(entry)})

    def create_autorec_by_series(self, event_id: int, config_uuid: str = '') -> str:
        data = {'event_id': int(event_id)}
        if config_uuid:
            data['config_uuid'] = config_uuid
        return response_id(self._post_form('dvr/autorec/create_by_series', data))

    def list_timerec_entries(self) -> List[TimerecEntry]:
        return [parse_timerec_entry(raw) for raw in self._grid('api/dvr/timerec/grid')]

    def create_timerec_entry(self, spec: TimerecSpec) -> str:
        conf = timerec_http_conf(spec, creating=True)
        return response_id(self._post_form('dvr/timerec/create', {'conf': json.dumps(conf)}))

    def update_timerec_entry(self, entry: TimerecEntry, spec: TimerecSpec) -> None:
        node = {'uuid': entry_uuid(entry)}
        node.update(timerec_http_conf(spec, creating=False))
        self._post_form('idnode/save', {'node': json.dumps(node)})

    def delete_timerec_entry(self, entry: TimerecEntry) -> None:
        self._post_form('idnode/delete', {'uuid': entry_uuid(entry)})

    def _post_uuid(self, path, entry) -> dict:
        return self._post_form(path, {'uuid': entry_uuid(entry)})

    def _post_form(self, path, data) -> dict:
        return self._request('POST', f'api/{path.lstrip("/")}', data=data) or {}

    def _recording_http_url(self, entry: DvrEntry) -> str:
        entry_uuid(entry)
        relative = ''
        if isinstance(entry.raw, dict):
            relative = str(entry.raw.get('url') or '')
        if relative.startswith(('http://', 'https://')):
            return relative
        if not relative:
            relative = f'dvrfile/{entry.uuid}'
        return f'{self._base}/{relative.lstrip("/")}'

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

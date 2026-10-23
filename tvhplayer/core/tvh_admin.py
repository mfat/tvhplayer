"""Server administration for playlist import: networks, muxes, bouquets. No Qt imports.

These calls need the admin privilege. They stay out of ``TvhBackend``, which
is the viewing API (docs/backend.md).
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

import requests

from .errors import TvhAuthError, TvhConnectionError, TvhError
from .proxy import configure_session
from .urls import http_auth, http_base_url

DEFAULT_TIMEOUT = 30
# Playlists can be far larger than the viewing API's 10000-row grids.
ADMIN_GRID_LIMIT = 200000
SAVE_BATCH = 100
BOUQUET_WAIT_SECONDS = 10


def network_bouquet_source(network_uuid: str) -> str:
    return f'iptv-network://{network_uuid}'


class TvhAdmin:
    def __init__(self, server):
        server = server.to_dict() if hasattr(server, 'to_dict') else dict(server or {})
        self._base = http_base_url(server.get('url'))
        self._auth = http_auth(server)
        self._session = requests.Session()
        configure_session(self._session, self._base)
        self._timeout = DEFAULT_TIMEOUT

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _request(self, path, data=None, params=None):
        url = f'{self._base}/{path.lstrip("/")}'
        method = 'POST' if data is not None else 'GET'
        try:
            response = self._session.request(
                method, url, data=data, params=params, auth=self._auth, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise TvhConnectionError(str(exc)) from exc
        if response.status_code in (401, 403):
            raise TvhAuthError(f'HTTP {response.status_code} for {path}')
        if response.status_code >= 400:
            raise TvhError(f'HTTP {response.status_code} for {path}: {response.text[:200]}')
        if not response.content:
            return {}
        try:
            return json.loads(response.text, strict=False)
        except ValueError as exc:
            raise TvhError(f'Invalid JSON from {path}') from exc

    def _grid(self, path) -> List[dict]:
        data = self._request(path, params={'limit': ADMIN_GRID_LIMIT})
        return [row for row in data.get('entries') or [] if isinstance(row, dict)]

    def check_admin(self) -> None:
        """Raise ``TvhAuthError`` when this login cannot change server settings."""
        self._request('api/mpegts/network/grid', params={'limit': 1})

    def network_exists(self, uuid: str) -> bool:
        if not uuid:
            return False
        data = self._request('api/idnode/load', params={'uuid': uuid})
        return bool(data.get('entries'))

    def create_network(self, conf: dict) -> str:
        data = self._request(
            'api/mpegts/network/create',
            data={'class': 'iptv_network', 'conf': json.dumps(conf)},
        )
        return _uuid(data, 'network')

    def list_muxes(self, network_uuid: str) -> List[dict]:
        return [row for row in self._grid('api/mpegts/mux/grid') if row.get('network_uuid') == network_uuid]

    def create_mux(self, network_uuid: str, conf: dict) -> str:
        data = self._request(
            'api/mpegts/network/mux_create',
            data={'uuid': network_uuid, 'conf': json.dumps(conf)},
        )
        return _uuid(data, 'mux')

    def save(self, nodes: List[dict]) -> None:
        for start in range(0, len(nodes), SAVE_BATCH):
            batch = nodes[start:start + SAVE_BATCH]
            self._request('api/idnode/save', data={'node': json.dumps(batch)})

    def delete(self, uuids: List[str]) -> None:
        uuids = [uuid for uuid in uuids if uuid]
        for start in range(0, len(uuids), SAVE_BATCH):
            batch = uuids[start:start + SAVE_BATCH]
            self._request('api/idnode/delete', data={'uuid': json.dumps(batch)})

    def find_bouquet(self, network_uuid: str) -> Optional[dict]:
        source = network_bouquet_source(network_uuid)
        for row in self._grid('api/bouquet/grid'):
            if row.get('source') == source:
                return row
        return None

    def map_network_bouquet(self, network_uuid: str, wait=BOUQUET_WAIT_SECONDS) -> Optional[dict]:
        """Turn on channel mapping for the network's bouquet.

        Tvheadend creates the bouquet on a timer after the network asks for
        one, so this polls for it.
        """
        deadline = time.monotonic() + wait
        while True:
            bouquet = self.find_bouquet(network_uuid)
            if bouquet is not None:
                self.save([{
                    'uuid': bouquet['uuid'],
                    'enabled': True,
                    'maptoch': True,
                    'mapopt': ['mapnolcn', 'mapnoname', 'mapradio', 'encrypted'],
                }])
                return bouquet
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

    def delete_network(self, network_uuid: str) -> None:
        """Delete the network, then the channel tag its bouquet leaves behind."""
        bouquet = self.find_bouquet(network_uuid)
        tag = (bouquet or {}).get('chtag_ref') or ''
        self.delete([network_uuid])
        if tag:
            self.delete([tag])


def _uuid(data, what) -> str:
    uuid = data.get('uuid') if isinstance(data, dict) else None
    if not uuid:
        raise TvhError(f'The server did not return the new {what}')
    return uuid

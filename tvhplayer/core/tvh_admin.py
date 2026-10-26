"""Server administration for playlist import: networks, muxes, bouquets. No Qt imports.

These calls need the admin privilege. They stay out of ``TvhBackend``, which
is the viewing API (docs/backend.md).
"""

from __future__ import annotations

import json
import os
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
# mpegts_mux_t scan_state that queues a scan, as the web interface's Force Scan does.
SCAN_PENDING = 1


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

    def request(self, path, data=None, params=None):
        """One API call: POST with ``data``, GET without. Returns the decoded JSON."""
        return self._request(path, data=data, params=params)

    def _grid(self, path, **params) -> List[dict]:
        data = self._request(path, params=dict(params, limit=ADMIN_GRID_LIMIT))
        return [row for row in data.get('entries') or [] if isinstance(row, dict)]

    def check_admin(self) -> None:
        """Raise ``TvhAuthError`` when this login cannot change server settings."""
        self._request('api/mpegts/network/grid', params={'limit': 1})

    def network_exists(self, uuid: str) -> bool:
        if not uuid:
            return False
        data = self._request('api/idnode/load', params={'uuid': uuid})
        return bool(data.get('entries'))

    def has_network_bouquets(self, network_uuid: str) -> bool:
        """Whether the network can map its services to channels with a bouquet.

        Tvheadend 4.3 and newer can; 4.2 has no such setting.
        """
        return 'bouquet' in self._node(network_uuid)

    def update_network(self, uuid: str, conf: dict) -> None:
        """Save the fields of ``conf`` that differ on the server."""
        node = self._node(uuid)
        changed = {key: value for key, value in conf.items() if node.get(key) != value}
        if changed:
            self.save([dict(changed, uuid=uuid)])

    def create_network(self, conf: dict) -> str:
        data = self._request(
            'api/mpegts/network/create',
            data={'class': 'iptv_network', 'conf': json.dumps(conf)},
        )
        return _uuid(data, 'network')

    def list_muxes(self, network_uuid: str, fields=None) -> List[dict]:
        """The network's muxes; with ``fields``, only those fields of each."""
        # The default hidemode leaves out every mux of a disabled network.
        params = {'hidemode': 'none'}
        if fields:
            params['list'] = ','.join({'uuid', 'network_uuid', *fields})
        rows = self._grid('api/mpegts/mux/grid', **params)
        return [row for row in rows if row.get('network_uuid') == network_uuid]

    def list_services(self, mux_uuids, fields=None) -> List[dict]:
        """Services of these muxes, including unverified and disabled ones.

        With ``fields``, only those fields of each.
        """
        mux_uuids = set(mux_uuids)
        params = {'hidemode': 'none'}
        if fields:
            params['list'] = ','.join({'uuid', 'multiplex_uuid', *fields})
        rows = self._grid('api/mpegts/service/grid', **params)
        return [row for row in rows if row.get('multiplex_uuid') in mux_uuids]

    def scan_network(self, network_uuid: str) -> None:
        """Queue a scan of every mux in the network."""
        self._request('api/mpegts/network/scan', data={'uuid': network_uuid})

    def scan_muxes(self, uuids: List[str]) -> None:
        """Queue a scan of these muxes only."""
        self.save([{'uuid': uuid, 'scan_state': SCAN_PENDING} for uuid in uuids])

    def create_mux(self, network_uuid: str, conf: dict) -> str:
        data = self._request(
            'api/mpegts/network/mux_create',
            data={'uuid': network_uuid, 'conf': json.dumps(conf)},
        )
        return _uuid(data, 'mux')

    def hardware_tree(self, uuid: str = 'root') -> List[dict]:
        """Hardware and its tuners: ``root`` lists the hardware, a node's uuid its children."""
        data = self._request('api/hardware/tree', params={'uuid': uuid})
        return data if isinstance(data, list) else []

    def list_tuner_muxes(self) -> List[dict]:
        """Muxes received with a tuner. IPTV muxes, which carry a URL, are left out."""
        return [row for row in self._grid('api/mpegts/mux/grid', hidemode='none') if 'iptv_url' not in row]

    def list_services_all(self, fields=None) -> List[dict]:
        """Every service, including unverified and disabled ones; with ``fields``, only those fields of each."""
        return self._grid('api/mpegts/service/grid', hidemode='none', **_only(fields))

    def list_channels(self, fields=None) -> List[dict]:
        """Every channel; with ``fields``, only those fields of each."""
        return self._grid('api/channel/grid', **_only(fields))

    def list_all_muxes(self, fields=None) -> List[dict]:
        """Every mux; with ``fields``, only those fields of each."""
        return self._grid('api/mpegts/mux/grid', hidemode='none', **_only(fields))

    def list_guide_channels(self) -> List[dict]:
        """The channels every EPG grabber has seen, with the TV channels each feeds."""
        return self._grid('api/epggrab/channel/grid')

    def has_programmes(self, channel_uuid: str) -> bool:
        """Whether the server's EPG holds any programme for this channel."""
        data = self._request('api/epg/events/grid', params={'channel': channel_uuid, 'limit': 1})
        return bool(data.get('totalCount') or data.get('entries'))

    def keep_guide_after_import(self) -> None:
        """Have the server save its EPG after each XMLTV import, so a crash keeps it."""
        entries = self._request('api/epggrab/config/load').get('entries') or []
        params = {param.get('id'): param.get('value') for param in (entries[0].get('params') or [])} if entries else {}
        if not params.get('epgdb_saveafterimport'):
            self._request('api/epggrab/config/save', data={'node': json.dumps({'epgdb_saveafterimport': True})})

    def create_channel(self, conf: dict) -> str:
        data = self._request('api/channel/create', data={'conf': json.dumps(conf)})
        return _uuid(data, 'channel')

    def list_channel_tags(self) -> List[dict]:
        return self._grid('api/channeltag/grid')

    def create_channel_tag(self, conf: dict) -> str:
        data = self._request('api/channeltag/create', data={'conf': json.dumps(conf)})
        return _uuid(data, 'channel tag')

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

    def delete_orphan_channels(self, network_uuid: str) -> int:
        """Delete the network bouquet's channels that lost their service.

        Such a channel shows as ``{name-not-set}`` and has nothing to play.
        Servers that older versions filled with duplicate playlists have them.
        """
        bouquet = self.find_bouquet(network_uuid)
        if bouquet is None:
            return 0
        orphans = [
            row['uuid'] for row in self._grid('api/channel/grid')
            if row.get('bouquet') == bouquet['uuid'] and not row.get('services') and row.get('uuid')
        ]
        self.delete(orphans)
        return len(orphans)

    def _node(self, uuid: str) -> dict:
        """One idnode as {'class': ..., 'uuid': ..., <param id>: <value>}."""
        entries = self._request('api/idnode/load', params={'uuid': uuid}).get('entries') or []
        if not entries:
            return {}
        entry = entries[0]
        node = {param.get('id'): param.get('value') for param in entry.get('params') or []}
        node.update({'class': entry.get('class'), 'uuid': uuid})
        return node

    def _epggrab_modules(self) -> List[dict]:
        return [row for row in self._request('api/epggrab/module/list').get('entries') or [] if row.get('uuid')]

    def enable_xmltv_socket(self, wait=5) -> str:
        """Turn on the External XMLTV module and return its socket path, or ''."""
        for row in self._epggrab_modules():
            node = self._node(row['uuid'])
            if node.get('class') != 'epggrab_mod_ext_xmltv':
                continue
            path = node.get('path') or ''
            if not node.get('enabled'):
                self.save([{'uuid': row['uuid'], 'enabled': True}])
            deadline = time.monotonic() + wait
            while path and not os.path.exists(path) and time.monotonic() < deadline:
                time.sleep(0.2)
            return path
        return ''

    def use_url_grabber(self, url: str) -> bool:
        """Point an installed ``tv_grab_url`` grabber at ``url`` and run it."""
        for row in self._epggrab_modules():
            if (row.get('title') or '').endswith('XMLTV URL grabber'):
                self.save([{'uuid': row['uuid'], 'enabled': True, 'args': url}])
                self._request('api/epggrab/internal/rerun', data={'rerun': 1})
                return True
        return False

    def delete_unused_tags(self, names: List[str], wait=BOUQUET_WAIT_SECONDS) -> None:
        """Delete channel tags with these names once no channel carries them.

        Tvheadend drops a deleted network's channels on a timer, so this
        waits for their tags to be released.
        """
        names = set(names or [])
        if not names:
            return
        deadline = time.monotonic() + wait
        while True:
            tags = [row for row in self._grid('api/channeltag/grid') if row.get('name') in names]
            used = {tag for row in self._grid('api/channel/grid') for tag in row.get('tags') or []}
            unused = [row['uuid'] for row in tags if row.get('uuid') not in used]
            if len(unused) == len(tags) or time.monotonic() >= deadline:
                self.delete(unused)
                return
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


def _only(fields) -> dict:
    """Grid parameters that ask for just ``fields`` and the uuid; all of them without."""
    return {'list': ','.join(sorted({'uuid', *fields}))} if fields else {}

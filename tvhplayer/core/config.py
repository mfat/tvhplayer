"""Load and save TVHplayer settings. No Qt imports."""

from __future__ import annotations

import json
import logging
import os
import sys
from copy import deepcopy
from pathlib import Path

from .models import ServerConfig

log = logging.getLogger(__name__)

DEFAULT_GEOMETRY = {'x': 100, 'y': 100, 'width': 1200, 'height': 700}


def default_config_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'TVHplayer'
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home()) / 'TVHplayer'
    xdg = os.environ.get('XDG_CONFIG_HOME')
    base = Path(xdg) if xdg else Path.home() / '.config'
    return base / 'tvhplayer'


def default_config_path():
    return default_config_dir() / 'tvhplayer.conf'


def default_config():
    return {
        'volume': 50,
        'last_server': 0,
        'recording_path': str(Path.home()),
        'window_geometry': dict(DEFAULT_GEOMETRY),
        'servers': [],
        'builtin_autostart': False,
        'builtin_http_port': 0,
        'builtin_htsp_port': 0,
    }


def _normalize(data):
    cfg = default_config()
    if not isinstance(data, dict):
        return cfg
    cfg.update(data)
    geometry = data.get('window_geometry') or {}
    merged_geo = dict(DEFAULT_GEOMETRY)
    if isinstance(geometry, dict):
        merged_geo.update({k: geometry[k] for k in DEFAULT_GEOMETRY if k in geometry})
    cfg['window_geometry'] = merged_geo
    servers = []
    for raw in data.get('servers') or []:
        servers.append(ServerConfig.from_dict(raw).to_dict())
    cfg['servers'] = servers
    try:
        cfg['last_server'] = int(cfg.get('last_server') or 0)
    except (TypeError, ValueError):
        cfg['last_server'] = 0
    try:
        cfg['volume'] = int(cfg.get('volume') or 50)
    except (TypeError, ValueError):
        cfg['volume'] = 50
    cfg['builtin_autostart'] = bool(cfg.get('builtin_autostart'))
    for key in ('builtin_http_port', 'builtin_htsp_port'):
        try:
            cfg[key] = int(cfg.get(key) or 0)
        except (TypeError, ValueError):
            cfg[key] = 0
    return cfg


class ConfigStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_config_path()
        self.data = default_config()
        self.load()

    def load(self):
        try:
            if self.path.exists():
                with self.path.open('r', encoding='utf-8') as handle:
                    self.data = _normalize(json.load(handle))
            else:
                self.data = default_config()
        except (OSError, json.JSONDecodeError) as exc:
            log.warning('Could not load config from %s: %s', self.path, exc)
            self.data = default_config()
        return self.data

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _normalize(self.data)
        with self.path.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2)
        self.data = payload
        return payload

    @property
    def servers(self):
        return self.data.setdefault('servers', [])

    @servers.setter
    def servers(self, value):
        self.data['servers'] = [
            ServerConfig.from_dict(item).to_dict() if isinstance(item, dict) else item.to_dict()
            for item in (value or [])
        ]

    def snapshot(self):
        return deepcopy(self.data)

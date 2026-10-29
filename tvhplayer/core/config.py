"""Load and save TVHplayer settings. No Qt imports."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from .builtin_server import without_builtin_secrets
from .channel_info import channel_list_options
from .guide_feeds import GuideSource
from .guide_match import Choice
from .models import ServerConfig
from .player import DEINTERLACE_AUTO, DEINTERLACE_MODES
from .playlist_sync import PlaylistSource
from .recorder import DEFAULT_FORMAT, RECORDING_FORMATS
from .urls import pin_http_port

# The app's own theme; any other ui_theme value names a Qt style.
THEME_TVHPLAYER = 'TVHplayer'
# Light or dark: as the desktop is, or always one of them.
SCHEME_SYSTEM = 'system'
SCHEME_LIGHT = 'light'
SCHEME_DARK = 'dark'
SCHEME_CHOICES = (SCHEME_SYSTEM, SCHEME_LIGHT, SCHEME_DARK)

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


def default_cache_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'TVHplayer'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'TVHplayer' / 'Cache'
    xdg = os.environ.get('XDG_CACHE_HOME')
    base = Path(xdg) if xdg else Path.home() / '.cache'
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
        'playlists': [],
        'channel_list': channel_list_options(None),
        'play_on_start': False,
        'last_channel': {},
        'cast_profiles': {},
        'cast_auto_profiles': {},
        'hide_dead_channels': True,
        # Empty until chosen: the Videos folder, or asked the first time where that cannot be written.
        'local_recording_dir': '',
        'local_recording_format': DEFAULT_FORMAT,
        'local_recording_ffmpeg_options': '',
        'convert_after_recording': False,
        # Empty while it is the default, so a better default reaches everyone.
        'convert_options': '',
        'delete_converted_original': False,
        # Block sleep until scheduled recordings on this computer are done, not only while recording.
        'stay_awake_for_scheduled': True,
        'deinterlace': DEINTERLACE_AUTO,
        # TVHplayer's own look, or the name of a Qt style. Read before the window is built.
        'ui_theme': THEME_TVHPLAYER,
        'color_scheme': SCHEME_SYSTEM,
        # On GNOME and KDE, the app's own title bar instead of the desktop's. Read before the window is built.
        'own_title_bar': False,
        # None until chosen: live resize is off before Qt 6.11, and on from 6.11.
        'live_resize': None,
        # Minutes the built-in server starts recordings early and ends them late.
        'builtin_padding_early': 2,
        'builtin_padding_late': 5,
        # Warn when the recordings folder has less than this many GB free; 0 never warns.
        'low_space_gb': 5,
        # Set Up Channels opens by itself once, when the built-in server first has no channels.
        'setup_offered': False,
        # Programme guides for servers on this computer, and each channel's guide
        # chosen by hand: {server key: {channel uuid: choice}}.
        'guide_sources': [],
        'guide_choices': {},
        # Missing from configs saved when a port-less http:// address meant port 80.
        'http_ports_pinned': True,
        # Ask GitHub about a newer release at most once a day; the time is seconds since the epoch.
        'check_for_updates': True,
        'last_update_check': 0.0,
        # A release the user chose not to hear about again; a later one is shown.
        'skipped_update_version': '',
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
    if not data.get('http_ports_pinned'):
        for server in servers:
            if not server['builtin']:
                server['url'] = pin_http_port(server['url'])
    cfg['servers'] = servers
    cfg['http_ports_pinned'] = True
    cfg['playlists'] = [
        PlaylistSource.from_dict(raw).to_dict()
        for raw in data.get('playlists') or []
        if isinstance(raw, dict)
    ]
    cfg['guide_sources'] = [
        GuideSource.from_dict(raw).to_dict()
        for raw in data.get('guide_sources') or []
        if isinstance(raw, dict) and raw.get('location')
    ]
    cfg['guide_choices'] = _guide_choices(data.get('guide_choices'))
    try:
        cfg['last_server'] = int(cfg.get('last_server') or 0)
    except (TypeError, ValueError):
        cfg['last_server'] = 0
    try:
        cfg['volume'] = max(0, min(100, int(cfg.get('volume', 50))))
    except (TypeError, ValueError):
        cfg['volume'] = 50
    cfg['channel_list'] = channel_list_options(data.get('channel_list'))
    cfg['builtin_autostart'] = bool(cfg.get('builtin_autostart'))
    for key in (
        'play_on_start', 'hide_dead_channels', 'convert_after_recording', 'delete_converted_original',
        'stay_awake_for_scheduled', 'setup_offered', 'own_title_bar', 'check_for_updates',
    ):
        cfg[key] = bool(cfg.get(key))
    try:
        cfg['last_update_check'] = max(0.0, float(cfg.get('last_update_check') or 0))
    except (TypeError, ValueError):
        cfg['last_update_check'] = 0.0
    # Left unset so the Qt version picks the default, until Settings saves true or false.
    cfg.pop('resize_on_release', None)
    choice = cfg.get('live_resize', None)
    cfg['live_resize'] = None if choice is None else bool(choice)
    for key in ('local_recording_dir', 'local_recording_ffmpeg_options', 'convert_options', 'skipped_update_version'):
        if not isinstance(cfg.get(key), str):
            cfg[key] = ''
    if cfg.get('deinterlace') not in DEINTERLACE_MODES:
        cfg['deinterlace'] = DEINTERLACE_AUTO
    # Legacy Settings choice (auto/mpv/vlc); playback is always libmpv now.
    cfg.pop('player_engine', None)
    if not isinstance(cfg.get('ui_theme'), str) or not cfg['ui_theme'].strip():
        cfg['ui_theme'] = THEME_TVHPLAYER
    if cfg.get('color_scheme') not in SCHEME_CHOICES:
        cfg['color_scheme'] = SCHEME_SYSTEM
    if cfg.get('local_recording_format') not in RECORDING_FORMATS:
        cfg['local_recording_format'] = DEFAULT_FORMAT
    if not isinstance(cfg.get('last_channel'), dict):
        cfg['last_channel'] = {}
    for field in ('cast_profiles', 'cast_auto_profiles'):
        profiles = cfg.get(field)
        cfg[field] = {key: value for key, value in profiles.items()
                      if isinstance(key, str) and isinstance(value, str)} if isinstance(profiles, dict) else {}
    for key in ('builtin_http_port', 'builtin_htsp_port'):
        try:
            cfg[key] = int(cfg.get(key) or 0)
        except (TypeError, ValueError):
            cfg[key] = 0
    defaults = default_config()
    for key in ('builtin_padding_early', 'builtin_padding_late', 'low_space_gb'):
        value = cfg.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            cfg[key] = defaults[key]
    return cfg


def _guide_choices(data):
    if not isinstance(data, dict):
        return {}
    result = {}
    for server, channels in data.items():
        if not isinstance(channels, dict):
            continue
        kept = {}
        for uuid, raw in channels.items():
            choice = Choice.from_dict(raw)
            if choice is not None:
                kept[str(uuid)] = choice.to_dict()
        if kept:
            result[str(server)] = kept
    return result


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
        except OSError as exc:
            log.warning('Could not load config from %s: %s', self.path, exc)
            self.data = default_config()
        except ValueError as exc:
            # Kept aside, so the next save does not replace the user's settings with defaults.
            broken = self.path.with_name(self.path.name + '.broken')
            try:
                os.replace(self.path, broken)
                log.warning('Config %s cannot be read (%s); moved it to %s', self.path, exc, broken)
            except OSError:
                log.warning('Config %s cannot be read: %s', self.path, exc)
            self.data = default_config()
        return self.data

    def save(self):
        # A link is followed, so a config kept elsewhere stays there.
        target = Path(os.path.realpath(self.path))
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _normalize(self.data)
        on_disk = dict(payload, servers=without_builtin_secrets(payload['servers']))
        # Written whole beside the old file, then swapped in: a crash or full
        # disk midway leaves the old settings. mkstemp makes it owner-only,
        # as it holds server passwords.
        fd, temp = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(on_disk, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
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

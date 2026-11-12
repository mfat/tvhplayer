"""Load and save TVHplayer settings. No Qt imports."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import atexit
from copy import deepcopy
from pathlib import Path

from .builtin_server import without_builtin_secrets
from .channel_info import channel_list_options
from .guide_feeds import GuideSource
from .guide_match import Choice
from .models import ServerConfig
from .player import DEINTERLACE_AUTO, DEINTERLACE_MODES
from .playlist_sync import PlaylistSource, valid_state_id
from .recorder import DEFAULT_FORMAT, RECORDING_FORMATS
from .urls import pin_http_port

# The app's own theme; any other ui_theme value names a Qt style.
THEME_TVHPLAYER = 'TVHplayer'
# The same, drawn in Jottr's Organic look.
THEME_ORGANIC = 'Organic'
# What a new install starts with.
DEFAULT_THEME = THEME_ORGANIC
# Light or dark: as the desktop is, or always one of them.
SCHEME_SYSTEM = 'system'
SCHEME_LIGHT = 'light'
SCHEME_DARK = 'dark'
SCHEME_CHOICES = (SCHEME_SYSTEM, SCHEME_LIGHT, SCHEME_DARK)
TIMESHIFT_MAX_GB = 500

log = logging.getLogger(__name__)

DEFAULT_GEOMETRY = {'x': 100, 'y': 100, 'width': 1200, 'height': 700}
# A playlist's channel map and stream verdicts grow with the playlist, to tens
# of megabytes, while the settings are saved on every channel change. They are
# kept in a file of their own in this folder beside the settings, named after
# the playlist's state_id, and written only when they changed.
PLAYLIST_STATE_DIR = 'playlists'
PLAYLIST_STATE_FIELDS = ('muxes', 'health')


def default_config_dir():
    profile = os.environ.get('TVHPLAYER_PROFILE_DIR')
    if profile:
        return Path(profile).expanduser().resolve() / 'Roaming' / 'TVHplayer'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'TVHplayer'
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home()) / 'TVHplayer'
    xdg = os.environ.get('XDG_CONFIG_HOME')
    base = Path(xdg) if xdg else Path.home() / '.config'
    return base / 'tvhplayer'


def default_cache_dir():
    profile = os.environ.get('TVHPLAYER_PROFILE_DIR')
    if profile:
        return Path(profile).expanduser().resolve() / 'Local' / 'TVHplayer' / 'Cache'
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
        'stream_profiles': {},
        'cast_profiles': {},
        'cast_auto_profiles': {},
        'hide_dead_channels': False,
        # Fade channels that failed the server's stream test and say Not working.
        'mark_dead_channels': True,
        # Empty until chosen: the Videos folder, or asked the first time where that cannot be written.
        'local_recording_dir': '',
        'local_recording_display': '',
        'local_recording_format': DEFAULT_FORMAT,
        'local_recording_ffmpeg_options': '',
        'convert_after_recording': False,
        # Empty while it is the default, so a better default reaches everyone.
        'convert_options': '',
        'delete_converted_original': False,
        # Block sleep until scheduled recordings on this computer are done, not only while recording.
        'stay_awake_for_scheduled': True,
        'deinterlace': DEINTERLACE_AUTO,
        # Probe a new stream for less time, so a channel's picture comes sooner.
        'fast_channel_start': False,
        # Timeshift buffer on disk, up to this many GB, instead of mpv's buffer in memory.
        'timeshift_on_disk': False,
        'timeshift_gb': 4,
        # TVHplayer's own look, or the name of a Qt style. Read before the window is built.
        'ui_theme': DEFAULT_THEME,
        'color_scheme': SCHEME_SYSTEM,
        # Keys of ui_theme.ACCENTS and ui_theme.WINDOW_COLORS, or 'default'.
        'accent_color': 'default',
        'window_color': 'default',
        # On GNOME and KDE, the app's own title bar instead of the desktop's. Read before the window is built.
        # None until chosen: on for GNOME on Wayland, off elsewhere.
        'title_bar': None,
        # None until chosen: live resize is off before Qt 6.11, and on from 6.11.
        'live_resize': None,
        # Minutes the built-in server starts recordings early and ends them late.
        'builtin_padding_early': 2,
        'builtin_padding_late': 5,
        # Warn when the recordings folder has less than this many GB free; 0 never warns.
        'low_space_gb': 5,
        # Legacy field: having offered setup is not evidence that channels exist.
        'setup_offered': False,
        'setup_started': False,
        'setup_completed': False,
        'setup_dismissed': False,
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
        'play_on_start', 'hide_dead_channels', 'mark_dead_channels', 'convert_after_recording', 'delete_converted_original',
        'stay_awake_for_scheduled', 'setup_offered', 'check_for_updates', 'fast_channel_start',
        'timeshift_on_disk', 'setup_started', 'setup_completed', 'setup_dismissed',
    ):
        cfg[key] = bool(cfg.get(key))
    try:
        cfg['last_update_check'] = max(0.0, float(cfg.get('last_update_check') or 0))
    except (TypeError, ValueError):
        cfg['last_update_check'] = 0.0
    # Left unset so the Qt version picks the default, until Settings saves true or false.
    cfg.pop('resize_on_release', None)
    # Up to 4.6 every config held own_title_bar, false unless switched on, so a
    # false one says nothing: only an earlier "on" is kept as a choice.
    earlier = cfg.pop('own_title_bar', None)
    choice = cfg.get('title_bar', None)
    if choice is None and earlier is True:
        choice = True
    cfg['title_bar'] = None if choice is None else bool(choice)
    choice = cfg.get('live_resize', None)
    cfg['live_resize'] = None if choice is None else bool(choice)
    for key in ('local_recording_dir', 'local_recording_display', 'local_recording_ffmpeg_options', 'convert_options', 'skipped_update_version'):
        if not isinstance(cfg.get(key), str):
            cfg[key] = ''
    if cfg.get('deinterlace') not in DEINTERLACE_MODES:
        cfg['deinterlace'] = DEINTERLACE_AUTO
    # Legacy Settings choice (auto/mpv/vlc); playback is always libmpv now.
    cfg.pop('player_engine', None)
    if not isinstance(cfg.get('ui_theme'), str) or not cfg['ui_theme'].strip():
        cfg['ui_theme'] = DEFAULT_THEME
    if cfg.get('color_scheme') not in SCHEME_CHOICES:
        cfg['color_scheme'] = SCHEME_SYSTEM
    for key in ('accent_color', 'window_color'):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            cfg[key] = 'default'
    if cfg.get('local_recording_format') not in RECORDING_FORMATS:
        cfg['local_recording_format'] = DEFAULT_FORMAT
    if not isinstance(cfg.get('last_channel'), dict):
        cfg['last_channel'] = {}
    for field in ('stream_profiles', 'cast_profiles', 'cast_auto_profiles'):
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
    value = cfg.get('timeshift_gb')
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= TIMESHIFT_MAX_GB:
        cfg['timeshift_gb'] = defaults['timeshift_gb']
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
        # state_id -> the (muxes, health) objects last written to its state file.
        self._written = {}
        # state_ids of the playlists in the settings this store read or wrote.
        self._known = set()
        self._written_lock = threading.Lock()
        self.load()

    def _target(self):
        # A link is followed, so a config kept elsewhere stays there.
        return Path(os.path.realpath(self.path))

    def _state_dir(self, target=None):
        return (target or self._target()).parent / PLAYLIST_STATE_DIR

    def load(self):
        # Settings still being written in the background are read as written.
        _writer_for(self._target()).flush()
        try:
            if self.path.exists():
                with self.path.open('r', encoding='utf-8') as handle:
                    raw = json.load(handle)
                from_files = self._attach_playlist_states(raw)
                self.data = _normalize(raw)
                with self._written_lock:
                    self._written = {
                        playlist['state_id']: tuple(playlist[key] for key in PLAYLIST_STATE_FIELDS)
                        for playlist in self.data['playlists'] if playlist['state_id'] in from_files
                    }
                self._known = {playlist['state_id'] for playlist in self.data['playlists']}
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

    def _attach_playlist_states(self, raw):
        """Put each playlist's state file back into it. Older configs hold it inline.

        Returns the state_ids read from their files.
        """
        found = set()
        if not isinstance(raw, dict) or not isinstance(raw.get('playlists'), list):
            return found
        folder = self._state_dir()
        for playlist in raw['playlists']:
            if not isinstance(playlist, dict) or 'muxes' in playlist:
                continue
            state_id = valid_state_id(playlist.get('state_id'))
            if not state_id:
                continue
            try:
                with open(folder / f'{state_id}.json', 'r', encoding='utf-8') as handle:
                    state = json.load(handle)
            except (OSError, ValueError) as exc:
                # The channels stay on the server; the next refresh finds them by address.
                log.warning('Could not read the saved state of playlist %s: %s', playlist.get('name'), exc)
                continue
            if isinstance(state, dict):
                for key in PLAYLIST_STATE_FIELDS:
                    if isinstance(state.get(key), dict):
                        playlist[key] = state[key]
                found.add(state_id)
        return found

    def save(self, background=False):
        """Write the settings. With ``background`` the disk is written on another thread.

        The ``muxes`` and ``health`` of a saved playlist are never changed in
        place: a change replaces the playlist's dict. That lets this compare
        them by identity and hand them to the writer without a copy.
        """
        target = self._target()
        playlists = self.data.get('playlists')
        if isinstance(playlists, list):
            for index, raw in enumerate(playlists):
                if isinstance(raw, dict) and not valid_state_id(raw.get('state_id')):
                    # Saved by an older version, or not by this app: normalized once, which names its state file.
                    playlists[index] = PlaylistSource.from_dict(raw).to_dict()
        payload = _normalize(_without_playlist_states(self.data))
        heavy = {}
        for raw in self.data.get('playlists') or []:
            if isinstance(raw, dict) and valid_state_id(raw.get('state_id')):
                heavy[raw['state_id']] = tuple(
                    raw.get(key) if isinstance(raw.get(key), dict) else {} for key in PLAYLIST_STATE_FIELDS
                )
        states = {}
        for playlist in payload['playlists']:
            state = heavy.get(playlist['state_id'], ({}, {}))
            playlist['muxes'], playlist['health'] = state
            with self._written_lock:
                previous = self._written.get(playlist['state_id'])
            if previous is None or any(
                old is not new and old != new for old, new in zip(previous, state)
            ):
                states[playlist['state_id']] = state
        on_disk = _without_playlist_states(payload)
        on_disk['servers'] = without_builtin_secrets(payload['servers'])
        main = json.dumps(on_disk, indent=2)
        keep = {playlist['state_id'] for playlist in payload['playlists']}
        # Only the files of playlists removed since are deleted, never ones this store did not know.
        gone, self._known = self._known - keep, set(keep)
        with self._written_lock:
            self._written.update(states)
            for state_id in list(self._written):
                if state_id not in keep:
                    del self._written[state_id]
        writer = _writer_for(target)
        writer.submit(self, main, states, gone)
        if not background:
            writer.flush(raise_errors=True)
        self.data = payload
        return payload

    def flush(self, timeout=None):
        """Wait until background saves are on disk. False when the time ran out."""
        return _writer_for(self._target()).flush(timeout)

    def _write(self, target, main, states, gone):
        """Write state files first, then the settings that name them."""
        folder = self._state_dir(target)
        if states:
            folder.mkdir(parents=True, exist_ok=True)
        for state_id, (muxes, health) in states.items():
            try:
                _write_file(folder / f'{state_id}.json', json.dumps({'muxes': muxes, 'health': health}))
            except BaseException:
                with self._written_lock:
                    # Written again on the next save.
                    self._written.pop(state_id, None)
                raise
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_file(target, main)
        for state_id in gone:
            try:
                os.unlink(folder / f'{state_id}.json')
            except OSError:
                pass

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


def _without_playlist_states(data):
    """``data`` with playlists that leave out their state, sharing everything else."""
    result = dict(data)
    result['playlists'] = [
        {key: value for key, value in raw.items() if key not in PLAYLIST_STATE_FIELDS}
        for raw in data.get('playlists') or [] if isinstance(raw, dict)
    ]
    return result


def _write_file(target, text):
    # Written whole beside the old file, then swapped in: a crash or full
    # disk midway leaves the old one. mkstemp makes it owner-only, as the
    # settings hold server passwords.
    fd, temp = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


class _Writer:
    """Writes one settings file on its own thread, newest content first.

    Saves that come while one is written are merged: the newest settings,
    and the newest state of each playlist.
    """

    def __init__(self, target):
        self._target = target
        self._cond = threading.Condition()
        self._pending = None
        self._busy = False
        self._error = None
        self._thread = None

    def submit(self, store, main, states, gone):
        with self._cond:
            if self._pending is None:
                self._pending = [store, main, dict(states), set(gone)]
            else:
                self._pending[0] = store
                self._pending[1] = main
                for state_id in gone:
                    self._pending[2].pop(state_id, None)
                self._pending[2].update(states)
                self._pending[3] = (self._pending[3] | set(gone)) - set(states)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name='config-writer', daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def _run(self):
        while True:
            with self._cond:
                if self._pending is None:
                    self._thread = None
                    self._cond.notify_all()
                    return
                store, main, states, gone = self._pending
                self._pending = None
                self._busy = True
            error = None
            try:
                store._write(self._target, main, states, gone)
            except BaseException as exc:  # reported by flush, or logged
                error = exc
                log.warning('Could not save settings to %s: %s', self._target, exc)
            with self._cond:
                self._busy = False
                self._error = error
                self._cond.notify_all()

    def flush(self, timeout=None, raise_errors=False):
        with self._cond:
            done = self._cond.wait_for(lambda: self._pending is None and not self._busy, timeout)
            error, self._error = self._error, None
        if raise_errors and error is not None:
            raise error
        return done


_writers = {}
_writers_lock = threading.Lock()


def _writer_for(target):
    key = str(target)
    with _writers_lock:
        writer = _writers.get(key)
        if writer is None:
            writer = _writers[key] = _Writer(Path(target))
        return writer


@atexit.register
def _flush_all():
    with _writers_lock:
        writers = list(_writers.values())
    for writer in writers:
        writer.flush(timeout=30)

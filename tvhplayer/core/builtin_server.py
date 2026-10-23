"""App-owned Tvheadend: command line, ports, and startup verdict.

The child stays in the foreground. Tvheadend writes a pid file only when
``-f`` is passed, so this module does not use ``--pid``.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BUILTIN_NAME = 'Built-in Server'
STANDARD_HTTP_PORT = 9981
STANDARD_HTSP_PORT = 9982
PORT_LOW = 20000
PORT_HIGH = 45000
MAX_BIND_ATTEMPTS = 3

_BIND_FAILURE = re.compile(r'bind:\s+\S+:\d+:')
_HTTP_STARTED = 'Starting HTTP server'
_HTSP_STARTED = 'Starting HTSP server'


def platform_supports_builtin() -> bool:
    """Linux, macOS, and Flatpak. Windows is deferred."""
    return sys.platform != 'win32'


def is_builtin_server(server) -> bool:
    return bool(server and server.get('builtin'))


def bundled_binary_candidates() -> list[Path]:
    """Binaries this package may have shipped. A host install is not included."""
    candidates = [Path('/app/bin/tvheadend')]
    executable = Path(sys.executable).resolve()
    candidates.append(executable.with_name('tvheadend'))
    # macOS .app: the interpreter or launcher lives in Contents/MacOS.
    candidates.append(executable.parent / 'tvheadend')
    if executable.parent.name == 'MacOS':
        candidates.append(executable.parent.parent / 'Resources' / 'tvheadend')
    frozen_root = getattr(sys, '_MEIPASS', None)
    if frozen_root:
        candidates.append(Path(frozen_root) / 'tvheadend')
    return candidates


def find_bundled_binary() -> Path | None:
    seen = set()
    for path in bundled_binary_candidates():
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def builtin_config_dir(app_config_dir) -> Path:
    return Path(app_config_dir) / 'tvheadend'


def command_args(binary, config_dir, http_port: int, htsp_port: int) -> list[str]:
    """Foreground command. No ``-f``, ``-C``, ``--pid``, ``--logfile``, or ``--nostderr``."""
    return [
        str(binary),
        '-c', str(config_dir),
        '-B',
        '--bindaddr', '127.0.0.1',
        '--noacl',
        '--http_port', str(int(http_port)),
        '--htsp_port', str(int(htsp_port)),
    ]


def _usable_port(port, blocked) -> bool:
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if port < 1 or port > 65535:
        return False
    if port in (STANDARD_HTTP_PORT, STANDARD_HTSP_PORT):
        return False
    return port not in blocked


def _pick_port(rng, blocked) -> int:
    for _ in range(200):
        port = rng.randint(PORT_LOW, PORT_HIGH)
        if _usable_port(port, blocked):
            return port
    raise RuntimeError('could not choose a built-in server port')


def pick_port_pair(rng=None, avoid=()):
    """Choose HTTP and HTSP ports without binding a probe socket."""
    rng = rng or random
    blocked = set(avoid)
    http_port = _pick_port(rng, blocked)
    blocked.add(http_port)
    htsp_port = _pick_port(rng, blocked)
    return http_port, htsp_port


def initial_ports(remembered_http, remembered_htsp, rng=None):
    """Use a remembered pair when it is not a Tvheadend standard port."""
    if _usable_port(remembered_http, ()) and _usable_port(remembered_htsp, (int(remembered_http),)):
        return int(remembered_http), int(remembered_htsp)
    return pick_port_pair(rng)


class StderrWatch:
    """Portable bind signal. Tvheadend keeps running after a failed bind."""

    def __init__(self):
        self.bind_failed = False
        self.http_started = False
        self.htsp_started = False
        self.bind_line = ''

    def feed_line(self, line: str) -> None:
        if _BIND_FAILURE.search(line):
            self.bind_failed = True
            self.bind_line = line.strip()
        if _HTTP_STARTED in line:
            self.http_started = True
        if _HTSP_STARTED in line:
            self.htsp_started = True

    def feed(self, text: str) -> None:
        for line in text.splitlines():
            self.feed_line(line)


class LineBuffer:
    """Split process output that arrives in partial chunks."""

    def __init__(self):
        self.watch = StderrWatch()
        self._pending = ''

    def feed(self, text: str) -> None:
        self._pending += text
        lines = self._pending.splitlines(keepends=True)
        if lines and not lines[-1].endswith(('\n', '\r')):
            self._pending = lines.pop()
        else:
            self._pending = ''
        for line in lines:
            self.watch.feed_line(line)


def startup_result(alive: bool, watch: StderrWatch, serverinfo_ok: bool) -> str:
    """Return ``ready``, ``bind_failed``, ``exited``, or ``pending``."""
    if watch.bind_failed:
        return 'bind_failed'
    if not alive:
        return 'exited'
    if watch.http_started and watch.htsp_started and serverinfo_ok:
        return 'ready'
    return 'pending'


def serverinfo_ok(http_port: int, timeout: float = 0.4) -> bool:
    url = f'http://127.0.0.1:{int(http_port)}/api/serverinfo'
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8', errors='replace'))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return False
    return isinstance(payload, dict) and any(
        key in payload for key in ('sw_version', 'api_version', 'name')
    )


def ensure_builtin_server(servers, http_port=0, htsp_port=0):
    """Return a server list that contains one permanent built-in entry."""
    servers = list(servers or [])
    if not platform_supports_builtin():
        return [server for server in servers if not is_builtin_server(server)]
    url = ''
    htsp = STANDARD_HTSP_PORT
    if _usable_port(http_port, ()) and _usable_port(htsp_port, (int(http_port),)):
        url = f'http://127.0.0.1:{int(http_port)}'
        htsp = int(htsp_port)
    found = False
    kept = []
    for server in servers:
        if not is_builtin_server(server):
            kept.append(server)
            continue
        if found:
            continue
        found = True
        entry = dict(server)
        entry['name'] = BUILTIN_NAME
        entry['builtin'] = True
        entry['protocol'] = 'http'
        entry['username'] = ''
        entry['password'] = ''
        if url:
            entry['url'] = url
            entry['htsp_port'] = htsp
        kept.append(entry)
    if not found:
        kept.append({
            'name': BUILTIN_NAME,
            'url': url,
            'username': '',
            'password': '',
            'protocol': 'http',
            'htsp_port': htsp,
            'builtin': True,
        })
    return kept


def apply_builtin_endpoint(servers, http_port: int, htsp_port: int):
    updated = []
    for server in servers or []:
        if not is_builtin_server(server):
            updated.append(server)
            continue
        entry = dict(server)
        entry['url'] = f'http://127.0.0.1:{int(http_port)}'
        entry['htsp_port'] = int(htsp_port)
        entry['builtin'] = True
        entry['name'] = BUILTIN_NAME
        updated.append(entry)
    return updated


def recording_titles(entries) -> list[str]:
    """Titles of DVR rows that are recording right now."""
    titles = []
    for entry in entries or []:
        category = entry.category() if hasattr(entry, 'category') else ''
        if category != 'recording':
            continue
        title = getattr(entry, 'title', '') or 'Untitled'
        titles.append(str(title))
    return titles


def quit_confirmation(titles, lookup_failed: bool) -> str | None:
    """Text for the quit dialog, or None when quit can proceed."""
    if titles:
        names = ', '.join(titles)
        return (
            f'A recording is currently in progress on the built-in server: {names}. '
            'Exiting TVHplayer will stop this recording. Are you sure you want to quit?'
        )
    if lookup_failed:
        return (
            'The built-in server is running and its recording list could not be read. '
            'Exiting TVHplayer will stop the built-in server. Are you sure you want to quit?'
        )
    return None

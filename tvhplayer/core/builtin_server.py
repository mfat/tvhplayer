"""App-owned Tvheadend: command line, ports, and startup verdict.

The child stays in the foreground. Tvheadend writes a pid file only when
``-f`` is passed, so this module does not use ``--pid``.

Access control stays on. The app writes a Tvheadend ``superuser`` file with a
generated password, so a web page or another local user cannot drive the
built-in server through 127.0.0.1.
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
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
STARTUP_TIMEOUT_SECONDS = 60
SUPERUSER_NAME = 'tvhplayer'

_BIND_FAILURE = re.compile(r'bind:\s+\S+:\d+:')
_HTTP_STARTED = 'Starting HTTP server'
_HTSP_STARTED = 'Starting HTSP server'


def platform_supports_builtin() -> bool:
    """Linux only, Flatpak included. Tvheadend has no supported macOS or Windows build."""
    return sys.platform.startswith('linux')


def is_builtin_server(server) -> bool:
    return bool(server and server.get('builtin'))


def builtin_requests_ready(server, running: bool) -> bool:
    """A built-in entry can be used once its child is listening."""
    if not is_builtin_server(server):
        return True
    return bool(running) and bool((server.get('url') or '').strip())


def bundled_binary_candidates() -> list[Path]:
    """Binaries this package may have shipped. A host install is not included."""
    # Flatpak, then the deb and rpm packages' private copy.
    candidates = [Path('/app/bin/tvheadend'), Path('/usr/libexec/tvhplayer/tvheadend')]
    executable = Path(sys.executable).resolve()
    candidates.append(executable.with_name('tvheadend'))
    frozen_root = getattr(sys, '_MEIPASS', None)
    if frozen_root:
        candidates.append(Path(frozen_root) / 'tvheadend')
    # Source checkout: the Tvheadend tree sits next to this repo.
    repo = Path(__file__).resolve().parents[2]
    candidates.append(repo / 'build' / 'tvheadend')
    candidates.append(repo.parent / 'tvheadend' / 'build.linux' / 'tvheadend')
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


def superuser_path(config_dir) -> Path:
    return Path(config_dir) / 'superuser'


def _read_superuser(path: Path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    username = data.get('username')
    password = data.get('password')
    if isinstance(username, str) and username and isinstance(password, str) and len(password) >= 16:
        return username, password
    return None


def ensure_superuser(config_dir) -> tuple[str, str]:
    """Return the built-in admin login, writing one on first use.

    Tvheadend reads ``<config>/superuser`` at startup and gives that account
    full rights over HTTP and HTSP. The folder and file are owner-only.
    """
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config_dir, 0o700)
    path = superuser_path(config_dir)
    existing = _read_superuser(path)
    if existing is not None:
        os.chmod(path, 0o600)
        return existing
    username = SUPERUSER_NAME
    password = secrets.token_urlsafe(24)
    payload = json.dumps({'username': username, 'password': password}, indent=2)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(payload)
    os.chmod(path, 0o600)
    return username, password


def command_args(binary, config_dir, http_port: int, htsp_port: int) -> list[str]:
    """Foreground command. No ``-f``, ``-C``, ``--pid``, ``--logfile``, ``--nostderr``, or ``--noacl``."""
    return [
        str(binary),
        '-c', str(config_dir),
        '-B',
        '--bindaddr', '127.0.0.1',
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


def _direct_opener(url, username, password):
    """Loopback opener: no http_proxy from the environment, digest login when given."""
    handlers = [urllib.request.ProxyHandler({})]
    if username:
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, url, username, password)
        handlers.append(urllib.request.HTTPDigestAuthHandler(passwords))
    return urllib.request.build_opener(*handlers)


def serverinfo_ok(http_port: int, timeout: float = 0.4, username='', password='') -> bool:
    """With access control on, Tvheadend answers ``/api`` only after a login."""
    url = f'http://127.0.0.1:{int(http_port)}/api/serverinfo'
    try:
        with _direct_opener(url, username, password).open(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8', errors='replace'))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return False
    return isinstance(payload, dict) and any(
        key in payload for key in ('sw_version', 'api_version', 'name')
    )


def ensure_builtin_server(servers, http_port=0, htsp_port=0, username='', password=''):
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
        entry['username'] = username
        entry['password'] = password
        if url:
            entry['url'] = url
            entry['htsp_port'] = htsp
        kept.append(entry)
    if not found:
        kept.append({
            'name': BUILTIN_NAME,
            'url': url,
            'username': username,
            'password': password,
            'protocol': 'http',
            'htsp_port': htsp,
            'builtin': True,
        })
    return kept


def apply_builtin_endpoint(servers, http_port: int, htsp_port: int, username='', password=''):
    updated = []
    for server in servers or []:
        if not is_builtin_server(server):
            updated.append(server)
            continue
        entry = dict(server)
        entry['url'] = f'http://127.0.0.1:{int(http_port)}'
        entry['htsp_port'] = int(htsp_port)
        entry['username'] = username
        entry['password'] = password
        entry['builtin'] = True
        entry['name'] = BUILTIN_NAME
        updated.append(entry)
    return updated


def without_builtin_secrets(servers):
    """Server dicts for the app config file. The built-in login stays in its superuser file."""
    cleaned = []
    for server in servers or []:
        if is_builtin_server(server):
            server = dict(server)
            server['username'] = ''
            server['password'] = ''
        cleaned.append(server)
    return cleaned


def find_builtin_server(servers):
    for server in servers or []:
        if is_builtin_server(server):
            return server
    return None


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

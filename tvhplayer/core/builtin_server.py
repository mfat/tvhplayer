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
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BUILTIN_NAME = 'Built-in Server'
STANDARD_HTTP_PORT = 9981
STANDARD_HTSP_PORT = 9982
PORT_LOW = 20000
PORT_HIGH = 45000
MAX_BIND_ATTEMPTS = 3
STARTUP_TIMEOUT_SECONDS = 60
SUPERUSER_NAME = 'tvhplayer'
# Tvheadend exits with 78 when another process holds its config lock.
CONFIG_LOCKED_EXIT = 78

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


# Run by the app's Python before Tvheadend: ask Linux to send SIGTERM when
# TVHplayer exits, even when it crashes or is killed, then become Tvheadend.
# Qt has no process flag for this, and the Flatpak has no setpriv.
PARENT_DEATH_LAUNCHER = (
    'import ctypes, os, signal, sys\n'
    'ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0)\n'
    'if os.getppid() != int(sys.argv[1]):\n'
    '    sys.exit(1)\n'
    'os.execv(sys.argv[2], sys.argv[2:])\n'
)


def launch_command(argv, parent_pid=None, python=None):
    """``(program, args)`` that start ``argv`` so it stops when this app stops.

    Linux only, and only when this app runs on a Python interpreter; a frozen
    build starts Tvheadend directly.
    """
    python = sys.executable if python is None else python
    if not sys.platform.startswith('linux') or getattr(sys, 'frozen', False) or not python:
        return str(argv[0]), [str(arg) for arg in argv[1:]]
    parent_pid = os.getpid() if parent_pid is None else parent_pid
    return python, ['-I', '-c', PARENT_DEATH_LAUNCHER, str(parent_pid)] + [str(arg) for arg in argv]


def _cmdline(pid, proc) -> list[str]:
    try:
        with open(f'{proc}/{pid}/cmdline', 'rb') as handle:
            raw = handle.read()
    except OSError:
        return []
    return [part.decode('utf-8', errors='replace') for part in raw.split(b'\0') if part]


def _parent_pid(pid, proc) -> int:
    try:
        with open(f'{proc}/{pid}/stat', 'r', encoding='utf-8', errors='replace') as handle:
            # The command name can hold spaces and parentheses; fields follow the last ')'.
            return int(handle.read().rsplit(')', 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return 0


def _same_dir(first, second) -> bool:
    try:
        return Path(first).resolve() == Path(second).resolve()
    except OSError:
        return False


def servers_using(config_dir, proc='/proc') -> list[tuple[int, int]]:
    """``(pid, parent pid)`` of running Tvheadend processes on this config folder."""
    found = []
    try:
        entries = os.listdir(proc)
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        argv = _cmdline(entry, proc)
        if not argv or os.path.basename(argv[0]) != 'tvheadend':
            continue
        for index, arg in enumerate(argv[:-1]):
            if arg in ('-c', '--config') and _same_dir(argv[index + 1], config_dir):
                found.append((int(entry), _parent_pid(entry, proc)))
                break
    return found


def owned_by_other_app(parent_pid, proc='/proc') -> bool:
    """True when the parent is another running TVHplayer, not init or systemd."""
    if parent_pid <= 1 or parent_pid == os.getpid():
        return False
    return any('tvhplayer' in arg.lower() for arg in _cmdline(parent_pid, proc))


def stop_leftover_servers(config_dir, timeout=10.0, proc='/proc') -> list[int]:
    """Stop built-in servers that a TVHplayer which is gone left running.

    Returns the pids it stopped. Raises ``RuntimeError`` when another running
    TVHplayer owns the server, which must be left alone.
    """
    leftovers = []
    for pid, parent in servers_using(config_dir, proc):
        if owned_by_other_app(parent, proc):
            raise RuntimeError('The built-in server is already running in another TVHplayer window.')
        leftovers.append(pid)
    for pid in leftovers:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    alive = list(leftovers)
    while alive and time.monotonic() < deadline:
        time.sleep(0.2)
        alive = [pid for pid in alive if os.path.exists(f'{proc}/{pid}') and _cmdline(pid, proc)]
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return leftovers


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


# Tvheadend's "Authentication type" (config field ``digest``): 2 is plain and digest.
PLAIN_AND_DIGEST_LOGIN = 2


def _post(http_port: int, path: str, form: dict, username='', password='', timeout: float = 2.0) -> bool:
    url = f'http://127.0.0.1:{int(http_port)}/{path}'
    body = urllib.parse.urlencode(form).encode()
    try:
        with _direct_opener(url, username, password).open(url, data=body, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, ValueError):
        return False


def apply_builtin_defaults(http_port: int, username='', password='') -> list[str]:
    """Settings that make the built-in server ready to use; returns those that failed.

    * Accept a plain login as well as digest. Tvheadend defaults to digest
      only, and VLC sends the login in the stream URL as plain (Basic), so
      playback failed with 401. The server listens on 127.0.0.1 only and keeps
      its generated password, so this opens it to no one else.
    * Turn off the first-run setup wizard, so the web interface opens on its
      normal pages. The wizard can still be started from Configuration → General.

    Applied on every start, so an older built-in config gets them too.
    """
    steps = (
        ('plain login', 'api/config/save', {'node': json.dumps({'digest': PLAIN_AND_DIGEST_LOGIN})}),
        # The handler needs a request body, even an unused one.
        ('setup wizard off', 'api/wizard/cancel', {'cancel': '1'}),
    )
    return [
        name for name, path, form in steps
        if not _post(http_port, path, form, username, password)
    ]


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
        entry['protocol'] = 'htsp'
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
            'protocol': 'htsp',
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


def upcoming_recordings(entries, now=None) -> list:
    """Enabled DVR rows still waiting to record, soonest first."""
    now = time.time() if now is None else now
    upcoming = []
    for entry in entries or []:
        category = entry.category() if hasattr(entry, 'category') else ''
        if category != 'upcoming':
            continue
        raw = getattr(entry, 'raw', None) or {}
        enabled = raw.get('enabled', True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ('0', 'false', 'no', 'off', '')
        if not enabled:
            continue
        start = int(getattr(entry, 'start', 0) or 0)
        stop = start + int(getattr(entry, 'duration', 0) or 0)
        if max(start, stop) <= now:
            continue
        upcoming.append(entry)
    return sorted(upcoming, key=lambda entry: entry.start or 0)


def when_text(start, now=None) -> str:
    """``today at 21:00``, ``tomorrow at 06:30`` or ``Sat 31 Oct at 20:15``."""
    now = time.time() if now is None else now
    moment = datetime.fromtimestamp(start)
    days = (moment.date() - datetime.fromtimestamp(now).date()).days
    clock = moment.strftime('%H:%M')
    if days <= 0:
        return f'today at {clock}'
    if days == 1:
        return f'tomorrow at {clock}'
    return f"{moment.strftime('%a %d %b')} at {clock}"


def quit_confirmation(
    titles,
    lookup_failed: bool,
    upcoming=(),
    local_recording: str = '',
    playlist_updates=(),
    now=None,
    conversions=(),
) -> str | None:
    """Text for the quit dialog, or None when quit can proceed.

    ``titles`` and ``upcoming`` come from the built-in server; ``lookup_failed``
    says its recording list could not be read. ``local_recording`` names what is
    being recorded to this computer; ``conversions`` names recordings being
    converted for editing. ``playlist_updates`` only adds a note when
    there is already a reason to ask.
    """
    reasons = []
    if local_recording:
        reasons.append(
            f'A recording to this computer is in progress: {local_recording}. '
            'Quitting stops it and the file ends there.'
        )
    if conversions:
        reasons.append(
            f'Converting for editing: {", ".join(conversions)}. '
            'Quitting stops the conversion; the original recording is kept.'
        )
    if titles:
        names = ', '.join(titles)
        reasons.append(
            f'A recording is in progress on the built-in server: {names}. '
            'Quitting stops this recording.'
        )
    if upcoming:
        first = upcoming[0]
        title = getattr(first, 'title', '') or 'Untitled'
        text = f'{title} {when_text(first.start, now)}'
        if len(upcoming) > 1:
            text += f' (and {len(upcoming) - 1} more)'
        reasons.append(
            f'Recordings are scheduled on the built-in server. Next: {text}. '
            'They will not be recorded while TVHplayer is closed.'
        )
    if lookup_failed and not titles and not upcoming:
        reasons.append(
            'The built-in server is running and its recording list could not be read. '
            'Quitting stops the built-in server.'
        )
    if not reasons:
        return None
    if playlist_updates:
        reasons.append(
            f'A playlist update is still running ({", ".join(playlist_updates)}). '
            'It runs again the next time the built-in server starts.'
        )
    return '\n\n'.join(reasons + ['Are you sure you want to quit?'])

"""Log files in the platform's per-user state folder. No Qt imports.

Linux follows the XDG Base Directory spec: ``$XDG_STATE_HOME/tvhplayer``,
which is ``~/.local/state/tvhplayer`` by default. Flatpak points
``XDG_STATE_HOME`` inside the app's sandbox folder.

``app.log`` has the app's messages, including what it prints. ``tvheadend.log``
has the built-in server's output. Both rotate at 10 MB and keep 5 old files.
"""

from __future__ import annotations

import io
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
APP_LOG = 'app.log'
SERVER_LOG = 'tvheadend.log'
SERVER_LOGGER = 'tvhplayer.tvheadend'
OUTPUT_LOGGER = 'tvhplayer.output'

_SECRET_VALUE = re.compile(
    r'(?i)(["\']?(?:password|passwd|secret|token|api[_-]?key)["\']?\s*[:=]\s*)'
    r'(?:"[^"]*"|\'[^\']*\'|[^\s,;}\]]+)'
)
_URL_LOGIN = re.compile(r'(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):[^@\s/]+@')
_AUTHORIZATION = re.compile(r'(?i)(\bauthorization\s*:\s*(?:basic|digest|bearer)\s+)[^\r\n]+')


def log_dir() -> Path:
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Logs' / 'TVHplayer'
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local')
        return Path(base) / 'TVHplayer' / 'Logs'
    state = os.environ.get('XDG_STATE_HOME')
    base = Path(state) if state else Path.home() / '.local' / 'state'
    return base / 'tvhplayer'


def sanitize(text: str) -> str:
    """Hide passwords, URL logins, and auth headers."""
    text = _URL_LOGIN.sub(r'\1:***@', str(text))
    text = _AUTHORIZATION.sub(r'\1***', text)
    return _SECRET_VALUE.sub(r'\1***', text)


class SanitizingFormatter(logging.Formatter):
    def format(self, record):
        return sanitize(super().format(record))


def _file_handler(path: Path) -> logging.Handler:
    handler = RotatingFileHandler(
        str(path),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8',
        errors='backslashreplace',
    )
    handler.setFormatter(SanitizingFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    handler._tvhplayer_managed = True
    return handler


class _Tee(io.TextIOBase):
    """Keep writing to the real stream and copy each finished line to a logger."""

    def __init__(self, stream, logger, level):
        super().__init__()
        self._stream = stream
        self._logger = logger
        self._level = level
        self._pending = ''

    def write(self, text):
        if self._stream is not None:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
        self._pending += text
        while '\n' in self._pending:
            line, self._pending = self._pending.split('\n', 1)
            if line.strip():
                self._logger.log(self._level, line.rstrip())
        return len(text)

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return bool(self._stream is not None and self._stream.isatty())

    @property
    def encoding(self):
        return getattr(self._stream, 'encoding', 'utf-8')


def configure_logging(directory=None, capture_output=True) -> Path:
    """Write app.log and tvheadend.log; return the folder.

    ``capture_output`` copies print() and stderr into app.log while they still
    reach the terminal. A folder that cannot be created leaves logging on the
    console only.
    """
    directory = Path(directory) if directory is not None else log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        app_handler = _file_handler(directory / APP_LOG)
        server_handler = _file_handler(directory / SERVER_LOG)
    except OSError as exc:
        print(f'Warning: could not open the log folder {directory}: {exc}', file=sys.stderr)
        return directory

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, '_tvhplayer_managed', False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(logging.DEBUG)
    root.addHandler(app_handler)
    # One line per HTTP request would bury the app's own messages.
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    console = logging.StreamHandler(sys.__stderr__)
    console.setLevel(logging.WARNING)
    console.setFormatter(SanitizingFormatter('%(levelname)s: %(name)s: %(message)s'))
    console._tvhplayer_managed = True
    root.addHandler(console)

    server = logging.getLogger(SERVER_LOGGER)
    for handler in list(server.handlers):
        server.removeHandler(handler)
        handler.close()
    server.propagate = False
    server.setLevel(logging.DEBUG)
    server.addHandler(server_handler)

    if capture_output:
        output = logging.getLogger(OUTPUT_LOGGER)
        output.handlers = [app_handler]
        output.propagate = False
        output.setLevel(logging.DEBUG)
        if not isinstance(sys.stdout, _Tee):
            sys.stdout = _Tee(sys.stdout, output, logging.INFO)
        if not isinstance(sys.stderr, _Tee):
            sys.stderr = _Tee(sys.stderr, output, logging.WARNING)
    logging.getLogger('tvhplayer').info('Logging to %s', directory)
    return directory

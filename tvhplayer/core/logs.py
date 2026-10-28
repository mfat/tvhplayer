"""Log files in the platform's per-user state folder. No Qt imports.

Linux follows the XDG Base Directory spec: ``$XDG_STATE_HOME/tvhplayer``,
which is ``~/.local/state/tvhplayer`` by default. Flatpak points
``XDG_STATE_HOME`` inside the app's sandbox folder.

``app.log`` has the app's messages and everything the process writes to its
terminal, including mpv and Qt. ``tvheadend.log``
has the built-in server's output. Both rotate at 10 MB and keep 5 old files.
"""

from __future__ import annotations

import atexit
import io
import logging
import os
import re
import sys
import threading
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


class _FdCapture:
    """Route a file descriptor through a pipe.

    Everything written to it, by Python, mpv, Qt, or a child program, reaches
    the terminal with secrets hidden, and each line goes to app.log.
    """

    def __init__(self, fd, logger, level):
        self.fd = fd
        self.terminal = os.dup(fd)
        read_end, write_end = os.pipe()
        os.dup2(write_end, fd)
        os.close(write_end)
        self._read_end = read_end
        self._logger = logger
        self._level = level
        self._thread = threading.Thread(target=self._pump, name=f'log-fd{fd}', daemon=True)
        self._thread.start()

    def _pump(self):
        pending = b''
        while True:
            try:
                chunk = os.read(self._read_end, 65536)
            except OSError:
                break
            if not chunk:
                break
            pending += chunk
            *lines, pending = pending.split(b'\n')
            for raw in lines:
                self._emit(raw)
        if pending:
            self._emit(pending)
        os.close(self._read_end)

    def _emit(self, raw):
        text = sanitize(raw.decode('utf-8', errors='replace').rstrip('\r'))
        try:
            os.write(self.terminal, (text + '\n').encode('utf-8', errors='replace'))
        except OSError:
            pass
        if text.strip():
            try:
                self._logger.log(self._level, text)
            except Exception:  # a broken log file must not stop the program's output
                pass

    def close(self, timeout=1.0):
        """Point the descriptor back at the terminal and let the pipe drain."""
        os.dup2(self.terminal, self.fd)
        self._thread.join(timeout)


class _Tee(io.TextIOBase):
    """Where descriptors cannot be redirected: copy Python's own output to a logger."""

    def __init__(self, stream, logger, level):
        super().__init__()
        self._stream = stream
        self._logger = logger
        self._level = level
        self._pending = ''

    def write(self, text):
        self._pending += text
        while '\n' in self._pending:
            line, self._pending = self._pending.split('\n', 1)
            line = sanitize(line.rstrip())
            if self._stream is not None:
                try:
                    self._stream.write(line + '\n')
                except (OSError, ValueError):
                    pass
            if line.strip():
                self._logger.log(self._level, line)
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


_captures = {}


def _stop_captures():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    for fd in list(_captures):
        _captures.pop(fd).close()


def _capture(output):
    """Capture fds 1 and 2 on POSIX; elsewhere wrap sys.stdout and sys.stderr."""
    if os.name != 'posix':
        if not isinstance(sys.stdout, _Tee):
            sys.stdout = _Tee(sys.stdout, output, logging.INFO)
        if not isinstance(sys.stderr, _Tee):
            sys.stderr = _Tee(sys.stderr, output, logging.WARNING)
        return None
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    if not _captures:
        _captures[1] = _FdCapture(1, output, logging.INFO)
        _captures[2] = _FdCapture(2, output, logging.WARNING)
        atexit.register(_stop_captures)
    for stream in (sys.stdout, sys.stderr):
        # A pipe is block-buffered by default; keep messages in step with events.
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            try:
                reconfigure(line_buffering=True)
            except (OSError, ValueError):
                pass
    return _captures[2].terminal


def configure_logging(directory=None, capture_output=True) -> Path:
    """Write app.log and tvheadend.log; return the folder.

    ``capture_output`` copies the process's stdout and stderr into app.log
    while they still reach the terminal, with secrets hidden in both. A
    folder that cannot be created leaves logging on the console only.
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
    server = logging.getLogger(SERVER_LOGGER)
    for handler in list(server.handlers):
        server.removeHandler(handler)
        handler.close()
    server.propagate = False
    server.setLevel(logging.DEBUG)
    server.addHandler(server_handler)

    terminal = None
    if capture_output:
        output = logging.getLogger(OUTPUT_LOGGER)
        output.handlers = [app_handler]
        output.propagate = False
        output.setLevel(logging.DEBUG)
        terminal = _capture(output)
    # Warnings from loggers also reach the terminal, written straight to it so
    # the capture does not copy them into app.log a second time.
    stream = os.fdopen(os.dup(terminal), 'w', buffering=1) if terminal is not None else sys.__stderr__
    console = logging.StreamHandler(stream)
    console.setLevel(logging.WARNING)
    console.setFormatter(SanitizingFormatter('%(levelname)s: %(name)s: %(message)s'))
    console._tvhplayer_managed = True
    root.addHandler(console)
    logging.getLogger('tvhplayer').info('Logging to %s', directory)
    return directory

"""One desktop instance per user and configuration, with local show activation."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QLockFile, QStandardPaths, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class AppInstance(QObject):
    show_requested = pyqtSignal()

    def __init__(self, config_dir, parent=None):
        super().__init__(parent)
        directory = Path(config_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        identity = f'{Path.home().resolve()}:{directory}'
        name = 'tvhplayer-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
        if sys.platform == 'win32':
            self.name = name
        else:
            runtime = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation))
            # Flatpak's /tmp is private to each sandbox instance. This per-app
            # runtime directory is shared across invocations of the same app.
            app_id = os.environ.get('FLATPAK_ID')
            if app_id:
                runtime = runtime / 'app' / app_id
            self.name = str(runtime / name)
        self.lock_path = str(directory / 'desktop.lock')
        self.lock = QLockFile(self.lock_path) if sys.platform == 'win32' else None
        if self.lock is not None:
            self.lock.setStaleLockTime(0)
        self._lock_fd = None
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        self.owned = False

    def _try_lock(self):
        if self.lock is not None:
            return self.lock.tryLock()
        # Kernel locks work across Flatpak PID namespaces. PID-based stale-lock
        # detection cannot safely identify an owner in another sandbox instance.
        import fcntl
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        except OSError:
            os.close(fd)
            raise
        self._lock_fd = fd
        return True

    def _unlock(self):
        if self.lock is not None:
            self.lock.unlock()
        elif self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def acquire(self):
        """Return True for the owner, False after activating it; raise on failure."""
        if not self._try_lock():
            socket = QLocalSocket(self)
            socket.connectToServer(self.name)
            if not socket.waitForConnected(3000):
                socket.deleteLater()
                raise RuntimeError('TVHplayer is already starting or stopping. Try opening it again shortly.')
            socket.write(b'show\n')
            sent = socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            socket.deleteLater()
            if not sent:
                raise RuntimeError('Could not ask the running TVHplayer to open its window.')
            return False
        # Only the proven lock owner may remove a socket left by a crashed owner.
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self._unlock()
            raise RuntimeError('Could not create the TVHplayer activation channel.')
        self.owned = True
        return True

    def _connected(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(16)
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(2000)
            self._read(socket)

    def _read(self, socket):
        if socket.canReadLine():
            if bytes(socket.readLine(16)) == b'show\n':
                self.show_requested.emit()
            socket.disconnectFromServer()

    def close(self):
        if self.owned:
            self.server.close()
            self._unlock()
            self.owned = False

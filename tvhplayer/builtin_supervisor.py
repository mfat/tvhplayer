"""QProcess owner for the built-in Tvheadend."""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

try:
    from .core.builtin_server import (
        MAX_BIND_ATTEMPTS,
        STARTUP_TIMEOUT_SECONDS,
        LineBuffer,
        command_args,
        ensure_superuser,
        initial_ports,
        pick_port_pair,
        serverinfo_ok,
        startup_result,
    )
except ImportError:
    from core.builtin_server import (
        MAX_BIND_ATTEMPTS,
        STARTUP_TIMEOUT_SECONDS,
        LineBuffer,
        command_args,
        ensure_superuser,
        initial_ports,
        pick_port_pair,
        serverinfo_ok,
        startup_result,
    )


class BuiltinSupervisor(QObject):
    """Start, watch, and stop the shipped tvheadend child."""

    status_changed = pyqtSignal(str)
    ready = pyqtSignal(int, int)
    failed = pyqtSignal(str)

    def __init__(self, binary, config_dir, http_port=0, htsp_port=0, parent=None):
        super().__init__(parent)
        self.binary = binary
        self.config_dir = config_dir
        self.http_port = int(http_port or 0)
        self.htsp_port = int(htsp_port or 0)
        self.username = ''
        self.password = ''
        self.startup_timeout = STARTUP_TIMEOUT_SECONDS
        self._deadline = 0.0
        self._status = 'stopped'
        self._attempts = 0
        self._lines = LineBuffer()
        self._log = []
        self._stop_requested = False
        self._handling_exit = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._poll_ready)

    @property
    def status(self) -> str:
        return self._status

    def is_running(self) -> bool:
        return self._status == 'running' and self._child_alive()

    def log_text(self) -> str:
        return ''.join(self._log)

    def start(self) -> None:
        if self._status in ('starting', 'running'):
            return
        if self.binary is None:
            self._set_status('failed')
            self.failed.emit('Built-in Tvheadend is not packaged in this build.')
            return
        try:
            self.username, self.password = ensure_superuser(self.config_dir)
        except OSError as exc:
            self._set_status('failed')
            self.failed.emit(f'Could not set up the built-in server login: {exc}')
            return
        self._stop_requested = False
        self._attempts = 0
        self.http_port, self.htsp_port = initial_ports(self.http_port, self.htsp_port)
        self._start_attempt()

    def stop(self) -> None:
        self._stop_requested = True
        self._poll.stop()
        if self._child_alive():
            self._handling_exit = True
            self.process.terminate()
            if not self.process.waitForFinished(5000):
                self.process.kill()
                self.process.waitForFinished(2000)
            self._handling_exit = False
        self._set_status('stopped')

    def _start_attempt(self) -> None:
        self._attempts += 1
        self._lines = LineBuffer()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        args = command_args(self.binary, self.config_dir, self.http_port, self.htsp_port)[1:]
        self._set_status('starting')
        self._deadline = time.monotonic() + self.startup_timeout
        self.process.start(str(self.binary), args)
        self._poll.start()

    def _on_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        if not data:
            return
        self._log.append(data)
        if len(self._log) > 400:
            self._log = self._log[-400:]
        self._lines.feed(data)
        if self._status == 'starting' and self._lines.watch.bind_failed:
            self._retry_or_fail(self._lines.watch.bind_line or 'bind failed')

    def _poll_ready(self) -> None:
        if self._status != 'starting':
            return
        result = startup_result(self._child_alive(), self._lines.watch, False)
        if result == 'bind_failed':
            self._retry_or_fail(self._lines.watch.bind_line or 'bind failed')
            return
        if result == 'exited':
            return
        if time.monotonic() > self._deadline:
            self._retry_or_fail(
                f'Built-in Tvheadend did not answer within {int(self.startup_timeout)} seconds.'
            )
            return
        if not (self._lines.watch.http_started and self._lines.watch.htsp_started):
            return
        if not serverinfo_ok(self.http_port, username=self.username, password=self.password):
            return
        result = startup_result(True, self._lines.watch, True)
        if result == 'ready':
            self._poll.stop()
            self._set_status('running')
            self.ready.emit(self.http_port, self.htsp_port)

    def _retry_or_fail(self, reason: str) -> None:
        if self._status != 'starting' or self._handling_exit:
            return
        self._poll.stop()
        retry = self._attempts < MAX_BIND_ATTEMPTS and self._lines.watch.bind_failed
        self._handling_exit = True
        if self._child_alive():
            self.process.kill()
            self.process.waitForFinished(3000)
        self._handling_exit = False
        if self._stop_requested:
            self._set_status('stopped')
            return
        if retry:
            self.http_port, self.htsp_port = pick_port_pair(avoid=(self.http_port, self.htsp_port))
            self._start_attempt()
            return
        self._set_status('failed')
        self.failed.emit(reason)

    def _on_finished(self, _code, _status) -> None:
        if self._handling_exit:
            return
        self._poll.stop()
        if self._stop_requested:
            self._set_status('stopped')
            return
        if self._status == 'starting':
            self._set_status('failed')
            self.failed.emit('Built-in Tvheadend exited before it was ready.')
            return
        if self._status == 'running':
            self._set_status('failed')
            self.failed.emit('Built-in Tvheadend stopped.')

    def _child_alive(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def _set_status(self, status: str) -> None:
        if self._status == status:
            return
        self._status = status
        self.status_changed.emit(status)

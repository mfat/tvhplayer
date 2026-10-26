"""QProcess owner for the built-in Tvheadend."""

from __future__ import annotations

import logging
import threading
import time

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

try:
    from .core.builtin_server import (
        CONFIG_LOCKED_EXIT,
        MAX_BIND_ATTEMPTS,
        STARTUP_TIMEOUT_SECONDS,
        LineBuffer,
        apply_builtin_defaults,
        command_args,
        ensure_superuser,
        initial_ports,
        launch_command,
        pick_port_pair,
        serverinfo_ok,
        set_padding,
        set_recordings_dir,
        startup_result,
        stop_leftover_servers,
    )
    from .core.logs import SERVER_LOGGER
    from .core.proxy import child_env
except ImportError:
    from core.builtin_server import (
        CONFIG_LOCKED_EXIT,
        MAX_BIND_ATTEMPTS,
        STARTUP_TIMEOUT_SECONDS,
        LineBuffer,
        apply_builtin_defaults,
        command_args,
        ensure_superuser,
        initial_ports,
        launch_command,
        pick_port_pair,
        serverinfo_ok,
        set_padding,
        set_recordings_dir,
        startup_result,
        stop_leftover_servers,
    )
    from core.logs import SERVER_LOGGER
    from core.proxy import child_env


log = logging.getLogger('tvhplayer.builtin')
server_log = logging.getLogger(SERVER_LOGGER)


class BuiltinSupervisor(QObject):
    """Start, watch, and stop the shipped tvheadend child."""

    status_changed = pyqtSignal(str)
    ready = pyqtSignal(int, int)
    failed = pyqtSignal(str)
    # From the readiness check's thread: attempt, answered, defaults that failed.
    _checked = pyqtSignal(int, bool, object)

    def __init__(self, binary, config_dir, http_port=0, htsp_port=0, parent=None):
        super().__init__(parent)
        self.binary = binary
        self.config_dir = config_dir
        self.http_port = int(http_port or 0)
        self.htsp_port = int(htsp_port or 0)
        self.username = ''
        self.password = ''
        # The app's recordings folder, given to the server on every start; '' leaves its own.
        self.recordings_dir = ''
        # Minutes early and late for recordings, given on every start; None leaves the server's own.
        self.padding = None
        self.startup_timeout = STARTUP_TIMEOUT_SECONDS
        self._deadline = 0.0
        self._status = 'stopped'
        self._attempts = 0
        self._lines = LineBuffer()
        self._log = []
        self._partial_line = ''
        self._stop_requested = False
        self._handling_exit = False
        self._shut_down = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._poll_ready)
        self._check_attempt = 0
        self._checking = False
        self._checked.connect(self._on_checked)

    @property
    def status(self) -> str:
        return self._status

    def is_running(self) -> bool:
        return self._status == 'running' and self._child_alive()

    def log_text(self) -> str:
        return ''.join(self._log)

    def start(self) -> None:
        if self._shut_down or self._status in ('starting', 'running'):
            return
        if self.binary is None:
            self._set_status('failed')
            self.failed.emit('Built-in Tvheadend is not packaged in this build.')
            return
        try:
            stopped = stop_leftover_servers(self.config_dir)
        except RuntimeError as exc:
            self._fail(str(exc))
            return
        if stopped:
            log.info('Stopped a built-in server an earlier TVHplayer left running: pid %s', stopped)
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
        self._check_attempt += 1
        if self._child_alive():
            self._handling_exit = True
            self.process.terminate()
            if not self.process.waitForFinished(5000):
                self.process.kill()
                self.process.waitForFinished(2000)
            self._handling_exit = False
        self._set_status('stopped')

    def shut_down(self) -> None:
        """Stop for good. Work still finishing as the app quits cannot start it again."""
        self._shut_down = True
        self.stop()

    def _start_attempt(self) -> None:
        self._attempts += 1
        self._check_attempt += 1
        self._checking = False
        self._lines = LineBuffer()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        program, args = launch_command(command_args(self.binary, self.config_dir, self.http_port, self.htsp_port))
        self._set_status('starting')
        self._deadline = time.monotonic() + self.startup_timeout
        # VLC's http_proxy is hidden from this process. Tvheadend's own fetches keep it.
        environment = QProcessEnvironment()
        for key, value in child_env(None).items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.start(program, args)
        self._poll.start()

    def _on_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        if not data:
            return
        self._log.append(data)
        if len(self._log) > 400:
            self._log = self._log[-400:]
        self._partial_line += data
        *lines, self._partial_line = self._partial_line.split('\n')
        for line in lines:
            if line.strip():
                server_log.info(line.rstrip())
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
        if self._checking:
            return
        # A server still starting can take the whole timeout to answer; the
        # window must not wait for it.
        self._checking = True
        threading.Thread(
            target=self._check_ready,
            args=(self._check_attempt, self.http_port, self.username, self.password,
                  self.recordings_dir, self.padding),
            name='builtin-ready',
            daemon=True,
        ).start()

    def _check_ready(self, attempt, http_port, username, password, recordings_dir, padding) -> None:
        failed = []
        answered = serverinfo_ok(http_port, username=username, password=password)
        if answered:
            failed = apply_builtin_defaults(http_port, username, password, recordings_dir, padding)
        try:
            self._checked.emit(attempt, answered, failed)
        except RuntimeError:
            # The app closed while the server was being asked.
            pass

    def _on_checked(self, attempt, answered, failed) -> None:
        if attempt != self._check_attempt:
            return
        self._checking = False
        if self._status != 'starting' or not answered:
            return
        result = startup_result(self._child_alive(), self._lines.watch, True)
        if result == 'ready':
            if failed:
                log.warning('Could not apply built-in server defaults: %s', ', '.join(failed))
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
        self._fail(reason)

    def _fail(self, reason: str) -> None:
        log.warning('Built-in server failed: %s', reason)
        self._set_status('failed')
        self.failed.emit(reason)

    def _on_finished(self, code, _status) -> None:
        if self._handling_exit:
            return
        self._poll.stop()
        log.info('Built-in Tvheadend exited with code %s', code)
        if self._stop_requested:
            self._set_status('stopped')
            return
        if self._status == 'starting':
            if code == CONFIG_LOCKED_EXIT:
                self._fail('Another Tvheadend is using the built-in server settings, so the built-in server could not start.')
            else:
                self._fail('Built-in Tvheadend exited before it was ready.')
            return
        if self._status == 'running':
            self._fail('Built-in Tvheadend stopped.')

    def set_recordings_dir(self, folder: str) -> bool:
        """Use ``folder`` from the next start, and now when running. False when the server refused it."""
        self.recordings_dir = folder or ''
        if not self.recordings_dir or not self.is_running():
            return True
        return set_recordings_dir(self.http_port, self.recordings_dir, self.username, self.password)

    def set_padding(self, padding) -> bool:
        """Use ``(minutes early, minutes late)`` from the next start, and now when running."""
        self.padding = tuple(padding)
        if not self.is_running():
            return True
        return set_padding(self.http_port, self.padding, self.username, self.password)

    def _child_alive(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def _set_status(self, status: str) -> None:
        if self._status == status:
            return
        self._status = status
        self.status_changed.emit(status)

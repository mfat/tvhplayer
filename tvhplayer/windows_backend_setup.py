"""Consent-based WSL setup and progress UI. No Windows changes on construction."""
from __future__ import annotations

import json
import shutil

from PyQt6.QtCore import QProcess, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QProgressBar, QVBoxLayout


def setup_command(action):
    """Fixed arguments only: no filenames or error text enter the elevated script."""
    if action not in ('install', 'update', 'repair'):
        raise ValueError('Unknown WSL setup action')
    arguments = '--update' if action == 'update' else '--install --no-distribution'
    script = ("$ErrorActionPreference = 'Stop'; try { "
              "$p = Start-Process -FilePath ($env:WINDIR + '\\System32\\wsl.exe') "
              f"-ArgumentList '{arguments}' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; "
              "exit $p.ExitCode } catch { Write-Error $_; exit 1 }")
    return ['-NoProfile', '-NonInteractive', '-Command', script]


class WindowsBackendSetup(QDialog):
    def __init__(self, supervisor, parent=None):
        super().__init__(parent)
        self.supervisor = supervisor
        self.setWindowTitle('Set up the built-in server')
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        description = QLabel('The built-in server needs WSL 2.9.3 or newer and hardware virtualization. '
                             'Installing WSL may download files, ask for administrator permission, and require a Windows restart. '
                             'Your other servers remain available.')
        description.setWordWrap(True)
        layout.addWidget(description)
        issue = supervisor.setup_issue
        self.action = issue.action if issue else 'install'
        self.message = QLabel(str(issue) if issue else 'Check WSL and start the built-in server.')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        try:
            pending = json.loads(self.resume_file.read_text(encoding='utf-8'))
            if pending.get('schema') == 1:
                self.message.setText('A previous WSL setup needs to be checked. If Windows has restarted, '
                                     'choose “Check again and start server”.\n\n' + self.message.text())
        except (OSError, ValueError, AttributeError):
            pass
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.install = QPushButton('Update WSL…' if self.action == 'update' else 'Install / repair WSL…')
        self.install.clicked.connect(self._install)
        layout.addWidget(self.install)
        self.check = QPushButton('Check again and start server')
        self.check.clicked.connect(self._check)
        layout.addWidget(self.check)
        help_button = QPushButton('WSL setup help')
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://learn.microsoft.com/en-us/windows/wsl/install')))
        layout.addWidget(help_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.process = QProcess(self)
        self.process.finished.connect(self._installed)
        self.process.errorOccurred.connect(self._process_error)
        supervisor.status_changed.connect(self._status)
        supervisor.failed.connect(self._failed)
        supervisor.ready.connect(self._ready)
        self.finished.connect(self._detach)

    @property
    def resume_file(self):
        return self.supervisor.config_dir.parent / 'wslc-setup.json'

    def _save(self, stage):
        self.resume_file.parent.mkdir(parents=True, exist_ok=True)
        self.resume_file.write_text(json.dumps({'schema': 1, 'stage': stage, 'action': self.action}), encoding='utf-8')

    def _busy(self, busy):
        self.progress.setVisible(busy)
        self.install.setEnabled(not busy)
        self.check.setEnabled(not busy)

    def _install(self):
        # This slot is reached only after the explicit install/update button click.
        self._save('installing')
        self._busy(True)
        self.message.setText('Waiting for Windows setup. Accept the administrator prompt to continue. '
                             'If a restart is requested, restart Windows and reopen TVHplayer.')
        powershell = shutil.which('powershell.exe')
        if not powershell:
            self._failed('Windows PowerShell was not found. Use the WSL setup help link.')
            return
        self.process.start(powershell, setup_command(self.action))

    def _installed(self, code, status):
        self._busy(False)
        self._save('check_required' if code == 0 else 'restart_or_retry')
        if code in (0, 3010, 1641):
            self.message.setText('WSL setup finished. If Windows requests a restart, restart it and reopen TVHplayer. '
                                 'Otherwise choose “Check again and start server”.')
        else:
            self.message.setText('WSL setup was cancelled or could not finish. Check virtualization and Windows policy, '
                                 'then try again. Other servers are still available.')

    def _process_error(self, _error):
        self._failed('Could not launch Windows setup. You can install WSL using the setup help link.')

    def _check(self):
        self._busy(True)
        self.supervisor.start()

    def _status(self, status):
        if status in ('starting', 'installing'):
            self._busy(True)
            self.message.setText('Loading the offline server image…' if status == 'installing' else 'Starting the built-in server…')
        elif status in ('failed', 'stopped'):
            self._busy(False)

    def _failed(self, message):
        self._busy(False)
        self.message.setText(message)

    def _ready(self, *_ports):
        self.resume_file.unlink(missing_ok=True)
        self.accept()

    def reject(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.message.setText('Windows setup is still running. Finish or cancel its administrator prompt first.')
            return
        if self.supervisor.status in ('starting', 'installing'):
            self.supervisor.stop()
        super().reject()

    def _detach(self, _result):
        for signal, slot in ((self.supervisor.status_changed, self._status),
                             (self.supervisor.failed, self._failed), (self.supervisor.ready, self._ready)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

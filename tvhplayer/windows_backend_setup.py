"""Consent-based WSL setup and progress UI. No Windows changes on construction."""
from __future__ import annotations

import shutil

from PyQt6.QtCore import QProcess, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QProgressBar, QVBoxLayout

try:
    from .core.windows_prerequisites import pending_setup, save_setup
except ImportError:
    from core.windows_prerequisites import pending_setup, save_setup


def setup_command(action):
    """Fixed arguments only: no filenames or error text enter the elevated script."""
    if action not in ('install', 'update', 'repair'):
        raise ValueError('Unknown WSL setup action')
    arguments = '--update' if action == 'update' else '--install --no-distribution'
    executable = 'wsl.exe'
    if action == 'repair':
        executable = 'dism.exe'
        arguments = '/online /enable-feature /featurename:VirtualMachinePlatform /all /norestart'
    script = ("$ErrorActionPreference = 'Stop'; try { "
              f"$p = Start-Process -FilePath ($env:WINDIR + '\\System32\\{executable}') "
              f"-ArgumentList '{arguments}' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; "
              "exit $p.ExitCode } catch { Write-Error $_; exit 1 }")
    return ['-NoProfile', '-NonInteractive', '-Command', script]


class WindowsBackendSetup(QDialog):
    def __init__(self, supervisor, parent=None):
        super().__init__(parent)
        self.supervisor = supervisor
        self.setWindowTitle('Set up the built-in server')
        self.setMinimumWidth(480)
        self.setMaximumWidth(640)
        layout = QVBoxLayout(self)
        description = QLabel('The built-in server needs WSL 2.9.3 or newer and hardware virtualization. '
                             'Installing WSL may download files, ask for administrator permission, and require a Windows restart. '
                             'Your other servers remain available.')
        description.setWordWrap(True)
        layout.addWidget(description)
        issue = supervisor.setup_issue
        self.action = issue.action if issue else 'check'
        self.message = QLabel(str(issue) if issue else 'Check WSL and start the built-in server.')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        if getattr(supervisor, 'disabled', False):
            self.action = 'bios'
            self.message.setText('The built-in server and its automatic checks are disabled because '
                                 'hardware virtualization is disabled or unavailable. You can use another '
                                 'TVheadend server. After enabling virtualization in BIOS/UEFI, choose '
                                 'Enable and check again to retry.')
        elif pending_setup(supervisor.config_dir):
            self.message.setText('Resuming built-in server setup.\n\n' + self.message.text())
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.install = QPushButton('Update WSL…' if self.action == 'update' else 'Install / repair WSL…')
        self.install.clicked.connect(self._install)
        layout.addWidget(self.install)
        self.check = QPushButton('Check again and start server')
        if getattr(supervisor, 'disabled', False):
            self.check.setText('Enable and check again')
        self.check.clicked.connect(self._check)
        layout.addWidget(self.check)
        help_button = QPushButton('WSL setup help')
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://learn.microsoft.com/en-us/windows/wsl/troubleshooting')))
        layout.addWidget(help_button)
        virtualization_help = QPushButton('How to enable virtualization in BIOS / UEFI')
        virtualization_help.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            'https://support.microsoft.com/windows/c5578302-6e43-4b4b-a449-8ced115f58e1')))
        layout.addWidget(virtualization_help)
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
        self._update_action()
        if supervisor.status in ('starting', 'installing'):
            self._status(supervisor.status)

    @property
    def resume_file(self):
        return self.supervisor.config_dir.parent / 'wslc-setup.json'

    def _save(self, stage):
        save_setup(self.supervisor.config_dir, stage, self.action)

    def _busy(self, busy):
        self.progress.setVisible(busy)
        self.install.setEnabled(not busy and self.action in ('install', 'update', 'repair'))
        self.check.setEnabled(not busy)

    def _update_action(self):
        issue = self.supervisor.setup_issue
        self.action = issue.action if issue else self.action
        self.install.setText({'install': 'Install WSL…', 'update': 'Update WSL…',
                              'repair': 'Enable Virtual Machine Platform…', 'bios': 'Enable virtualization in BIOS / UEFI',
                              'reboot': 'Restart Windows to continue', 'diagnose': 'Check WSL troubleshooting',
                              'check': 'Check Windows prerequisites'}[self.action])
        self.install.setVisible(self.action in ('install', 'update', 'repair'))

    def _install(self):
        # This slot is reached only after the explicit install/update button click.
        if self.action not in ('install', 'update', 'repair'):
            return
        self._save('installing')
        self._busy(True)
        self.message.setText('Waiting for Windows setup. Accept the administrator prompt to continue. '
                             'TVHplayer will check whether Windows is ready after setup finishes.')
        powershell = shutil.which('powershell.exe')
        if not powershell:
            self._failed('Windows PowerShell was not found. Use the WSL setup help link.')
            return
        self.process.start(powershell, setup_command(self.action))

    def _installed(self, code, status):
        self._busy(False)
        self._save('check_required' if code == 0 else 'restart_or_retry')
        if status == QProcess.ExitStatus.NormalExit and code in (0, 3010, 1641):
            if self.action in ('install', 'repair') or code in (3010, 1641):
                self._save('restart_required')
                self.action = 'reboot'
                self.install.hide()
                self.message.setText('Restart Windows to finish setup, even if Windows did not show a reboot prompt. '
                                     'Then reopen TVHplayer; setup will resume automatically. Save your work before restarting. '
                                     'TVHplayer will not restart your computer automatically.')
            else:
                self._check()
        else:
            self.message.setText('WSL setup was cancelled or could not finish. Check virtualization and Windows policy, '
                                 'then try again. Other servers are still available.')

    def _process_error(self, _error):
        self._failed('Could not launch Windows setup. You can install WSL using the setup help link.')

    def _check(self):
        self._busy(True)
        if getattr(self.supervisor, 'disabled', False):
            self.supervisor.enable_and_check()
        else:
            self.supervisor.start()

    def _status(self, status):
        if status in ('starting', 'installing'):
            self._busy(True)
            self.message.setText('Preparing the built-in server…' if status == 'installing' else 'Starting the built-in server…')
        elif status in ('failed', 'stopped'):
            self._busy(False)

    def _failed(self, message):
        self._update_action()
        self._busy(False)
        self.check.setText('Enable and check again' if getattr(self.supervisor, 'disabled', False)
                           else 'Check again and start server')
        self.message.setText(message)

    def _ready(self, *_ports):
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

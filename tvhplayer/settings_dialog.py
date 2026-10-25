"""The Settings window. For now it holds what to do with imported channels that do not work."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

try:
    from .a11y import announce_label, describe
except ImportError:
    from a11y import announce_label, describe

HIDE_HELP = (
    'After an import or refresh, the server tests each channel in the background. '
    'Channels that fail are hidden and come back once a later test finds them working.'
)
CHECK_HELP = 'Test every imported channel now and hide the ones that do not work.'


class SettingsDialog(QDialog):
    """``host`` is the main window: it keeps the setting and runs the checks."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._jobs = []
        self.setWindowTitle('Settings')
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setAccessibleName('Settings')
        layout = QVBoxLayout(self)

        group = QGroupBox('Imported channels')
        group_layout = QVBoxLayout(group)
        self.hide_check = QCheckBox('&Hide channels that do not work')
        self.hide_check.setChecked(host.hides_dead_channels())
        describe(self.hide_check, description=HIDE_HELP)
        group_layout.addWidget(self.hide_check)
        hide_help = QLabel(HIDE_HELP)
        hide_help.setWordWrap(True)
        hide_help.setContentsMargins(24, 0, 0, 0)
        group_layout.addWidget(hide_help)

        row = QHBoxLayout()
        self.check_btn = QPushButton('&Check Channels Now')
        describe(self.check_btn, 'Check Channels Now', CHECK_HELP)
        self.check_btn.setToolTip(CHECK_HELP)
        row.addWidget(self.check_btn)
        row.addStretch(1)
        group_layout.addLayout(row)
        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        group_layout.addWidget(self.status_label)
        layout.addWidget(group)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.hide_check.toggled.connect(self._toggled)
        self.check_btn.clicked.connect(self._check)
        self._sync()

    def _toggled(self, on):
        self._host.set_hides_dead_channels(on)
        if on:
            announce_label(self.status_label, 'Channels that do not work are hidden from the next import or refresh on.')
        else:
            announce_label(self.status_label, 'Hidden channels are shown again. Imports no longer test channels.')

    def _check(self):
        self._jobs = self._host.check_playlist_channels()
        if not self._jobs:
            announce_label(self.status_label, 'There are no imported playlists to check.')
            return
        for job in self._jobs:
            job.finished.connect(lambda *_args: self._sync())
            job.failed.connect(lambda *_args: self._sync())
        count = len(self._jobs)
        playlists = '1 playlist' if count == 1 else f'{count} playlists'
        announce_label(
            self.status_label,
            f'Checking {playlists} in the background. Channels that do not work are hidden as they are found; '
            'the status bar says when it is done.',
        )
        self._sync()

    def _sync(self):
        running = any(job.is_running() for job in self._host.playlist_checks())
        self.check_btn.setEnabled(not running)
        if running:
            self.check_btn.setToolTip('Channels are being checked.')
        else:
            self.check_btn.setToolTip(CHECK_HELP)

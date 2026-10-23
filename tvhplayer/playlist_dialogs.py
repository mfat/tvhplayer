"""Import an M3U playlist into a Tvheadend server.

The user picks a playlist and a server. Every technical choice is made by
``core.playlist`` and ``core.playlist_sync``; this module runs them off the
UI thread and reports the outcome in plain words.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

try:
    from .a11y import announce_label, buddy_label, describe
    from .core.playlist import load_playlist, plan_channels, playlist_commands, playlist_name
    from .core.playlist_sync import (
        PlaylistSource,
        error_message,
        ffmpeg_for_server,
        find_source,
        result_message,
        server_key,
        sync_playlist,
        unique_name,
    )
    from .core.tvh_admin import TvhAdmin
except ImportError:
    from a11y import announce_label, buddy_label, describe
    from core.playlist import load_playlist, plan_channels, playlist_commands, playlist_name
    from core.playlist_sync import (
        PlaylistSource,
        error_message,
        ffmpeg_for_server,
        find_source,
        result_message,
        server_key,
        sync_playlist,
        unique_name,
    )
    from core.tvh_admin import TvhAdmin


class _Task(QThread):
    """Run ``fn(task)`` on a worker thread."""

    progress = pyqtSignal(int, int)
    checkpoint = pyqtSignal(object)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.succeeded.emit(self._fn(self))
        except Exception as exc:  # reported to the user by the job
            self.failed.emit(exc)


class PlaylistJob(QObject):
    """Read a playlist and write its channels to one server.

    ``host`` is the main window. It starts the built-in server when needed
    and saves the playlist source. ``ask_commands(count, server_name)``
    decides whether programs named in the playlist may run; without it the
    saved choice is used.
    """

    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self, host, source, server, first_import, ask_commands=None, parent=None):
        super().__init__(parent)
        self._host = host
        self.source = source
        self.server = server
        self._first_import = first_import
        self._ask_commands = ask_commands
        self._task = None
        self._playlist = None
        self._busy = False
        self._cancelled = False

    def start(self):
        self._busy = True
        self._host.ensure_server_ready(self.server, self._server_ready, self._stop_with)

    def cancel(self):
        self._cancelled = True

    def is_running(self):
        return self._busy

    def _stop_with(self, message):
        self._busy = False
        self.failed.emit(message)

    def _server_ready(self, server):
        self.server = server
        if self._cancelled:
            self._stop_with('Import stopped.')
            return
        self.status.emit('Reading the playlist…')
        location = self.source.location
        self._run(lambda _task: load_playlist(location), self._loaded)

    def _loaded(self, playlist):
        self._playlist = playlist
        if self._cancelled:
            self._stop_with('Import stopped.')
            return
        commands = playlist_commands(playlist)
        if commands and not self.source.allow_commands and self._ask_commands is not None:
            self.source.allow_commands = bool(self._ask_commands(len(commands), self.server.get('name', '')))
        self.status.emit('Adding channels…')
        self._run(self._sync, self._synced)

    def _sync(self, task):
        source = self.source
        ffmpeg = ffmpeg_for_server(self.server)
        plans, skipped = plan_channels(self._playlist, ffmpeg, source.name, source.allow_commands)
        with TvhAdmin(self.server) as admin:
            return sync_playlist(
                admin,
                source,
                plans,
                skipped,
                progress=task.progress.emit,
                cancelled=lambda: self._cancelled,
                checkpoint=lambda: task.checkpoint.emit(source.to_dict()),
            )

    def _synced(self, result):
        self._busy = False
        self._host.store_playlist_source(self.source.to_dict())
        self.finished.emit(result_message(self.source.name, result, self._first_import), result.skipped)

    def _run(self, fn, on_success):
        task = _Task(fn, self)
        task.progress.connect(self.progress.emit)
        task.checkpoint.connect(self._host.store_playlist_source)
        task.succeeded.connect(on_success)
        task.failed.connect(self._failed)
        self._task = task
        task.start()

    def _failed(self, exc):
        self._stop_with(error_message(exc, self.server.get('name', 'the server')))


def ask_to_run_commands(parent, count, server_name):
    programs = '1 program' if count == 1 else f'{count} programs'
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle('Run programs from this playlist?')
    box.setText(f'This playlist wants to run {programs} on {server_name}.')
    box.setInformativeText('Only allow this if you trust where the playlist came from.')
    allow = box.addButton('Allow', QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton('Skip Them', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(skip)
    box.exec()
    return box.clickedButton() is allow


def show_skipped(parent, skipped):
    lines = '\n'.join(f'{entry.name or "(no name)"}: {entry.reason}' for entry in skipped)
    box = QMessageBox(parent)
    box.setWindowTitle('Entries not added')
    box.setText('These playlist entries could not be added.')
    box.setDetailedText(lines)
    box.exec()


class ImportPlaylistDialog(QDialog):
    """One step: choose a playlist and a server, then Import."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._job = None
        self._skipped = []
        self._done_server = None
        self.setWindowTitle('Import Playlist')
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setAccessibleName('Import Playlist')
        self.setAccessibleDescription('Add TV channels from an M3U playlist to a server.')
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        intro = QLabel('Add TV channels from a playlist. Paste its web address or choose a file.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText('https://example.com/channels.m3u')
        describe(self.location_input, description='Web address of an M3U playlist, or a playlist file.')
        browse = QPushButton('&Browse…')
        browse.clicked.connect(self._browse)
        describe(browse, 'Browse', 'Choose a playlist file on this computer.')
        row = QHBoxLayout()
        row.addWidget(self.location_input, 1)
        row.addWidget(browse)
        layout.addWidget(buddy_label('&Playlist:', self.location_input))
        layout.addLayout(row)

        self._targets = self._host.import_targets()
        self.server_combo = QComboBox()
        for server in self._targets:
            self.server_combo.addItem(server.get('name', ''))
        describe(self.server_combo, description='The server that receives the channels.')
        server_label = buddy_label('Add channels &to:', self.server_combo)
        layout.addWidget(server_label)
        layout.addWidget(self.server_combo)
        if len(self._targets) < 2:
            server_label.hide()
            self.server_combo.hide()

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        describe(self.progress_bar, 'Import progress')
        layout.addWidget(self.progress_bar)

        self.buttons = QDialogButtonBox()
        self.import_btn = self.buttons.addButton('&Import', QDialogButtonBox.ButtonRole.AcceptRole)
        self.details_btn = self.buttons.addButton('&Details', QDialogButtonBox.ButtonRole.HelpRole)
        self.show_btn = self.buttons.addButton('&Show Channels', QDialogButtonBox.ButtonRole.ActionRole)
        self.close_btn = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.details_btn.hide()
        self.show_btn.hide()
        self.import_btn.setDefault(True)
        self.import_btn.clicked.connect(self._start)
        self.details_btn.clicked.connect(lambda: show_skipped(self, self._skipped))
        self.show_btn.clicked.connect(self._show_channels)
        self.close_btn.clicked.connect(self.reject)
        layout.addWidget(self.buttons)

    def _browse(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, 'Choose a Playlist', '', 'Playlists (*.m3u *.m3u8);;All files (*)'
        )
        if path:
            self.location_input.setText(path)

    def _set_status(self, message):
        announce_label(self.status_label, message)

    def _set_running(self, running):
        self.location_input.setEnabled(not running)
        self.server_combo.setEnabled(not running)
        self.import_btn.setEnabled(not running)
        self.close_btn.setText('Cancel' if running else 'Close')
        self.progress_bar.setVisible(running)

    def _start(self):
        location = self.location_input.text().strip()
        if not location:
            self._set_status('Enter a playlist address or choose a file.')
            self.location_input.setFocus()
            return
        if not self._targets:
            self._set_status('Add a server first, then import the playlist.')
            return
        server = self._targets[max(self.server_combo.currentIndex(), 0)]
        key = server_key(server)
        sources = self._host.playlist_sources()
        existing = find_source(sources, location, key)
        if existing is not None:
            source = PlaylistSource.from_dict(existing.to_dict())
        else:
            source = PlaylistSource(unique_name(sources, playlist_name(location), key), location, key)
        self.details_btn.hide()
        self.show_btn.hide()
        self.progress_bar.setRange(0, 0)
        self._set_running(True)
        self._job = PlaylistJob(
            self._host,
            source,
            server,
            existing is None,
            ask_commands=lambda count, name: ask_to_run_commands(self, count, name),
            parent=self,
        )
        self._job.status.connect(self._set_status)
        self._job.progress.connect(self._progress)
        self._job.finished.connect(self._finished)
        self._job.failed.connect(self._failed)
        self._job.start()

    def _progress(self, done, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        self.status_label.setText(f'Adding channels… {done} of {total}')

    def _finished(self, message, skipped):
        self._set_running(False)
        self._set_status(message)
        self._skipped = list(skipped)
        self.details_btn.setVisible(bool(self._skipped))
        self._done_server = self._job.server
        self.show_btn.setVisible(not self._host.is_current_server(self._done_server))
        self._host.playlist_imported(self._done_server)
        self.close_btn.setFocus()

    def _failed(self, message):
        self._set_running(False)
        self._set_status(message)

    def _show_channels(self):
        self._host.show_server(self._done_server)
        self.accept()

    def reject(self):
        if self._job is not None and self._job.is_running():
            self._job.cancel()
            self._set_status('Stopping…')
            return
        super().reject()

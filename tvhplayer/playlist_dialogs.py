"""Import an M3U playlist into a Tvheadend server.

The user picks a playlist and a server. Every technical choice is made by
``core.playlist`` and ``core.playlist_sync``; this module runs them off the
UI thread and reports the outcome in plain words.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
        remove_playlist,
        result_message,
        server_key,
        sync_playlist,
        unique_name,
        wait_for_checks,
    )
    from .core.errors import PlaylistError, TvhError
    from .core.tvh_admin import TvhAdmin
    from .core.xmltv import load_guide
except ImportError:
    from a11y import announce_label, buddy_label, describe
    from core.playlist import load_playlist, plan_channels, playlist_commands, playlist_name
    from core.playlist_sync import (
        PlaylistSource,
        error_message,
        ffmpeg_for_server,
        find_source,
        remove_playlist,
        result_message,
        server_key,
        sync_playlist,
        unique_name,
        wait_for_checks,
    )
    from core.errors import PlaylistError, TvhError
    from core.tvh_admin import TvhAdmin
    from core.xmltv import load_guide


class _Task(QThread):
    """Run ``fn(task)`` on a worker thread."""

    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
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


BUSY = 'This playlist is being updated. Try again in a moment.'


class PlaylistJob(QObject):
    """Read a playlist and write its channels to one server, or remove them.

    ``host`` is the main window. It starts the built-in server when needed,
    saves the playlist source, and makes sure one playlist is updated by one
    job at a time. ``ask_commands(count, server_name)`` decides whether
    programs named in the playlist may run; without it the saved choice is used.
    """

    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self, host, source, server, first_import=False, ask_commands=None, remove=False, parent=None):
        super().__init__(parent)
        self._host = host
        self.source = source
        self.server = server
        self._first_import = first_import
        self._ask_commands = ask_commands
        self._remove = remove
        self._task = None
        self._playlist = None
        self._busy = False
        self._cancelled = False

    def start(self):
        if not self._host.claim_playlist(self.source):
            self.failed.emit(BUSY)
            return
        self._busy = True
        self._host.ensure_server_ready(self.server, self._server_ready, self._stop_with)

    def cancel(self):
        self._cancelled = True

    def is_running(self):
        return self._busy

    def _release(self):
        self._busy = False
        self._host.release_playlist(self.source)

    def _stop_with(self, message):
        self._release()
        self.failed.emit(message)

    def _server_ready(self, server):
        self.server = server
        if self._cancelled:
            self._stop_with('Import stopped.')
            return
        if self._remove:
            self.status.emit('Removing channels…')
            self._run(self._delete, self._deleted)
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
            result = sync_playlist(
                admin,
                source,
                plans,
                skipped,
                progress=task.progress.emit,
                cancelled=lambda: self._cancelled,
                checkpoint=lambda: task.checkpoint.emit(source.to_dict()),
            )
            if not result.cancelled:
                task.status.emit('Checking channels…')
                wait_for_checks(
                    admin, source, result, progress=task.progress.emit, cancelled=lambda: self._cancelled
                )
            if self._playlist.guide_url and not result.cancelled:
                task.status.emit('Loading the program guide…')
                try:
                    load_guide(admin, self.server, self._playlist.guide_url, result.added > 0)
                except (PlaylistError, TvhError):
                    # The channels are in; only the guide is missing.
                    result.guide_failed = True
            return result

    def _synced(self, result):
        self._host.store_playlist_source(self.source.to_dict())
        self._release()
        self.finished.emit(result_message(self.source.name, result, self._first_import), result.skipped)

    def _delete(self, _task):
        with TvhAdmin(self.server) as admin:
            admin.check_admin()
            remove_playlist(admin, self.source)

    def _deleted(self, _result):
        self._host.forget_playlist_source(self.source.to_dict())
        self._release()
        self.finished.emit(f'Removed the channels from {self.source.name}.', [])

    def _run(self, fn, on_success):
        task = _Task(fn, self)
        task.progress.connect(self.progress.emit)
        task.status.connect(self.status.emit)
        task.checkpoint.connect(self._host.store_playlist_source)
        task.succeeded.connect(on_success)
        task.failed.connect(self._failed)
        self._task = task
        task.start()

    def _failed(self, exc):
        self._stop_with(error_message(exc, self.server.get('name', 'the server'), self._remove))


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
    box.setWindowTitle('Channels not added')
    box.setText('These playlist entries could not be added or are not working right now.')
    box.setDetailedText(lines)
    box.exec()


class ImportPlaylistDialog(QDialog):
    """One step: choose a playlist and a server, then Import."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._job = None
        self._skipped = []
        self._step_text = ''
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
            first_import=existing is None,
            ask_commands=lambda count, name: ask_to_run_commands(self, count, name),
            parent=self,
        )
        self._job.status.connect(self._step)
        self._job.progress.connect(self._progress)
        self._job.finished.connect(self._finished)
        self._job.failed.connect(self._failed)
        self._job.start()

    def _step(self, message):
        self._step_text = message
        self.progress_bar.setRange(0, 0)
        self._set_status(message)

    def _progress(self, done, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        self.status_label.setText(f'{self._step_text} {done} of {total}')

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


class PlaylistsDialog(QDialog):
    """Imported playlists, with Refresh and Remove."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._job = None
        self.setWindowTitle('Playlists')
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setAccessibleName('Playlists')
        self.setAccessibleDescription('Playlists whose channels were imported. Refresh or remove them.')
        layout = QVBoxLayout(self)

        self.playlist_list = QListWidget()
        describe(self.playlist_list, 'Imported playlists')
        layout.addWidget(buddy_label('&Imported playlists:', self.playlist_list))
        layout.addWidget(self.playlist_list)
        self.empty_label = QLabel('No playlists yet. Use File → Import Playlist to add channels from one.')
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        describe(self.progress_bar, 'Progress')
        layout.addWidget(self.progress_bar)

        self.buttons = QDialogButtonBox()
        self.refresh_btn = self.buttons.addButton('&Refresh', QDialogButtonBox.ButtonRole.ActionRole)
        self.remove_btn = self.buttons.addButton('Re&move', QDialogButtonBox.ButtonRole.DestructiveRole)
        self.close_btn = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        describe(self.refresh_btn, 'Refresh', 'Read the playlist again and update its channels.')
        describe(self.remove_btn, 'Remove', 'Remove the playlist and its channels from the server.')
        self.refresh_btn.clicked.connect(lambda: self._run(remove=False))
        self.remove_btn.clicked.connect(self._confirm_remove)
        self.close_btn.clicked.connect(self.reject)
        self.playlist_list.currentRowChanged.connect(lambda _row: self._sync_buttons())
        layout.addWidget(self.buttons)
        self._load()

    def _load(self):
        self.playlist_list.clear()
        for source in self._host.playlist_sources():
            server = self._host.server_for_playlist(source)
            where = server.get('name', '') if server else 'a server that was removed'
            item = QListWidgetItem(f'{source.name} — {where}')
            item.setData(Qt.ItemDataRole.UserRole, source.to_dict())
            self.playlist_list.addItem(item)
        empty = self.playlist_list.count() == 0
        self.playlist_list.setVisible(not empty)
        self.empty_label.setVisible(empty)
        if not empty:
            self.playlist_list.setCurrentRow(0)
        self._sync_buttons()

    def _selected(self):
        item = self.playlist_list.currentItem()
        return PlaylistSource.from_dict(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _sync_buttons(self):
        source = self._selected()
        running = self._job is not None and self._job.is_running()
        has_server = source is not None and self._host.server_for_playlist(source) is not None
        self.refresh_btn.setEnabled(not running and has_server)
        self.remove_btn.setEnabled(not running and source is not None)
        self.playlist_list.setEnabled(not running)

    def _confirm_remove(self):
        source = self._selected()
        if source is None:
            return
        if self._host.server_for_playlist(source) is None:
            self._host.forget_playlist_source(source.to_dict())
            self._load()
            return
        answer = QMessageBox.question(
            self,
            'Remove Playlist',
            f'Remove the channels from {source.name}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run(remove=True)

    def _run(self, remove):
        source = self._selected()
        server = self._host.server_for_playlist(source) if source is not None else None
        if server is None:
            return
        self._job = PlaylistJob(self._host, source, server, remove=remove, parent=self)
        self._job.status.connect(lambda message: announce_label(self.status_label, message))
        self._job.progress.connect(self._progress)
        self._job.finished.connect(self._finished)
        self._job.failed.connect(self._failed)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self._job.start()
        self._sync_buttons()

    def _progress(self, done, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)

    def _finished(self, message, _skipped):
        self.progress_bar.hide()
        announce_label(self.status_label, message)
        self._host.playlist_imported(self._job.server)
        self._load()

    def _failed(self, message):
        self.progress_bar.hide()
        announce_label(self.status_label, message)
        self._sync_buttons()

    def reject(self):
        if self._job is not None and self._job.is_running():
            self._job.cancel()
            announce_label(self.status_label, 'Stopping…')
            return
        super().reject()

"""Import an M3U playlist into a Tvheadend server.

The user picks a playlist and a server. Every technical choice is made by
``core.playlist`` and ``core.playlist_sync``; this module runs them off the
UI thread and reports the outcome in plain words.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from .a11y import announce_label, buddy_label, describe, set_item_access
    from .core.playlist import load_playlist, plan_channels, playlist_commands, playlist_name, xtream_connections
    from .core.playlist_sync import (
        NETWORK_GONE,
        PlaylistSource,
        SyncResult,
        check_message,
        error_message,
        ffmpeg_for_server,
        find_source,
        remove_playlist,
        result_message,
        server_key,
        show_all_channels,
        sync_playlist,
        unique_name,
        wait_for_checks,
    )
    from .core.errors import PlaylistError, TvhError
    from .core.tvh_admin import TvhAdmin
    from .core.xmltv import is_local_server, load_guide
except ImportError:
    from a11y import announce_label, buddy_label, describe, set_item_access
    from core.playlist import load_playlist, plan_channels, playlist_commands, playlist_name, xtream_connections
    from core.playlist_sync import (
        NETWORK_GONE,
        PlaylistSource,
        SyncResult,
        check_message,
        error_message,
        ffmpeg_for_server,
        find_source,
        remove_playlist,
        result_message,
        server_key,
        show_all_channels,
        sync_playlist,
        unique_name,
        wait_for_checks,
    )
    from core.errors import PlaylistError, TvhError
    from core.tvh_admin import TvhAdmin
    from core.xmltv import is_local_server, load_guide


class _Task(QThread):
    """Run ``fn(task)`` on a worker thread."""

    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    checkpoint = pyqtSignal(object)
    channels_changed = pyqtSignal()
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
BUSY_POLL_MS = 1000
REMOVED_SERVERS = 'Removed servers'


def _playlists(count):
    return '1 playlist' if count == 1 else f'{count} playlists'


class PlaylistJob(QObject):
    """Read a playlist and write its channels to one server, or remove them.

    ``host`` is the main window. It starts the built-in server when needed,
    saves the playlist source, reloads its channel list while channels change,
    and makes sure one playlist is updated by one job at a time.
    ``ask_commands(count, server_name)`` decides whether programs named in the
    playlist may run; without it the saved choice is used.

    ``action`` is SYNC (import or refresh), REMOVE, CHECK (test every
    stream now and hide those that fail), or SHOW (show every channel again).
    A sync tests the streams only when the host hides channels that fail.

    ``checking`` is emitted once the channels and guide are written and only
    the server's stream test is left, which can take hours.
    """

    SYNC, REMOVE, CHECK, SHOW = 'add', 'remove', 'check', 'show'

    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    checking = pyqtSignal()
    finished = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self, host, source, server, first_import=False, ask_commands=None, action=SYNC, parent=None):
        super().__init__(parent)
        self._host = host
        self.source = source
        self.server = server
        self._first_import = first_import
        self._ask_commands = ask_commands
        self.action = action
        self._hide_failed = host.hides_dead_channels()
        self._task = None
        self._playlist = None
        self.result = None
        self._busy = False
        self._checking = False
        self._cancelled = False

    def start(self):
        if not self._host.claim_playlist(self.source):
            self.failed.emit(BUSY)
            return
        self._busy = True
        self._host.ensure_server_ready(self.server, self._server_ready, self._stop_with)

    def cancel(self):
        self._cancelled = True

    def shutdown(self, timeout_ms):
        """Cancel and wait for the worker, so Qt never destroys it while it runs."""
        self._cancelled = True
        task = self._task
        if task is not None and task.isRunning():
            return task.wait(timeout_ms)
        return True

    def is_running(self):
        return self._busy

    def is_writing(self):
        """Busy with more than the server's stream test."""
        return self._busy and not self._checking

    def is_checking(self):
        """Only the server's stream test is left, which can go on without a window."""
        return self._busy and self._checking

    def detach(self):
        """Drop every window's connection, for the host to take the job over."""
        for signal in (self.status, self.progress, self.checking, self.finished, self.failed):
            try:
                signal.disconnect()
            except TypeError:
                pass

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
        if self.action == self.REMOVE:
            self.status.emit('Removing channels…')
            self._run(self._delete, self._deleted)
            return
        if self.action == self.CHECK:
            self.status.emit('Starting the check…')
            self._run(self._start_check, self._synced)
            return
        if self.action == self.SHOW:
            self.status.emit('Showing channels…')
            self._run(self._show_all, self._shown)
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
        # When the account cannot be asked, the limit found last time stays.
        connections = xtream_connections(source.location)
        if connections is not None:
            source.max_streams = connections
        with TvhAdmin(self.server) as admin:
            result = sync_playlist(
                admin,
                source,
                plans,
                skipped,
                progress=task.progress.emit,
                cancelled=lambda: self._cancelled,
                checkpoint=lambda: task.checkpoint.emit(source.to_dict()),
                check=self._hide_failed,
            )
            result.films = self._playlist.films
            # Removed duplicates and newly hidden channels are already gone from the server.
            task.channels_changed.emit()
            # A server on this computer takes the guide with the other guide sources.
            if self._playlist.guide_url and not result.cancelled and not is_local_server(self.server):
                task.status.emit('Loading the program guide…')
                try:
                    load_guide(admin, self.server, self._playlist.guide_url, result.added > 0)
                except (PlaylistError, TvhError):
                    # The channels are in; only the guide is missing.
                    result.guide_failed = True
            return result

    def _synced(self, result):
        self.result = result
        self._host.store_playlist_source(self.source.to_dict())
        if self.action == self.SYNC and not result.cancelled:
            guide_url = self._playlist.guide_url if self._playlist is not None else ''
            self._host.after_playlist_sync(self.server, self.source, guide_url, result)
        if result.cancelled or not (self._hide_failed or self.action == self.CHECK):
            self._checked(result)
            return
        self._checking = True
        self.checking.emit()
        self.status.emit('Checking channels…')
        self._run(lambda task: self._check(task, result), self._checked)

    def _check(self, task, result):
        with TvhAdmin(self.server) as admin:
            wait_for_checks(
                admin,
                self.source,
                result,
                progress=task.progress.emit,
                cancelled=lambda: self._cancelled,
                changed=task.channels_changed.emit,
            )
        return result

    def _checked(self, result):
        self._release()
        if self.action == self.CHECK:
            message = check_message(self.source.name, result)
        else:
            message = result_message(self.source.name, result, self._first_import)
        self.finished.emit(message, result.skipped)

    def _start_check(self, _task):
        with TvhAdmin(self.server) as admin:
            admin.check_admin()
            if not admin.network_exists(self.source.network_uuid):
                raise PlaylistError(NETWORK_GONE)
            admin.scan_network(self.source.network_uuid)
        return SyncResult()

    def _show_all(self, task):
        with TvhAdmin(self.server) as admin:
            admin.check_admin()
            shown = show_all_channels(admin, self.source)
        if shown:
            task.channels_changed.emit()
        return shown

    def _shown(self, _shown):
        self._release()
        self.finished.emit(f'Every channel from {self.source.name} is shown.', [])

    def _delete(self, _task):
        with TvhAdmin(self.server) as admin:
            admin.check_admin()
            remove_playlist(admin, self.source)

    def _deleted(self, _result):
        self._host.forget_playlist_source(self.source.to_dict())
        self._release()
        self.finished.emit(f'Removed the channels from {self.source.name}.', [])

    def _run(self, fn, on_success):
        if self._cancelled:
            self._stop_with('Import stopped.')
            return
        task = _Task(fn, self)
        task.progress.connect(self.progress.emit)
        task.status.connect(self.status.emit)
        task.checkpoint.connect(self._host.store_playlist_source)
        task.channels_changed.connect(lambda: self._host.playlist_channels_changed(self.server))
        task.succeeded.connect(on_success)
        task.failed.connect(self._failed)
        self._task = task
        task.start()

    def _failed(self, exc):
        self._stop_with(error_message(exc, self.server.get('name', 'the server'), self.action))


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


CHECK_HINT = 'The channels are in the list. Those that do not work are hidden as the check finds them. You can close this window; checking goes on.'


class ImportPlaylistDialog(QDialog):
    """One step: choose a playlist and a server, then Import."""

    def __init__(self, host, parent=None, server=None):
        super().__init__(parent)
        self._host = host
        self._server = server
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
        if self._server is not None:
            keys = [server_key(server) for server in self._targets]
            if server_key(self._server) in keys:
                self.server_combo.setCurrentIndex(keys.index(server_key(self._server)))
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
        self.hint_label = QLabel(CHECK_HINT)
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        layout.addWidget(self.hint_label)

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
        self.hint_label.hide()

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
        self._job.checking.connect(self._checking)
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

    def _checking(self):
        self.close_btn.setText('Close')
        self.hint_label.show()

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
        if self._job is not None and self._job.is_checking():
            self._job.detach()
            self._host.keep_playlist_job(self._job)
            self._job = None
        elif self._job is not None and self._job.is_running():
            self._job.cancel()
            self._set_status('Stopping…')
            return
        super().reject()


class PlaylistsDialog(QDialog):
    """Servers on the left, the selected one's playlists on the right."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self._job = None
        self._stopping = None
        # One entry per server row: the server, or None for playlists whose server was removed.
        self._servers = []
        self.setWindowTitle('Playlists')
        self.setModal(True)
        self.setMinimumSize(720, 420)
        self.setAccessibleName('Playlists')
        self.setAccessibleDescription(
            'Servers on the left, the playlists imported to the selected server on the right. '
            'Refresh or remove them.'
        )
        layout = QVBoxLayout(self)
        columns = QHBoxLayout()
        columns.setSpacing(12)
        layout.addLayout(columns, 1)

        left = QWidget()
        left.setFixedWidth(250)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.server_list = QListWidget()
        describe(self.server_list, 'Servers', 'Choose a server to see the playlists imported to it.')
        left_layout.addWidget(buddy_label('&Servers:', self.server_list))
        left_layout.addWidget(self.server_list, 1)
        columns.addWidget(left)

        self.detail_panel = QFrame()
        self.detail_panel.setFrameShape(QFrame.Shape.StyledPanel)
        detail = QVBoxLayout(self.detail_panel)
        detail.setContentsMargins(16, 14, 16, 14)
        detail.setSpacing(10)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.title_label = QLabel()
        title_font = QFont(self.title_label.font())
        title_font.setBold(True)
        if title_font.pointSizeF() > 0:
            title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self.title_label.setFont(title_font)
        heading.addWidget(self.title_label)
        self.count_label = QLabel()
        self.count_label.setWordWrap(True)
        heading.addWidget(self.count_label)
        header.addLayout(heading, 1)
        self.refresh_btn = QPushButton('&Refresh')
        self.remove_btn = QPushButton('Re&move')
        describe(self.refresh_btn, 'Refresh', 'Read the playlist again and update its channels.')
        describe(self.remove_btn, 'Remove', 'Remove the playlist and its channels from the server.')
        self.refresh_btn.clicked.connect(lambda: self._run(remove=False))
        self.remove_btn.clicked.connect(self._confirm_remove)
        header.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.remove_btn, 0, Qt.AlignmentFlag.AlignTop)
        detail.addLayout(header)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        detail.addWidget(separator)

        self.playlist_list = QListWidget()
        describe(self.playlist_list, 'Playlists', 'Playlists imported to the selected server.')
        self.playlist_label = buddy_label('&Playlists:', self.playlist_list)
        detail.addWidget(self.playlist_label)
        detail.addWidget(self.playlist_list, 1)
        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        detail.addWidget(self.empty_label)
        detail.addStretch(0)

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        detail.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        describe(self.progress_bar, 'Progress')
        detail.addWidget(self.progress_bar)
        self.hint_label = QLabel(CHECK_HINT)
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        detail.addWidget(self.hint_label)

        footer = QHBoxLayout()
        self.import_btn = QPushButton('+ &Import Playlist…')
        describe(self.import_btn, 'Import playlist', 'Add channels from a playlist to the selected server.')
        self.import_btn.clicked.connect(self._import)
        footer.addWidget(self.import_btn)
        footer.addStretch(1)
        detail.addLayout(footer)
        columns.addWidget(self.detail_panel, 1)

        self.buttons = QDialogButtonBox()
        self.close_btn = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.close_btn.clicked.connect(self.reject)
        layout.addWidget(self.buttons)

        self.server_list.currentRowChanged.connect(lambda _row: self._show_server())
        self.playlist_list.currentRowChanged.connect(lambda _row: self._sync_buttons())
        self._load()
        # Updates started elsewhere (at startup, from Settings, or by an import
        # window that was closed) end on their own; follow them.
        self._busy_timer = QTimer(self)
        self._busy_timer.timeout.connect(self._follow_busy)
        self._busy_timer.start(BUSY_POLL_MS)

    def _load(self):
        """List the servers, keeping the selected one."""
        previous = self._selected_server_key()
        sources = self._host.playlist_sources()
        self._servers = list(self._host.import_targets())
        if any(self._host.server_for_playlist(source) is None for source in sources):
            self._servers.append(None)
        self.server_list.blockSignals(True)
        self.server_list.clear()
        row = -1
        for index, server in enumerate(self._servers):
            count = len(self._sources_for(server, sources))
            name = server.get('name', '') if server else REMOVED_SERVERS
            item = QListWidgetItem(f'{name} ({count})')
            set_item_access(item, f'{name}, {_playlists(count)}')
            self.server_list.addItem(item)
            key = self._key(server)
            if key == previous or (previous is None and row < 0 and server and self._host.is_current_server(server)):
                row = index
        if row < 0 and self._servers:
            row = 0
        self.server_list.setCurrentRow(row)
        self.server_list.blockSignals(False)
        self._show_server()

    @staticmethod
    def _key(server):
        return server_key(server) if server is not None else ''

    def _selected_server_key(self):
        row = self.server_list.currentRow()
        return self._key(self._servers[row]) if 0 <= row < len(self._servers) else None

    def _selected_server(self):
        row = self.server_list.currentRow()
        return self._servers[row] if 0 <= row < len(self._servers) else None

    def _sources_for(self, server, sources=None):
        sources = self._host.playlist_sources() if sources is None else sources
        if server is None:
            return [source for source in sources if self._host.server_for_playlist(source) is None]
        key = server_key(server)
        return [source for source in sources if source.server == key]

    def _show_server(self):
        """Fill the right side with the selected server's playlists."""
        row = self.server_list.currentRow()
        server = self._selected_server()
        has_row = 0 <= row < len(self._servers)
        selected = self.playlist_list.currentRow()
        self.playlist_list.clear()
        sources = self._sources_for(server) if has_row else []
        for source in sources:
            item = QListWidgetItem(self._label(source))
            item.setData(Qt.ItemDataRole.UserRole, source.to_dict())
            self.playlist_list.addItem(item)
        if sources:
            self.playlist_list.setCurrentRow(min(max(selected, 0), len(sources) - 1))
        if not has_row:
            self.title_label.setText('No servers')
            self.count_label.setText('Add a server in Server Management first.')
        elif server is None:
            self.title_label.setText(REMOVED_SERVERS)
            self.count_label.setText('Their server is no longer in the list. Remove forgets them.')
        else:
            self.title_label.setText(server.get('name', ''))
            self.count_label.setText(_playlists(len(sources)).capitalize())
        empty = not sources
        self.playlist_label.setVisible(not empty)
        self.playlist_list.setVisible(not empty)
        self.empty_label.setText('No playlists yet. Use Import Playlist to add channels from one.')
        self.empty_label.setVisible(empty and server is not None and has_row)
        self._sync_buttons()

    def _label(self, source):
        busy = ' — updating…' if self._host.is_playlist_busy(source) else ''
        return f'{source.name}{busy}'

    def _follow_busy(self):
        for row in range(self.playlist_list.count()):
            item = self.playlist_list.item(row)
            text = self._label(PlaylistSource.from_dict(item.data(Qt.ItemDataRole.UserRole)))
            if item.text() != text:
                item.setText(text)
        self._sync_buttons()

    def _selected(self):
        item = self.playlist_list.currentItem()
        return PlaylistSource.from_dict(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _sync_buttons(self):
        source = self._selected()
        running = (self._job is not None and self._job.is_running()) or self._stopping is not None
        busy = source is not None and self._host.is_playlist_busy(source)
        has_server = source is not None and self._host.server_for_playlist(source) is not None
        self.refresh_btn.setEnabled(not running and not busy and has_server)
        self.remove_btn.setEnabled(not running and source is not None)
        self.refresh_btn.setToolTip('This playlist is being updated.' if busy and not running else '')
        self.playlist_list.setEnabled(not running)
        self.server_list.setEnabled(not running)
        self.import_btn.setEnabled(not running and self._selected_server() is not None)

    def _import(self):
        server = self._selected_server()
        if server is None:
            return
        ImportPlaylistDialog(self._host, self, server=server).exec()
        self._load()

    def _confirm_remove(self):
        source = self._selected()
        if source is None:
            return
        if self._host.server_for_playlist(source) is None:
            self._host.forget_playlist_source(source.to_dict())
            self._load()
            return
        busy = self._host.is_playlist_busy(source)
        question = (
            f'{source.name} is being updated. Stop the update and remove its channels?' if busy
            else f'Remove the channels from {source.name}?'
        )
        answer = QMessageBox.question(
            self,
            'Remove Playlist',
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not busy:
            self._run(remove=True)
            return
        job = self._host.stop_playlist_job(source)
        if job is None:
            announce_label(self.status_label, BUSY)
            return
        self._stopping = job
        announce_label(self.status_label, 'Stopping the update…')
        job.finished.connect(lambda *_args: self._stopped(source))
        job.failed.connect(lambda *_args: self._stopped(source))
        self._sync_buttons()

    def _stopped(self, source):
        if self._stopping is None:
            return
        self._stopping = None
        # The stopped job saved the playlist's latest state; remove that one.
        current = find_source(self._host.playlist_sources(), source.location, source.server)
        self._load()
        if current is not None:
            self._run(remove=True, source=current)

    def _run(self, remove, source=None):
        source = source or self._selected()
        server = self._host.server_for_playlist(source) if source is not None else None
        if server is None:
            return
        action = PlaylistJob.REMOVE if remove else PlaylistJob.SYNC
        self._job = PlaylistJob(self._host, source, server, action=action, parent=self)
        self._job.status.connect(lambda message: announce_label(self.status_label, message))
        self._job.progress.connect(self._progress)
        self._job.checking.connect(self.hint_label.show)
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
        self.hint_label.hide()
        announce_label(self.status_label, message)
        self._host.playlist_imported(self._job.server)
        self._load()

    def _failed(self, message):
        self.progress_bar.hide()
        self.hint_label.hide()
        announce_label(self.status_label, message)
        self._sync_buttons()

    def reject(self):
        if self._job is not None and self._job.is_checking():
            self._job.detach()
            self._host.keep_playlist_job(self._job)
            self._job = None
        elif self._job is not None and self._job.is_running():
            self._job.cancel()
            announce_label(self.status_label, 'Stopping…')
            return
        super().reject()

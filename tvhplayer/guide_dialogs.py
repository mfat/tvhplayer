"""Programme guide sources for servers on this computer: add, find, match channels, update.

The work is done by ``core.guide_feeds`` and ``core.guide_update`` on worker
threads; these windows show it in plain words.
"""

from __future__ import annotations

import os
import time

import requests
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
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
    QSpinBox,
    QVBoxLayout,
)

try:
    from .a11y import announce_label, buddy_label, describe, set_item_access
    from .core.errors import TvhError
    from .core.guide_feeds import UPDATE_HOURS, GuideError, build_index, find_guides, guide_name, is_web_address
    from .core.guide_match import Choice, assign, main_region
    from .core.guide_update import server_channels, update_server_guide
    from .core.playlist_sync import error_message, server_key
    from .core.proxy import configure_session
    from .core.tvh_admin import TvhAdmin
    from .playlist_dialogs import _Task
except ImportError:
    from a11y import announce_label, buddy_label, describe, set_item_access
    from core.errors import TvhError
    from core.guide_feeds import UPDATE_HOURS, GuideError, build_index, find_guides, guide_name, is_web_address
    from core.guide_match import Choice, assign, main_region
    from core.guide_update import server_channels, update_server_guide
    from core.playlist_sync import error_message, server_key
    from core.proxy import configure_session
    from core.tvh_admin import TvhAdmin
    from playlist_dialogs import _Task

HOURS_LABELS = {6: 'Every 6 hours', 12: 'Every 12 hours', 24: 'Every day', 168: 'Every week', 0: 'Only when asked'}
SOURCES_HELP = (
    'Guides are XMLTV files from the internet or this computer. TVHplayer downloads them, keeps the '
    'last good copy, and loads the programmes of your channels into the server. A channel gets a guide '
    'when its guide ID is in one; others can be matched by name under Match Channels.'
)
TEXT_TIMEOUT = (30, 120)


def _ago(stamp, now=None):
    seconds = max(0, (time.time() if now is None else now) - stamp)
    if seconds < 90:
        return 'just now'
    if seconds < 5400:
        return f'{round(seconds / 60)} minutes ago'
    if seconds < 36 * 3600:
        hours = round(seconds / 3600)
        return '1 hour ago' if hours == 1 else f'{hours} hours ago'
    days = round(seconds / 86400)
    return '1 day ago' if days == 1 else f'{days} days ago'


def source_state(source, summary, now=None):
    """One line about a guide source: what it holds and when it was updated."""
    if summary is None:
        if source.error:
            return f'Not loaded: {source.error}'
        return 'Not loaded yet'
    count = len(summary.channels)
    text = f'{count:,} channel{"s" if count != 1 else ""}'
    if source.updated:
        text += f', updated {_ago(source.updated, now)}'
    if source.error:
        text += f'. Last update failed: {source.error}'
    if summary.no_zone:
        text += '. Its times have no time zone, so they may be off by hours'
    return text


def fetch_text(url):
    with requests.Session() as session:
        configure_session(session, url)
        response = session.get(url, timeout=TEXT_TIMEOUT)
        response.raise_for_status()
        return response.text


class GuideJob(QObject):
    """Update one server's guides and load them into it, off the UI thread.

    ``host`` is the main window. It starts the built-in server when needed
    and saves the sources' new state when the job ends.
    """

    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, host, server, force=False, parent=None):
        super().__init__(parent)
        self._host = host
        self.server = server
        self.force = force
        self._task = None
        self._busy = False
        self._cancelled = False
        self.message = ''
        self.ok = False
        self.report = None

    def start(self):
        self._busy = True
        self.status.emit('Starting…')
        self._host.ensure_server_ready(self.server, self._ready, self._stop_with)

    def is_running(self):
        return self._busy

    def cancel(self):
        self._cancelled = True

    def shutdown(self, timeout_ms):
        self._cancelled = True
        task = self._task
        if task is not None and task.isRunning():
            return task.wait(timeout_ms)
        return True

    def _stop_with(self, message):
        self._busy = False
        self.message = message
        self.failed.emit(message)

    def _ready(self, server):
        self.server = server
        if self._cancelled:
            self._stop_with('Stopped.')
            return
        sources = self._host.guide_sources(server)
        choices = self._host.guide_choices(server)
        cache = self._host.guide_cache()
        force = self.force

        def work(task):
            with TvhAdmin(server) as admin:
                report = update_server_guide(
                    admin, server, cache, sources, choices, force,
                    status=task.status.emit, progress=task.progress.emit,
                    cancelled=lambda: self._cancelled,
                )
            return report, sources

        task = _Task(work, self)
        task.status.connect(self.status.emit)
        task.progress.connect(self.progress.emit)
        task.succeeded.connect(self._done)
        task.failed.connect(lambda exc: self._failed(exc, sources))
        self._task = task
        task.start()

    def _done(self, result):
        report, sources = result
        self._host.store_guide_states(sources)
        self._busy = False
        self.ok = True
        self.report = report
        self.message = report.message()
        self.finished.emit(report)

    def _failed(self, exc, sources):
        self._host.store_guide_states(sources)
        if isinstance(exc, GuideError):
            message = f'The TV guide could not be loaded. {exc}'
        elif isinstance(exc, TvhError):
            message = error_message(exc, self.server.get('name', 'the server'), 'load the guide for')
        else:
            message = f'The TV guide could not be loaded: {exc}'
        self._stop_with(message)


class GuideSourcesDialog(QDialog):
    """The guides used for each server on this computer."""

    def __init__(self, host, parent=None, server=None):
        super().__init__(parent)
        self._host = host
        self._job = None
        self._servers = list(host.guide_servers())
        self.setWindowTitle('Guide Sources')
        self.setModal(True)
        self.setMinimumSize(640, 440)
        self.setAccessibleName('Guide Sources')
        self.setAccessibleDescription(SOURCES_HELP)
        layout = QVBoxLayout(self)

        self.server_combo = QComboBox()
        for item in self._servers:
            self.server_combo.addItem(item.get('name', ''))
        describe(self.server_combo, 'Server', 'The server on this computer whose guides are shown.')
        server_row = QHBoxLayout()
        server_row.addWidget(buddy_label('&Server:', self.server_combo))
        server_row.addWidget(self.server_combo, 1)
        layout.addLayout(server_row)
        if len(self._servers) < 2:
            self.server_combo.setEnabled(False)

        help_label = QLabel(SOURCES_HELP)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.source_list = QListWidget()
        describe(self.source_list, 'Guides', 'The programme guides used for this server, first ones first.')
        layout.addWidget(buddy_label('&Guides:', self.source_list))
        layout.addWidget(self.source_list, 1)

        hours_row = QHBoxLayout()
        self.hours_combo = QComboBox()
        for hours in UPDATE_HOURS:
            self.hours_combo.addItem(HOURS_LABELS[hours], hours)
        describe(self.hours_combo, 'Update', 'How often TVHplayer downloads the selected guide again while it runs.')
        hours_row.addWidget(buddy_label('U&pdate:', self.hours_combo))
        hours_row.addWidget(self.hours_combo)
        hours_row.addStretch(1)
        layout.addLayout(hours_row)

        buttons_row = QHBoxLayout()
        self.find_btn = QPushButton('&Find Guides…')
        describe(self.find_btn, 'Find guides', 'Look for free guides that have your channels, by their guide IDs.')
        self.add_btn = QPushButton('&Add…')
        describe(self.add_btn, 'Add guide', 'Add a guide by its web address or from a file.')
        self.remove_btn = QPushButton('&Remove')
        describe(self.remove_btn, 'Remove guide', 'Stop using the selected guide.')
        self.match_btn = QPushButton('&Match Channels…')
        describe(self.match_btn, 'Match channels', 'See which guide each channel uses, and match channels by name.')
        self.update_btn = QPushButton('&Update Now')
        describe(self.update_btn, 'Update now', 'Download every guide again and load it into the server.')
        for button in (self.find_btn, self.add_btn, self.remove_btn, self.match_btn, self.update_btn):
            buttons_row.addWidget(button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        describe(self.progress_bar, 'Progress')
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self.server_combo.currentIndexChanged.connect(lambda _i: self._show())
        self.source_list.currentRowChanged.connect(lambda _r: self._sync())
        self.hours_combo.activated.connect(self._hours_chosen)
        self.find_btn.clicked.connect(self._find)
        self.add_btn.clicked.connect(self._add)
        self.remove_btn.clicked.connect(self._remove)
        self.match_btn.clicked.connect(self._match)
        self.update_btn.clicked.connect(lambda: self._update(force=True))
        if server is not None:
            for index, item in enumerate(self._servers):
                if server_key(item) == server_key(server):
                    self.server_combo.setCurrentIndex(index)
        self._show()
        job = self._server() and host.guide_job(self._server())
        if job:
            self._follow(job)

    def _server(self):
        index = self.server_combo.currentIndex()
        return self._servers[index] if 0 <= index < len(self._servers) else None

    def _sources(self):
        server = self._server()
        return self._host.guide_sources(server) if server else []

    def _show(self):
        row = self.source_list.currentRow()
        self.source_list.clear()
        cache = self._host.guide_cache()
        for source in self._sources():
            state = source_state(source, cache.summary(source.location))
            item = QListWidgetItem(f'{source.label()}\n{state}')
            set_item_access(item, f'{source.label()}. {state}', source.location)
            item.setToolTip(source.location)
            self.source_list.addItem(item)
        if self.source_list.count():
            self.source_list.setCurrentRow(min(max(row, 0), self.source_list.count() - 1))
        if not self._servers:
            announce_label(self.status_label, 'There is no server on this computer to load guides into.')
        elif not self.source_list.count() and not self.status_label.text():
            self.status_label.setText('No guides yet. Find Guides looks for free ones that have your channels.')
        self._sync()

    def _selected(self):
        row = self.source_list.currentRow()
        sources = self._sources()
        return sources[row] if 0 <= row < len(sources) else None

    def _sync(self):
        busy = self._job is not None and self._job.is_running()
        has_server = self._server() is not None
        source = self._selected()
        for button in (self.find_btn, self.add_btn, self.match_btn):
            button.setEnabled(has_server and not busy)
        self.remove_btn.setEnabled(source is not None and not busy)
        self.update_btn.setEnabled(has_server and bool(self._sources()) and not busy)
        self.hours_combo.setEnabled(source is not None)
        if source is not None:
            index = self.hours_combo.findData(source.hours)
            if index < 0:
                self.hours_combo.addItem(f'Every {source.hours} hours', source.hours)
                index = self.hours_combo.count() - 1
            self.hours_combo.setCurrentIndex(index)

    def _hours_chosen(self, _index):
        source = self._selected()
        if source is None:
            return
        source.hours = self.hours_combo.currentData()
        self._host.store_guide_source(source)
        self._show()

    def _find(self):
        dialog = FindGuidesDialog(self._host, self._server(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen:
            self._host.add_guide_sources(self._server(), dialog.chosen)
            self._show()
            self._update(force=False)

    def _add(self):
        dialog = AddGuideDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.location:
            self._host.add_guide_sources(self._server(), [(dialog.location, guide_name(dialog.location))])
            self._show()
            self._update(force=False)

    def _remove(self):
        source = self._selected()
        if source is None:
            return
        answer = QMessageBox.question(
            self, 'Remove Guide?',
            f'Stop using {source.label()}? Channels that took their programmes from it lose them at the next update.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._host.remove_guide_source(source)
        self._show()
        self._update(force=False)

    def _match(self):
        dialog = MatchChannelsDialog(self._host, self._server(), self)
        dialog.exec()
        if dialog.changed:
            self._update(force=False)

    def _update(self, force):
        server = self._server()
        if server is None:
            return
        self._follow(self._host.update_guide(server, force=force))

    def _follow(self, job):
        self._job = job
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        job.status.connect(self._status)
        job.progress.connect(self._progress)
        job.finished.connect(self._finished)
        job.failed.connect(self._failed)
        self._sync()

    def _status(self, text):
        announce_label(self.status_label, text)
        self.progress_bar.setRange(0, 0)

    def _progress(self, done, total):
        if total:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(done, total))

    def _finished(self, _report):
        self.progress_bar.hide()
        announce_label(self.status_label, self._job.message)
        self._show()

    def _failed(self, message):
        self.progress_bar.hide()
        announce_label(self.status_label, message)
        self._show()

    def done(self, result):
        job = self._job
        if job is not None:
            for signal in (job.status, job.progress, job.finished, job.failed):
                try:
                    signal.disconnect()
                except TypeError:
                    pass
        super().done(result)


class AddGuideDialog(QDialog):
    """Ask for a guide's web address or file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.location = ''
        self.setWindowTitle('Add Guide')
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText('https://… or a file on this computer')
        describe(self.edit, 'Guide address or file',
                 'The web address of an XMLTV guide, packed or not, or a guide file on this computer.')
        layout.addWidget(buddy_label('&Web address or file of an XMLTV guide:', self.edit))
        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        browse = QPushButton('&Browse…')
        describe(browse, 'Browse', 'Pick a guide file on this computer.')
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)
        self.error_label = QLabel('')
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('&Add')
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, 'Guide File', '', 'XMLTV guides (*.xml *.gz *.xz);;All files (*)')
        if path:
            self.edit.setText(path)

    def _accept(self):
        text = self.edit.text().strip()
        if not text:
            announce_label(self.error_label, 'Enter a web address or pick a file.')
            return
        if not is_web_address(text):
            text = os.path.abspath(os.path.expanduser(text))
            if not os.path.isfile(text):
                announce_label(self.error_label, 'There is no file there.')
                return
        self.location = text
        self.accept()


class FindGuidesDialog(QDialog):
    """Look for free guides that have the server's channels, by their guide IDs."""

    def __init__(self, host, server, parent=None):
        super().__init__(parent)
        self._host = host
        self._server = server
        self._cancelled = False
        self._task = None
        self.chosen = []
        self.setWindowTitle('Find Guides')
        self.setMinimumSize(560, 380)
        self.setAccessibleName('Find Guides')
        layout = QVBoxLayout(self)
        intro = QLabel(
            'TVHplayer compares your channels\' guide IDs with the free guides of epgshare01 and '
            'iptv-epg.org. Guides for a country are large; the first look can take a few minutes.'
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.result_list = QListWidget()
        describe(self.result_list, 'Guides found', 'Tick the guides to use. The best ones are ticked for you.')
        layout.addWidget(buddy_label('&Guides found:', self.result_list))
        layout.addWidget(self.result_list, 1)
        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        describe(self.progress_bar, 'Progress')
        layout.addWidget(self.progress_bar)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.add_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add_btn.setText('&Use Ticked Guides')
        self.add_btn.setEnabled(False)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        QTimer.singleShot(0, self._start)

    def _start(self):
        self._host.ensure_server_ready(self._server, self._ready, self._stopped)

    def _stopped(self, message):
        self.progress_bar.hide()
        announce_label(self.status_label, message)

    def _ready(self, server):
        self._server = server
        cache = self._host.guide_cache()
        known = {source.location for source in self._host.guide_sources(server)}

        def fetch_summary(location, task):
            summary = cache.summary(location)
            if summary is not None:
                return summary
            return cache.refresh(location, progress=task.progress.emit, cancelled=lambda: self._cancelled)

        def work(task):
            with TvhAdmin(server) as admin:
                channels = server_channels(admin)
            ids = [epg_id for channel in channels for epg_id in channel.epg_ids]
            if not ids:
                return None
            candidates, problems = find_guides(
                ids, fetch_text, lambda location: fetch_summary(location, task),
                status=task.status.emit, cancelled=lambda: self._cancelled,
            )
            return [c for c in candidates if c.location not in known], problems

        task = _Task(work, self)
        task.status.connect(lambda text: announce_label(self.status_label, text))
        task.progress.connect(self._progress)
        task.succeeded.connect(self._found)
        task.failed.connect(lambda exc: self._stopped(f'Could not look for guides: {exc}'))
        self._task = task
        task.start()

    def _progress(self, done, total):
        if total:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(done, total))
        else:
            self.progress_bar.setRange(0, 0)

    def _found(self, result):
        self.progress_bar.hide()
        if result is None:
            announce_label(
                self.status_label,
                'Your channels have no guide IDs, so no guide can be found for them. '
                'Add a guide by its address, then match the channels by name under Match Channels.',
            )
            return
        candidates, problems = result
        for candidate in candidates:
            text = f'{candidate.name}: {candidate.matched} of {candidate.total} channels'
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if candidate.recommended else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, (candidate.location, candidate.name))
            item.setToolTip(candidate.location)
            set_item_access(item, text, candidate.location)
            self.result_list.addItem(item)
        if candidates:
            message = f'Found {len(candidates)} guide{"s" if len(candidates) != 1 else ""} with your channels.'
            self.add_btn.setEnabled(True)
            self.result_list.setCurrentRow(0)
            self.result_list.setFocus()
        else:
            message = 'No free guide has your channels\' IDs.'
        if problems:
            message += ' ' + ' '.join(problems)
        announce_label(self.status_label, message)

    def _accept(self):
        self.chosen = []
        for row in range(self.result_list.count()):
            item = self.result_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                self.chosen.append(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

    def done(self, result):
        self._cancelled = True
        task = self._task
        if task is not None and task.isRunning():
            task.wait(15000)
        super().done(result)


AUTO = 'auto'
NONE = 'none'


class MatchChannelsDialog(QDialog):
    """Each channel's guide: matched by ID, chosen here, or none, with name suggestions."""

    SHOW_ALL, SHOW_MISSING, SHOW_CHOSEN = 0, 1, 2

    def __init__(self, host, server, parent=None):
        super().__init__(parent)
        self._host = host
        self._server = server
        self._task = None
        self._channels = []
        self._index = None
        self._region = ''
        self._suggestions = {}
        self._choices = {}
        self._assignments = {}
        self._filling = False
        self.changed = False
        self.setWindowTitle('Match Channels')
        self.setMinimumSize(760, 520)
        self.setAccessibleName('Match Channels')
        self.setAccessibleDescription(
            'Each channel and the guide channel its programmes come from. Channels with a guide ID '
            'take the guide channel with the same ID. Others can be matched by name.'
        )
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.show_combo = QComboBox()
        self.show_combo.addItems(['All channels', 'Channels without a guide', 'Channels matched by hand'])
        describe(self.show_combo, 'Show', 'Which channels are listed.')
        filters.addWidget(buddy_label('Sh&ow:', self.show_combo))
        filters.addWidget(self.show_combo)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('Channel name')
        describe(self.filter_edit, 'Find channel', 'List only channels whose name contains this.')
        filters.addWidget(buddy_label('&Find:', self.filter_edit))
        filters.addWidget(self.filter_edit, 1)
        layout.addLayout(filters)

        self.channel_list = QListWidget()
        describe(self.channel_list, 'Channels',
                 'Each channel and its guide. Tick suggested matches, then choose Use Ticked Suggestions.')
        layout.addWidget(buddy_label('&Channels:', self.channel_list))
        layout.addWidget(self.channel_list, 1)

        suggestions_row = QHBoxLayout()
        self.use_btn = QPushButton('Use &Ticked Suggestions')
        describe(self.use_btn, 'Use ticked suggestions', 'Give each ticked channel the guide suggested for it.')
        suggestions_row.addWidget(self.use_btn)
        suggestions_row.addStretch(1)
        layout.addLayout(suggestions_row)

        self.detail_label = QLabel('')
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)
        guide_row = QHBoxLayout()
        self.guide_combo = QComboBox()
        describe(self.guide_combo, 'Guide for this channel', 'Where the selected channel\'s programmes come from.')
        guide_row.addWidget(buddy_label('&Guide:', self.guide_combo))
        guide_row.addWidget(self.guide_combo, 1)
        self.shift_spin = QSpinBox()
        self.shift_spin.setRange(-1440, 1440)
        self.shift_spin.setSingleStep(15)
        self.shift_spin.setSuffix(' min')
        describe(self.shift_spin, 'Shift times by',
                 'Move the programmes later or earlier, for example 60 minutes for a "+1" channel.')
        guide_row.addWidget(buddy_label('S&hift times by:', self.shift_spin))
        guide_row.addWidget(self.shift_spin)
        layout.addLayout(guide_row)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('Name or ID in the guides')
        describe(self.search_edit, 'Search the guides', 'Add guide channels with this name or ID to the Guide list.')
        search_row.addWidget(buddy_label('Sea&rch the guides:', self.search_edit))
        search_row.addWidget(self.search_edit, 1)
        layout.addLayout(search_row)

        self.status_label = QLabel('Reading the channels and guides…')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        for widget in (self.channel_list, self.use_btn, self.guide_combo, self.shift_spin, self.search_edit,
                       self.show_combo, self.filter_edit):
            widget.setEnabled(False)
        self.show_combo.currentIndexChanged.connect(lambda _i: self._fill())
        self.filter_edit.textChanged.connect(lambda _t: self._fill())
        self.channel_list.currentRowChanged.connect(lambda _r: self._show_channel())
        self.channel_list.itemChanged.connect(lambda _item: self._sync_use())
        self.use_btn.clicked.connect(self._use_ticked)
        self.guide_combo.activated.connect(self._guide_chosen)
        self.shift_spin.editingFinished.connect(self._shift_edited)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._search)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        QTimer.singleShot(0, self._start)

    def _start(self):
        self._host.ensure_server_ready(self._server, self._ready, self._stopped)

    def _stopped(self, message):
        announce_label(self.status_label, message)

    def _ready(self, server):
        self._server = server
        cache = self._host.guide_cache()
        sources = self._host.guide_sources(server)

        def work(_task):
            with TvhAdmin(server) as admin:
                channels = server_channels(admin)
            return channels, build_index(cache, sources)

        task = _Task(work, self)
        task.succeeded.connect(self._loaded)
        task.failed.connect(lambda exc: self._stopped(f'Could not read the channels: {exc}'))
        self._task = task
        task.start()

    def _loaded(self, result):
        self._channels, self._index = result
        self._channels.sort(key=lambda channel: channel.name.casefold())
        self._region = main_region(self._channels)
        self._choices = self._host.guide_choices(self._server)
        self._assignments = assign(self._channels, self._index, self._choices)
        for widget in (self.channel_list, self.guide_combo, self.shift_spin, self.search_edit,
                       self.show_combo, self.filter_edit):
            widget.setEnabled(True)
        if not self._index.channels:
            announce_label(self.status_label, 'No guide is loaded yet. Add or update a guide first.')
        self._fill()
        self.channel_list.setFocus()

    def _suggest(self, channel):
        if channel.uuid not in self._suggestions:
            self._suggestions[channel.uuid] = self._index.suggest(channel, self._region)
        return self._suggestions[channel.uuid]

    def _line(self, channel):
        assignment = self._assignments.get(channel.uuid)
        if assignment is not None:
            guide = assignment.channel
            how = 'same ID' if assignment.how == 'id' else 'chosen'
            text = f'{channel.name}: {guide.name} ({self._source_label(guide.source)}, {how})'
            if assignment.shift:
                text += f', {assignment.shift:+d} min'
            return text, None
        choice = self._choices.get(channel.uuid)
        if choice is not None and not choice.id:
            return f'{channel.name}: no guide (chosen)', None
        suggestions = self._suggest(channel)
        if suggestions:
            best = suggestions[0]
            text = (f'{channel.name}: no guide. Suggested: {best.channel.name} '
                    f'({self._source_label(best.channel.source)}, {round(best.score * 100)}%)')
            if best.shift:
                text += f', {best.shift:+d} min'
            return text, best
        return f'{channel.name}: no guide', None

    def _source_label(self, location):
        for source in self._host.guide_sources(self._server):
            if source.location == location:
                return source.label()
        return guide_name(location)

    def _visible(self):
        mode = self.show_combo.currentIndex()
        needle = self.filter_edit.text().strip().casefold()
        for channel in self._channels:
            if needle and needle not in channel.name.casefold():
                continue
            if mode == self.SHOW_MISSING and channel.uuid in self._assignments:
                continue
            if mode == self.SHOW_CHOSEN and channel.uuid not in self._choices:
                continue
            yield channel

    def _fill(self, keep=None):
        current = keep or self._current_uuid()
        self._filling = True
        self.channel_list.clear()
        row = 0
        for channel in self._visible():
            text, suggestion = self._line(channel)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, channel.uuid)
            if suggestion is not None:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Similar names, and names from another country, are left for the user to tick.
                item.setCheckState(Qt.CheckState.Checked if suggestion.sure else Qt.CheckState.Unchecked)
            set_item_access(item, text)
            self.channel_list.addItem(item)
            if channel.uuid == current:
                row = self.channel_list.count() - 1
        self._filling = False
        if self.channel_list.count():
            self.channel_list.setCurrentRow(row)
        self._show_channel()
        self._sync_use()
        missing = sum(1 for channel in self._channels if channel.uuid not in self._assignments)
        announce_label(
            self.status_label,
            f'{len(self._channels) - missing} of {len(self._channels)} channels have a guide.',
        )

    def _current_uuid(self):
        item = self.channel_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _channel(self, uuid):
        for channel in self._channels:
            if channel.uuid == uuid:
                return channel
        return None

    def _sync_use(self):
        if self._filling:
            return
        ticked = any(
            self.channel_list.item(row).checkState() == Qt.CheckState.Checked
            for row in range(self.channel_list.count())
            if self.channel_list.item(row).flags() & Qt.ItemFlag.ItemIsUserCheckable
        )
        self.use_btn.setEnabled(ticked)

    def _use_ticked(self):
        changes = {}
        for row in range(self.channel_list.count()):
            item = self.channel_list.item(row)
            if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable or item.checkState() != Qt.CheckState.Checked:
                continue
            channel = self._channel(item.data(Qt.ItemDataRole.UserRole))
            suggestions = self._suggest(channel) if channel else []
            if suggestions:
                best = suggestions[0]
                changes[channel.uuid] = Choice(best.channel.source, best.channel.id, best.shift)
        if changes:
            self._host.set_guide_choices(self._server, changes)
            self._choices_changed()
        self._fill()
        count = len(changes)
        announce_label(self.status_label, f'Matched {count} channel{"s" if count != 1 else ""} by name.')

    def _show_channel(self, extra=()):
        channel = self._channel(self._current_uuid())
        self.guide_combo.clear()
        if channel is None:
            self.detail_label.setText('')
            self.guide_combo.setEnabled(False)
            self.shift_spin.setEnabled(False)
            return
        self.guide_combo.setEnabled(True)
        auto = None
        for epg_id in channel.epg_ids:
            auto = self._index.by_id(epg_id)
            if auto is not None:
                break
        ids = ', '.join(channel.epg_ids) or 'none'
        self.detail_label.setText(f'{channel.name}. Guide ID: {ids}.')
        if auto is not None:
            self.guide_combo.addItem(f'Same ID: {auto.name} ({self._source_label(auto.source)})', AUTO)
        else:
            self.guide_combo.addItem('Same ID: none of the guides has this channel\'s ID', AUTO)
        self.guide_combo.addItem('No guide', NONE)
        seen = set()
        for suggestion in self._suggest(channel):
            guide = suggestion.channel
            seen.add((guide.source, guide.id))
            self.guide_combo.addItem(
                f'{guide.name} ({self._source_label(guide.source)}, {guide.id}, {round(suggestion.score * 100)}%)',
                (guide.source, guide.id, suggestion.shift))
        for guide in extra:
            if (guide.source, guide.id) not in seen:
                seen.add((guide.source, guide.id))
                self.guide_combo.addItem(f'{guide.name} ({self._source_label(guide.source)}, {guide.id})',
                                         (guide.source, guide.id, 0))
        choice = self._choices.get(channel.uuid)
        if choice is None:
            index = 0
        elif not choice.id:
            index = 1
        else:
            index = -1
            for row in range(self.guide_combo.count()):
                data = self.guide_combo.itemData(row)
                if isinstance(data, tuple) and data[:2] == (choice.source, choice.id):
                    index = row
            if index < 0:
                guide = self._index.find(choice.source, choice.id)
                name = guide.name if guide else choice.id
                self.guide_combo.addItem(f'{name} ({self._source_label(choice.source)}, {choice.id})',
                                         (choice.source, choice.id, choice.shift))
                index = self.guide_combo.count() - 1
        self.guide_combo.setCurrentIndex(index)
        assignment = self._assignments.get(channel.uuid)
        self.shift_spin.setEnabled(assignment is not None)
        self.shift_spin.setValue(assignment.shift if assignment else 0)

    def _guide_chosen(self, _index):
        channel = self._channel(self._current_uuid())
        if channel is None:
            return
        data = self.guide_combo.currentData()
        if data == AUTO:
            choice = None
        elif data == NONE:
            choice = Choice()
        else:
            source, guide_id, shift = data
            current = self._assignments.get(channel.uuid)
            if current is not None and (current.channel.source, current.channel.id) == (source, guide_id):
                shift = current.shift
            choice = Choice(source, guide_id, shift)
        self._set_choice(channel, choice)

    def _shift_edited(self):
        channel = self._channel(self._current_uuid())
        assignment = self._assignments.get(channel.uuid) if channel else None
        if assignment is None or self.shift_spin.value() == assignment.shift:
            return
        guide = assignment.channel
        self._set_choice(channel, Choice(guide.source, guide.id, self.shift_spin.value()))

    def _set_choice(self, channel, choice):
        self._host.set_guide_choices(self._server, {channel.uuid: choice})
        self._choices_changed()
        self._fill(keep=channel.uuid)

    def _choices_changed(self):
        self._choices = self._host.guide_choices(self._server)
        self._assignments = assign(self._channels, self._index, self._choices)
        self.changed = True

    def _search(self):
        if self._index is None:
            return
        found = self._index.search(self.search_edit.text())
        self._show_channel(extra=found)
        if found:
            announce_label(self.status_label, f'{len(found)} guide channels found; choose one in the Guide list.')
        elif self.search_edit.text().strip():
            announce_label(self.status_label, 'No guide channel has that name or ID.')

    def done(self, result):
        task = self._task
        if task is not None and task.isRunning():
            task.wait(15000)
        super().done(result)

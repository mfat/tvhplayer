import os
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import tvhplayer.guide_dialogs as dialogs  # noqa: E402
from tvhplayer.core.guide_feeds import Candidate, GuideCache, GuideSource, format_time  # noqa: E402
from tvhplayer.core.guide_match import Choice  # noqa: E402

BUILTIN = {'name': 'Built-in Server', 'url': 'http://127.0.0.1:20000', 'builtin': True}


class FakeAdmin:
    channels = []

    def __init__(self, _server):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        pass

    def list_all_muxes(self):
        return [{'uuid': f'm-{row["uuid"]}', 'iptv_epgid': row.get('epg', '')} for row in self.channels]

    def list_services_all(self):
        return [{'uuid': f's-{row["uuid"]}', 'multiplex_uuid': f'm-{row["uuid"]}'} for row in self.channels]

    def list_channels(self):
        return [{'uuid': row['uuid'], 'name': row['name'], 'services': [f's-{row["uuid"]}']} for row in self.channels]


class FakeJob:
    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class Signals(QObject):
            status = pyqtSignal(str)
            progress = pyqtSignal(int, int)
            finished = pyqtSignal(object)
            failed = pyqtSignal(str)

        self._signals = Signals()
        self.status = self._signals.status
        self.progress = self._signals.progress
        self.finished = self._signals.finished
        self.failed = self._signals.failed
        self.message = 'TV guide loaded for 1 of 2 channels.'

    def is_running(self):
        return True


class FakeHost:
    def __init__(self, tmp_path):
        self.cache = GuideCache(tmp_path / 'cache')
        self.sources = []
        self.choices = {}
        self.updates = []

    def guide_servers(self):
        return [BUILTIN]

    def guide_cache(self):
        return self.cache

    def guide_sources(self, _server):
        return [GuideSource.from_dict(source.to_dict()) for source in self.sources]

    def add_guide_sources(self, _server, entries):
        for location, name in entries:
            self.sources.append(GuideSource(location, 'builtin', name=name))

    def store_guide_source(self, changed):
        self.sources = [changed if source.location == changed.location else source for source in self.sources]

    def remove_guide_source(self, gone):
        self.sources = [source for source in self.sources if source.location != gone.location]

    def guide_choices(self, _server):
        return dict(self.choices)

    def set_guide_choices(self, _server, changes):
        self.saves = getattr(self, 'saves', 0) + 1
        for uuid, choice in changes.items():
            if choice is None:
                self.choices.pop(uuid, None)
            else:
                self.choices[uuid] = choice

    def guide_job(self, _server):
        return None

    def update_guide(self, server, force=False):
        self.updates.append(force)
        self.job = FakeJob()
        return self.job

    def ensure_server_ready(self, server, on_ready, _on_failed):
        on_ready(server)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(dialogs, 'TvhAdmin', FakeAdmin)
    return QApplication.instance() or QApplication([])


def _until(app, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _guide_file(tmp_path):
    now = int(time.time())
    channels = [('BBCOne.uk', 'BBC One'), ('E4.uk', 'E4'), ('Dave.uk', 'Dave')]
    parts = ['<tv>']
    for channel_id, name in channels:
        parts.append(f'<channel id="{channel_id}"><display-name>{name}</display-name></channel>')
        parts.append(f'<programme start="{format_time(now)}" stop="{format_time(now + 3600)}" '
                     f'channel="{channel_id}"><title>On now</title></programme>')
    parts.append('</tv>')
    path = tmp_path / 'guide.xml'
    path.write_text(''.join(parts))
    return str(path)


def test_sources_window_lists_changes_and_removes(app, tmp_path, monkeypatch):
    host = FakeHost(tmp_path)
    location = _guide_file(tmp_path)
    host.cache.refresh(location)
    host.sources = [GuideSource(location, 'builtin', name='Mine', updated=time.time() - 7200),
                    GuideSource('https://example.invalid/g.xml', 'builtin', error='Could not download the guide.')]
    dialog = dialogs.GuideSourcesDialog(host)
    texts = [dialog.source_list.item(row).text() for row in range(dialog.source_list.count())]
    assert texts == ['Mine\n3 channels, updated 2 hours ago',
                     'example.invalid: g\nNot loaded: Could not download the guide.']
    assert dialog.hours_combo.currentData() == 12
    dialog.hours_combo.setCurrentIndex(dialog.hours_combo.findData(0))
    dialog.hours_combo.activated.emit(dialog.hours_combo.currentIndex())
    assert host.sources[0].hours == 0

    dialog.update_btn.click()
    assert host.updates == [True]
    assert not dialog.update_btn.isEnabled()
    host.job.status.emit('Downloading Mine…')
    assert dialog.status_label.text() == 'Downloading Mine…'
    host.job.is_running = lambda: False
    host.job.finished.emit(None)
    assert dialog.status_label.text() == 'TV guide loaded for 1 of 2 channels.'
    assert dialog.update_btn.isEnabled()

    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
    dialog.source_list.setCurrentRow(1)
    dialog.remove_btn.click()
    assert [source.label() for source in host.sources] == ['Mine']
    assert host.updates == [True, False]
    dialog.done(0)


def test_add_guide_checks_files(app, tmp_path):
    dialog = dialogs.AddGuideDialog()
    dialog.edit.setText(str(tmp_path / 'missing.xml'))
    dialog._accept()
    assert dialog.error_label.text() == 'There is no file there.'
    dialog.edit.setText(' https://example.com/g.xml.gz ')
    dialog._accept()
    assert dialog.location == 'https://example.com/g.xml.gz'


def test_find_guides_ticks_the_recommended_ones(app, tmp_path, monkeypatch):
    host = FakeHost(tmp_path)
    FakeAdmin.channels = [{'uuid': 'c1', 'name': 'BBC One', 'epg': 'BBCOne.uk'}]
    seen = {}

    def find(ids, fetch_text, fetch_summary, status, cancelled):
        seen['ids'] = ids
        status('Looking…')
        return [Candidate('iptv-epg.org GB', 'https://a/gb.xml.gz', 1, 1, True),
                Candidate('epgshare01 UK1', 'https://b/uk1.xml.gz', 1, 1, False)], ['epgshare01 DE1 could not be read.']

    monkeypatch.setattr(dialogs, 'find_guides', find)
    dialog = dialogs.FindGuidesDialog(host, BUILTIN)
    assert _until(app, lambda: dialog.result_list.count() == 2)
    assert seen['ids'] == ['BBCOne.uk']
    states = [dialog.result_list.item(row).checkState() for row in range(2)]
    assert states == [Qt.CheckState.Checked, Qt.CheckState.Unchecked]
    assert dialog.status_label.text() == 'Found 2 guides with your channels. epgshare01 DE1 could not be read.'
    dialog._accept()
    assert dialog.chosen == [('https://a/gb.xml.gz', 'iptv-epg.org GB')]


def test_find_guides_without_ids(app, tmp_path):
    host = FakeHost(tmp_path)
    FakeAdmin.channels = [{'uuid': 'c1', 'name': 'BBC One'}]
    dialog = dialogs.FindGuidesDialog(host, BUILTIN)
    assert _until(app, lambda: 'no guide IDs' in dialog.status_label.text())
    assert not dialog.add_btn.isEnabled()
    dialog.done(0)


def test_match_channels_by_id_suggestion_and_hand(app, tmp_path):
    host = FakeHost(tmp_path)
    location = _guide_file(tmp_path)
    host.cache.refresh(location)
    host.sources = [GuideSource(location, 'builtin', name='Mine')]
    FakeAdmin.channels = [
        {'uuid': 'c1', 'name': 'BBC One HD', 'epg': 'BBCOne.uk@HD'},
        {'uuid': 'c2', 'name': 'E4 +1'},
        {'uuid': 'c3', 'name': 'Something else'},
    ]
    dialog = dialogs.MatchChannelsDialog(host, BUILTIN)
    assert _until(app, lambda: dialog.channel_list.count() == 3)
    lines = [dialog.channel_list.item(row).text() for row in range(3)]
    assert lines == [
        'BBC One HD: BBC One (Mine, same ID)',
        'E4 +1: no guide. Suggested: E4 (Mine, 93%), +60 min',
        'Something else: no guide',
    ]
    assert dialog.status_label.text() == '1 of 3 channels have a guide.'
    assert dialog.channel_list.item(1).checkState() == Qt.CheckState.Checked
    assert dialog.use_btn.isEnabled()
    dialog.use_btn.click()
    assert host.choices == {'c2': Choice(location, 'E4.uk', 60)}
    assert host.saves == 1
    assert dialog.changed
    assert dialog.channel_list.item(1).text() == 'E4 +1: E4 (Mine, chosen), +60 min'

    # Pick a guide by hand for the last channel through a search.
    dialog.channel_list.setCurrentRow(2)
    dialog.search_edit.setText('dave')
    dialog._search()
    row = dialog.guide_combo.findText('Dave (Mine, Dave.uk)')
    assert row >= 0
    dialog.guide_combo.setCurrentIndex(row)
    dialog.guide_combo.activated.emit(row)
    assert host.choices['c3'] == Choice(location, 'Dave.uk', 0)
    dialog.shift_spin.setValue(-30)
    dialog.shift_spin.editingFinished.emit()
    assert host.choices['c3'] == Choice(location, 'Dave.uk', -30)

    # "No guide" turns off the match by ID; "Same ID" brings it back.
    dialog.show_combo.setCurrentIndex(dialog.SHOW_ALL)
    dialog.channel_list.setCurrentRow(0)
    dialog.guide_combo.setCurrentIndex(1)
    dialog.guide_combo.activated.emit(1)
    assert host.choices['c1'] == Choice()
    assert dialog.channel_list.item(0).text() == 'BBC One HD: no guide (chosen)'
    dialog.guide_combo.setCurrentIndex(0)
    dialog.guide_combo.activated.emit(0)
    assert 'c1' not in host.choices
    dialog.done(0)

import os
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication  # noqa: E402

import tvhplayer.playlist_dialogs as dialogs  # noqa: E402
from tvhplayer.core.errors import TvhAuthError  # noqa: E402
from tvhplayer.core.playlist_sync import PlaylistSource  # noqa: E402

BUILTIN = {'name': 'Built-in Server', 'url': 'http://127.0.0.1:20000', 'builtin': True}
OTHER = {'name': 'Living room', 'url': 'http://tv.lan:9981'}


class FakeAdmin:
    """One fake server per URL, kept across connections like a real one."""

    servers = {}

    def __init__(self, server):
        self.server = server
        state = FakeAdmin.servers.setdefault(server.get('url'), {'networks': {}, 'muxes': {}})
        self.networks = state['networks']
        self.muxes = state['muxes']

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        pass

    def check_admin(self):
        if self.server.get('url') == 'http://denied':
            raise TvhAuthError('HTTP 403')

    def network_exists(self, uuid):
        return uuid in self.networks

    def create_network(self, conf):
        self.networks['net'] = conf
        return 'net'

    def update_network(self, _uuid, _conf):
        pass

    def list_muxes(self, _network_uuid):
        return [dict(conf, uuid=uuid) for uuid, conf in self.muxes.items()]

    def create_mux(self, _network_uuid, conf):
        uuid = f'm{len(self.muxes) + 1}'
        # The server's scan of these streams has already passed.
        self.muxes[uuid] = dict(conf, scan_state=0, scan_result=1)
        return uuid

    def list_services(self, _mux_uuids):
        return []

    def scan_network(self, _network_uuid):
        pass

    def save(self, nodes):
        pass

    def delete(self, uuids):
        pass

    def enable_xmltv_socket(self):
        return ''

    def use_url_grabber(self, _url):
        return False

    def delete_unused_tags(self, names):
        self.tags_deleted = list(names)

    def map_network_bouquet(self, _network_uuid):
        pass

    def delete_orphan_channels(self, _network_uuid):
        return 0


class FakeHost:
    def __init__(self, targets, current=None):
        self.busy = set()
        self.targets = targets
        self.current = current
        self.stored = []
        self.imported = []
        self.changed = []
        self.shown = []
        self.kept = []
        self.hide_dead = True

    def import_targets(self):
        return list(self.targets)

    def playlist_sources(self):
        return [PlaylistSource.from_dict(data) for data in self.stored]

    def store_playlist_source(self, data):
        self.stored = [item for item in self.stored if item['location'] != data['location']] + [data]

    def ensure_server_ready(self, server, on_ready, on_failed):
        on_ready(server)

    def is_current_server(self, server):
        return self.current is not None and server.get('url') == self.current.get('url')

    def playlist_imported(self, server):
        self.imported.append(server)

    def playlist_channels_changed(self, server):
        self.changed.append(server)

    def show_server(self, server):
        self.shown.append(server)

    def keep_playlist_job(self, job):
        self.kept.append(job)

    def hides_dead_channels(self):
        return self.hide_dead


    def claim_playlist(self, source):
        key = (source.server, source.location)
        if key in self.busy:
            return False
        self.busy.add(key)
        return True

    def release_playlist(self, source):
        self.busy.discard((source.server, source.location))

    def is_playlist_busy(self, source):
        return (source.server, source.location) in self.busy

    def stop_playlist_job(self, source):
        for job in self.kept:
            if job.is_running() and job.source.location == source.location:
                job.cancel()
                return job
        return None

    def forget_playlist_source(self, data):
        self.stored = [item for item in self.stored if item['location'] != data['location']]

    def server_for_playlist(self, source):
        for server in self.targets:
            key = 'builtin' if server.get('builtin') else server['url']
            if key == source.server:
                return server
        return None


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(dialogs, 'TvhAdmin', FakeAdmin)
    monkeypatch.setattr(dialogs, 'ffmpeg_for_server', lambda _server: '/usr/bin/ffmpeg')
    FakeAdmin.servers = {}
    return QApplication.instance() or QApplication([])


def _run(app, dialog, timeout=10):
    dialog.import_btn.click()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if dialog._job is not None and not dialog._job.is_running():
            break
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()


def _playlist(tmp_path, text):
    path = tmp_path / 'news.m3u'
    path.write_text(text, encoding='utf-8')
    return str(path)


TWO = '#EXTM3U\n#EXTINF:-1 tvg-chno="1",A\nhttp://x/a.ts\n#EXTINF:-1,B\nhttp://x/b.m3u8\n'


def test_import_to_builtin_server_in_one_step(app, tmp_path):
    host = FakeHost([BUILTIN, OTHER], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    assert not dialog.server_combo.isHidden()
    dialog.location_input.setText(_playlist(tmp_path, TWO))
    _run(app, dialog)
    assert dialog.status_label.text() == 'Added 2 channels from news.'
    assert host.stored[-1]['server'] == 'builtin'
    assert set(host.stored[-1]['muxes']) == {'name:A', 'name:B'}
    assert host.imported == [BUILTIN]
    assert host.changed and host.changed[0] == BUILTIN
    assert dialog.show_btn.isHidden()
    assert dialog.details_btn.isHidden()
    assert dialog.import_btn.isEnabled()


def test_import_again_refreshes_the_same_playlist(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    assert dialog.server_combo.isHidden()
    dialog.location_input.setText(_playlist(tmp_path, TWO))
    _run(app, dialog)
    _run(app, dialog)
    assert len(host.stored) == 1
    assert dialog.status_label.text() == 'The channels from news are up to date.'


def test_other_server_offers_to_show_its_channels(app, tmp_path):
    host = FakeHost([BUILTIN, OTHER], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.server_combo.setCurrentIndex(1)
    dialog.location_input.setText(_playlist(tmp_path, TWO))
    _run(app, dialog)
    assert host.stored[-1]['server'] == 'http://tv.lan:9981'
    assert not dialog.show_btn.isHidden()
    dialog.show_btn.click()
    assert host.shown == [OTHER]


def test_errors_are_plain_sentences(app, tmp_path):
    host = FakeHost([{'name': 'Office', 'url': 'http://denied'}])
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.location_input.setText(_playlist(tmp_path, TWO))
    _run(app, dialog)
    assert dialog.status_label.text().startswith('This account cannot add channels to Office.')
    assert host.stored == []

    dialog.location_input.setText(_playlist(tmp_path, 'hello'))
    _run(app, dialog)
    assert dialog.status_label.text() == 'This file is not a TV playlist.'

    dialog.location_input.setText('')
    dialog.import_btn.click()
    assert dialog.status_label.text() == 'Enter a playlist address or choose a file.'


def test_playlist_programs_need_permission(app, tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(dialogs, 'ask_to_run_commands', lambda _parent, count, name: asked.append(count) or False)
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    text = TWO + '#EXTINF:-1,Live\npipe:///usr/bin/streamlink --stdout https://y/live best\n'
    dialog.location_input.setText(_playlist(tmp_path, text))
    _run(app, dialog)
    assert asked == [1]
    assert dialog.status_label.text() == 'Added 2 channels from news. 1 entry could not be added.'
    assert not dialog.details_btn.isHidden()
    assert host.stored[-1]['allow_commands'] is False


def _wait_job(app, dialog, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if dialog._job is not None and not dialog._job.is_running():
            break
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()


def test_playlists_dialog_refreshes_and_removes(app, tmp_path, monkeypatch):
    removed = []
    monkeypatch.setattr(dialogs, 'remove_playlist', lambda _admin, source: removed.append(source.name))
    host = FakeHost([BUILTIN], current=BUILTIN)
    importer = dialogs.ImportPlaylistDialog(host)
    importer.location_input.setText(_playlist(tmp_path, TWO))
    _run(app, importer)

    dialog = dialogs.PlaylistsDialog(host)
    assert dialog.playlist_list.count() == 1
    assert dialog.playlist_list.item(0).text() == 'news — Built-in Server'
    dialog.refresh_btn.click()
    _wait_job(app, dialog)
    assert dialog.status_label.text() == 'The channels from news are up to date.'

    monkeypatch.setattr(
        dialogs.QMessageBox, 'question', lambda *_args, **_kwargs: dialogs.QMessageBox.StandardButton.Yes
    )
    dialog.remove_btn.click()
    _wait_job(app, dialog)
    assert removed == ['news']
    assert host.stored == []
    assert dialog.status_label.text() == 'Removed the channels from news.'
    assert dialog.playlist_list.isHidden()
    assert not dialog.empty_label.isHidden()


def test_one_job_per_playlist(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    location = _playlist(tmp_path, TWO)
    host.busy.add(('builtin', location))
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.location_input.setText(location)
    _run(app, dialog)
    assert dialog.status_label.text() == dialogs.BUSY
    assert dialog.import_btn.isEnabled()


def test_missing_guide_does_not_fail_the_import(app, tmp_path, monkeypatch):
    def broken(*_args):
        raise dialogs.PlaylistError('The program guide could not be loaded.')

    monkeypatch.setattr(dialogs, 'load_guide', broken)
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    text = TWO.replace('#EXTM3U', '#EXTM3U x-tvg-url="http://127.0.0.1:1/guide.xml"')
    dialog.location_input.setText(_playlist(tmp_path, text))
    _run(app, dialog)
    assert dialog.status_label.text() == 'Added 2 channels from news. The program guide could not be loaded.'


def test_job_says_when_only_the_stream_test_is_left(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    source = PlaylistSource('news', _playlist(tmp_path, TWO), 'builtin')
    job = dialogs.PlaylistJob(host, source, BUILTIN)
    events = []
    job.checking.connect(lambda: events.append('checking'))
    job.finished.connect(lambda message, _skipped: events.append(message))
    job.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and job.is_running():
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert events == ['checking', 'Updated the channels from news: 2 added.']


def test_closing_while_checking_hands_the_job_to_the_host(app, tmp_path, monkeypatch):
    class SlowScan(FakeAdmin):
        def create_mux(self, network_uuid, conf):
            uuid = super().create_mux(network_uuid, conf)
            self.muxes[uuid].update(scan_state=1, scan_result=0)
            return uuid

    monkeypatch.setattr(dialogs, 'TvhAdmin', SlowScan)
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.location_input.setText(_playlist(tmp_path, TWO))
    dialog.import_btn.click()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and dialog.hint_label.isHidden():
        app.processEvents()
        time.sleep(0.02)
    assert dialog.hint_label.text() == dialogs.CHECK_HINT
    assert dialog.close_btn.text() == 'Close'

    job = dialog._job
    finished = []
    dialog.close_btn.click()
    assert host.kept == [job]
    assert dialog._job is None
    assert job.is_checking()
    job.finished.connect(lambda message, _skipped: finished.append(message))
    for mux in FakeAdmin.servers[BUILTIN['url']]['muxes'].values():
        mux.update(scan_state=0, scan_result=1)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and job.is_running():
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert finished == ['Added 2 channels from news.']


def _finish(app, job, timeout=10):
    events = []
    job.checking.connect(lambda: events.append('checking'))
    job.finished.connect(lambda message, _skipped: events.append(message))
    job.failed.connect(lambda message: events.append(('failed', message)))
    job.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and job.is_running():
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    return events


def test_import_without_hiding_skips_the_check(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    host.hide_dead = False
    source = PlaylistSource('news', _playlist(tmp_path, TWO), 'builtin')
    events = _finish(app, dialogs.PlaylistJob(host, source, BUILTIN, first_import=True))
    assert events == ['Added 2 channels from news.']


def test_check_and_show_every_channel_of_an_imported_playlist(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    host.hide_dead = False
    source = PlaylistSource('news', _playlist(tmp_path, TWO), 'builtin')
    _finish(app, dialogs.PlaylistJob(host, source, BUILTIN, first_import=True))
    source = PlaylistSource.from_dict(host.stored[-1])

    check = dialogs.PlaylistJob(host, source, BUILTIN, action=dialogs.PlaylistJob.CHECK)
    assert _finish(app, check) == ['checking', 'Checked the channels from news: all 2 are working.']
    show = dialogs.PlaylistJob(host, source, BUILTIN, action=dialogs.PlaylistJob.SHOW)
    assert _finish(app, show) == ['Every channel from news is shown.']

    gone = PlaylistSource('old', source.location, 'builtin', network_uuid='nope')
    check = dialogs.PlaylistJob(host, gone, BUILTIN, action=dialogs.PlaylistJob.CHECK)
    assert _finish(app, check) == [('failed', dialogs.NETWORK_GONE)]


def test_settings_toggle_hiding_and_check_now(app):
    from tvhplayer.settings_dialog import SettingsDialog

    class Host:
        def __init__(self):
            self.hide = True
            self.jobs = []
            self.checks = 0

        def hides_dead_channels(self):
            return self.hide

        def plays_on_start(self):
            return False

        def set_plays_on_start(self, on):
            self.play = on

        def set_hides_dead_channels(self, on):
            self.hide = on

        def check_playlist_channels(self):
            self.checks += 1
            return list(self.jobs)

        def playlist_checks(self):
            return self.jobs

    host = Host()
    dialog = SettingsDialog(host)
    assert dialog.hide_check.isChecked()
    assert not dialog.play_check.isChecked()
    dialog.play_check.click()
    assert host.play is True
    dialog.hide_check.click()
    assert host.hide is False
    assert 'shown again' in dialog.status_label.text()
    dialog.check_btn.click()
    assert host.checks == 1
    assert dialog.status_label.text() == 'There are no imported playlists to check.'


def test_a_playlist_being_updated_cannot_be_refreshed(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    importer = dialogs.ImportPlaylistDialog(host)
    location = _playlist(tmp_path, TWO)
    importer.location_input.setText(location)
    _run(app, importer)

    # An update started elsewhere, such as the refresh at startup.
    host.busy.add(('builtin', location))
    dialog = dialogs.PlaylistsDialog(host)
    assert dialog.playlist_list.item(0).text() == 'news — Built-in Server — updating…'
    assert not dialog.refresh_btn.isEnabled()
    assert dialog.remove_btn.isEnabled()

    host.busy.clear()
    dialog._follow_busy()
    assert dialog.playlist_list.item(0).text() == 'news — Built-in Server'
    assert dialog.refresh_btn.isEnabled()
    assert dialog.remove_btn.isEnabled()


def test_removing_a_playlist_being_updated_stops_the_update_first(app, tmp_path, monkeypatch):
    class SlowScan(FakeAdmin):
        def create_mux(self, network_uuid, conf):
            uuid = super().create_mux(network_uuid, conf)
            self.muxes[uuid].update(scan_state=1, scan_result=0)
            return uuid

    monkeypatch.setattr(dialogs, 'TvhAdmin', SlowScan)
    removed = []
    monkeypatch.setattr(dialogs, 'remove_playlist', lambda _admin, source: removed.append(source.network_uuid))
    questions = []

    def yes(_parent, _title, text, *_args):
        questions.append(text)
        return dialogs.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(dialogs.QMessageBox, 'question', yes)
    host = FakeHost([BUILTIN], current=BUILTIN)
    source = PlaylistSource('news', _playlist(tmp_path, TWO), 'builtin')
    job = dialogs.PlaylistJob(host, source, BUILTIN, first_import=True)
    host.kept.append(job)
    job.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not job.is_checking():
        app.processEvents()
        time.sleep(0.02)

    dialog = dialogs.PlaylistsDialog(host)
    assert dialog.remove_btn.isEnabled()
    assert not dialog.refresh_btn.isEnabled()
    dialog.remove_btn.click()
    assert questions == ['news is being updated. Stop the update and remove its channels?']
    assert dialog.status_label.text() == 'Stopping the update…'
    assert not dialog.remove_btn.isEnabled()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not removed:
        app.processEvents()
        time.sleep(0.02)
    _wait_job(app, dialog)
    assert removed == ['net']
    assert host.stored == []
    assert dialog.status_label.text() == 'Removed the channels from news.'

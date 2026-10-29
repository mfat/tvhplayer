import os
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

import tvhplayer.playlist_dialogs as dialogs  # noqa: E402
from tvhplayer.core.errors import TvhAuthError  # noqa: E402
from tvhplayer.core.playlist_sync import PlaylistSource, same_source, source_key  # noqa: E402

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

    def has_network_bouquets(self, _network_uuid):
        return True

    def list_muxes(self, _network_uuid, fields=None):
        return [dict(conf, uuid=uuid) for uuid, conf in self.muxes.items()]

    def create_mux(self, _network_uuid, conf):
        uuid = f'm{len(self.muxes) + 1}'
        # The server's scan of these streams has already passed.
        self.muxes[uuid] = dict(conf, scan_state=0, scan_result=1)
        return uuid

    def list_services(self, _mux_uuids, fields=None):
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
        self.synced = []

    def import_targets(self):
        return list(self.targets)

    def playlist_sources(self):
        return [PlaylistSource.from_dict(data) for data in self.stored]

    def store_playlist_source(self, data):
        source = PlaylistSource.from_dict(data)
        self.stored = [
            item for item in self.stored
            if not same_source(PlaylistSource.from_dict(item), source)
        ] + [data]

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

    def after_playlist_sync(self, server, source, guide_url, result):
        self.synced.append((server.get('url'), source.name, guide_url, result.added))


    def claim_playlist(self, source):
        key = source_key(source)
        if key in self.busy:
            return False
        self.busy.add(key)
        return True

    def release_playlist(self, source):
        self.busy.discard(source_key(source))

    def is_playlist_busy(self, source):
        return source_key(source) in self.busy

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
    # The channel choice is a modal window; keep every channel.
    monkeypatch.setattr(dialogs, 'ask_to_choose', lambda *_args: True)
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


def test_xtream_provider_and_headers_reuse_the_playlist_pipeline(app, monkeypatch):
    from tvhplayer.core.playlist import parse_playlist

    loaded = []

    def load(location, cancelled=None, headers=None):
        loaded.append((location, headers))
        playlist = parse_playlist(TWO)
        playlist.max_connections = 1
        return playlist

    monkeypatch.setattr(dialogs, 'load_xtream', load)
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.source_type_combo.setCurrentIndex(1)
    dialog.location_input.setText('https://provider.example:8080')
    dialog.username_input.setText('user')
    dialog.password_input.setText('secret')
    dialog.user_agent_input.setText('Provider App')
    dialog.headers_input.setText('{"Referer":"https://provider.example/"}')
    _run(app, dialog)
    assert loaded == [(
        'https://provider.example:8080/get.php?username=user&password=secret',
        {'Referer': 'https://provider.example/', 'User-Agent': 'Provider App'},
    )]
    source = PlaylistSource.from_dict(host.stored[-1])
    assert source.source_type == 'xc'
    assert source.request_headers['User-Agent'] == 'Provider App'


def test_xtream_settings_rotate_password_without_duplicating_source(app, monkeypatch):
    from tvhplayer.core.playlist import parse_playlist

    loaded = []

    def load(location, cancelled=None, headers=None):
        loaded.append((location, headers))
        playlist = parse_playlist(TWO)
        playlist.max_connections = 1
        return playlist

    monkeypatch.setattr(dialogs, 'load_xtream', load)
    original = PlaylistSource(
        'Provider',
        'https://provider.example/get.php?username=user&password=old',
        'builtin',
        source_type='xc',
        request_headers={'User-Agent': 'Old App'},
    )
    host = FakeHost([BUILTIN], current=BUILTIN)
    host.stored = [original.to_dict()]
    dialog = dialogs.ImportPlaylistDialog(host, server=BUILTIN, source=original)
    assert dialog.windowTitle() == 'Edit Source'
    assert not dialog.source_type_combo.isEnabled()
    assert not dialog.username_input.isEnabled()
    assert not dialog.server_combo.isEnabled()
    dialog.password_input.setText('new')
    dialog.user_agent_input.setText('New App')
    _run(app, dialog)
    assert loaded == [(
        'https://provider.example/get.php?username=user&password=new',
        {'User-Agent': 'New App'},
    )]
    assert len(host.stored) == 1
    saved = PlaylistSource.from_dict(host.stored[0])
    assert saved.location.endswith('username=user&password=new')
    assert saved.request_headers == {'User-Agent': 'New App'}


def test_import_rejects_unsafe_provider_headers(app):
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.location_input.setText('https://provider.example/list.m3u')
    dialog.headers_input.setText('{"X-Test":"ok\\nInjected: yes"}')
    dialog.import_btn.click()
    assert dialog._job is None
    assert dialog.status_label.text().startswith('Other headers must be a JSON object')


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
    assert dialog.playlist_list.item(0).text() == 'news'
    assert dialog.health_label.text().startswith('Stream health: 2 working')
    assert dialog.health_btn.isEnabled()
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
    host.busy.add(source_key(PlaylistSource('news', location, 'builtin')))
    dialog = dialogs.ImportPlaylistDialog(host)
    dialog.location_input.setText(location)
    _run(app, dialog)
    assert dialog.status_label.text() == dialogs.BUSY
    assert dialog.import_btn.isEnabled()


def test_missing_guide_does_not_fail_the_import(app, tmp_path, monkeypatch):
    def broken(*_args):
        raise dialogs.PlaylistError('The program guide could not be loaded.')

    monkeypatch.setattr(dialogs, 'load_guide', broken)
    host = FakeHost([OTHER], current=OTHER)
    dialog = dialogs.ImportPlaylistDialog(host)
    text = TWO.replace('#EXTM3U', '#EXTM3U x-tvg-url="http://127.0.0.1:1/guide.xml"')
    dialog.location_input.setText(_playlist(tmp_path, text))
    _run(app, dialog)
    assert dialog.status_label.text() == 'Added 2 channels from news. The program guide could not be loaded.'


def test_a_server_on_this_computer_gets_the_guide_as_a_guide_source(app, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(dialogs, 'load_guide', lambda *args: sent.append(args))
    host = FakeHost([BUILTIN], current=BUILTIN)
    dialog = dialogs.ImportPlaylistDialog(host)
    text = TWO.replace('#EXTM3U', '#EXTM3U x-tvg-url="http://127.0.0.1:1/guide.xml"')
    dialog.location_input.setText(_playlist(tmp_path, text))
    _run(app, dialog)
    assert dialog.status_label.text() == 'Added 2 channels from news.'
    assert sent == []
    assert host.synced == [(BUILTIN['url'], 'news', 'http://127.0.0.1:1/guide.xml', 2)]


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


def test_an_import_stops_waiting_for_the_test_once_hiding_is_off(app, tmp_path, monkeypatch):
    class SlowScan(FakeAdmin):
        def create_mux(self, network_uuid, conf):
            uuid = super().create_mux(network_uuid, conf)
            self.muxes[uuid].update(scan_state=1, scan_result=0)
            return uuid

    monkeypatch.setattr(dialogs, 'TvhAdmin', SlowScan)
    host = FakeHost([BUILTIN], current=BUILTIN)
    source = PlaylistSource('news', _playlist(tmp_path, TWO), 'builtin')
    job = dialogs.PlaylistJob(host, source, BUILTIN, first_import=True)
    job.checking.connect(lambda: setattr(host, 'hide_dead', False))
    events = _finish(app, job)
    assert events == ['checking', 'Added 2 channels from news. Channels that were not checked yet stay in the list.']


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


def test_settings_toggle_hiding_and_check_now(app, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

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

        def uses_live_resize(self):
            return getattr(self, 'live_resize', False)

        def set_uses_live_resize(self, on):
            self.live_resize = on

        def shows_channel_logos(self):
            return True

        def set_shows_channel_logos(self, on):
            self.logos = on

        def set_hides_dead_channels(self, on):
            self.hide = on

        def local_recording_dir(self):
            return '/videos'

        def set_local_recording_dir(self, folder):
            self.folder = folder

        def recording_format(self):
            return 'ts'

        def set_recording_format(self, fmt):
            self.format = fmt

        def recording_ffmpeg_options(self):
            return getattr(self, 'options', '')

        def set_recording_ffmpeg_options(self, text):
            self.options = text

        def converts_after_recording(self):
            return False

        def set_converts_after_recording(self, on):
            self.convert = on

        def convert_options(self):
            return getattr(self, 'convert_text', '') or '-c:v libx264 -crf 18'

        def set_convert_options(self, text):
            self.convert_text = text

        def deletes_converted_original(self):
            return False

        def set_deletes_converted_original(self, on):
            self.delete = on

        builtin = object()
        padding = (2, 5)
        space = 5
        picon_job = None
        picons = 0

        def picon_count(self):
            return self.picons

        def download_picons(self):
            from PyQt6.QtCore import QObject, pyqtSignal

            class Job(QObject):
                progress = pyqtSignal(int, int)
                finished = pyqtSignal(object, str)

            self.picon_job = Job()
            return self.picon_job

        def remove_picons(self):
            self.picons = 0

        def recording_padding(self):
            return self.padding

        def set_recording_padding(self, early, late):
            self.padding = (early, late)

        def low_space_gb(self):
            return self.space

        def set_low_space_gb(self, gb):
            self.space = gb

        def stays_awake_for_scheduled(self):
            return True

        def set_stays_awake_for_scheduled(self, on):
            self.awake = on

        def conversion_problem(self, text):
            return 'This ffmpeg has no nope encoder.' if 'nope' in text else ''

        def check_playlist_channels(self):
            self.checks += 1
            return list(self.jobs)

        def playlist_checks(self):
            return self.jobs

        def playlist_sources(self):
            return list(self.sources)

        def server_for_playlist(self, source):
            return None if source.server == 'http://gone' else {'url': source.server}

        sources = []

        def theme_choice(self):
            return 'TVHplayer'

        def set_theme_choice(self, theme):
            self.theme = theme

        def running_theme(self):
            return 'TVHplayer'

        def color_scheme_choice(self):
            return 'system'

        def set_color_scheme_choice(self, mode):
            self.color_scheme = mode

        accent = 'sage'
        window_color = 'default'

        def accent_choice(self):
            return self.accent

        def set_accent_choice(self, key):
            self.accent = key

        def window_color_choice(self):
            return self.window_color

        def set_window_color_choice(self, key):
            self.window_color = key

        title_bar = False

        def can_draw_title_bar(self):
            return True

        def draws_title_bar(self):
            return self.title_bar

        def set_draws_title_bar(self, on):
            self.title_bar = on

        updates = True
        update_checks = 0

        def checks_for_updates(self):
            return self.updates

        def set_checks_for_updates(self, on):
            self.updates = on

        def check_for_updates(self):
            self.update_checks += 1

    host = Host()
    dialog = SettingsDialog(host)
    assert dialog.nav.item(dialog.nav.count() - 1).text() == 'Updates'
    assert dialog.updates_check.isChecked()
    dialog.updates_check.click()
    assert host.updates is False
    dialog.updates_btn.click()
    assert host.update_checks == 1
    # Appearance comes first and Settings opens on it.
    assert dialog.nav.item(0).text() == 'Appearance'
    assert dialog.pages.currentWidget().widget().findChild(QLabel, 'pageTitle').text() == 'Appearance'
    assert dialog.title_bar_check.isVisibleTo(dialog)
    assert dialog._title_bar_row.description.text() == 'Takes effect the next time TVHplayer starts.'
    assert dialog.title_bar_check.accessibleDescription() == 'Takes effect the next time TVHplayer starts.'
    assert not dialog.title_bar_check.isChecked()
    dialog.title_bar_check.click()
    assert host.title_bar is True
    assert dialog.accent_combo.currentData() == 'sage'
    assert not dialog.accent_combo.itemIcon(0).isNull()
    dialog.accent_combo.setCurrentIndex(dialog.accent_combo.findData('ocean'))
    QApplication.processEvents()
    assert host.accent == 'ocean'
    assert dialog.window_color_combo.currentData() == 'default'
    assert dialog.window_color_combo.isVisibleTo(dialog)
    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData('Fusion'))
    QApplication.processEvents()
    assert host.theme == 'Fusion'
    assert not dialog.window_color_combo.isVisibleTo(dialog)
    assert dialog.hide_check.isChecked()
    assert not dialog.play_check.isChecked()
    dialog.play_check.click()
    assert host.play is True
    assert not dialog.live_resize_check.isChecked()
    dialog.live_resize_check.click()
    assert host.live_resize is True
    assert dialog.folder_edit.text() == '/videos'
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *_a: '/recordings')
    dialog.folder_btn.click()
    assert host.folder == '/recordings'
    assert dialog.folder_edit.text() == '/recordings'
    assert dialog.format_combo.currentData() == 'ts'
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData('mp4'))
    assert host.format == 'mp4'
    assert dialog.awake_check.isChecked()
    assert dialog.logos_check.isChecked()
    dialog.logos_check.click()
    assert host.logos is False
    assert dialog.picon_btn.text() == '&Download Picons'
    assert not dialog.picon_remove_btn.isEnabled()
    dialog.picon_btn.click()
    assert not dialog.picon_btn.isEnabled()
    host.picon_job.progress.emit(5, 10)
    assert dialog.picon_progress.value() == 5
    host.picons = 24054
    host.picon_job.finished.emit(None, '')
    assert dialog.picon_btn.text() == 'Up&date Picons'
    assert dialog.picon_status.text().startswith('24,054 picons are ready.')
    dialog.picon_remove_btn.click()
    assert dialog.picon_status.text() == 'No picons downloaded.'
    assert (dialog.early_spin.value(), dialog.late_spin.value(), dialog.space_spin.value()) == (2, 5, 5)
    dialog.late_spin.setValue(10)
    dialog.space_spin.setValue(0)
    assert dialog.space_spin.text() == 'Never'
    dialog._padding_edited()
    dialog._space_edited()
    assert host.padding == (2, 10)
    assert host.space == 0
    dialog.awake_check.click()
    assert host.awake is False
    dialog.options_edit.setText('-metadata "title=unclosed')
    dialog._options_edited()
    assert not hasattr(host, 'options')
    assert 'not saved' in dialog.options_status.text()
    dialog.options_edit.setText(' -b:a 128k ')
    dialog._options_edited()
    assert host.options == '-b:a 128k'
    assert dialog.options_status.text() == ''

    assert not dialog.delete_check.isEnabled()
    dialog.convert_check.click()
    assert host.convert is True and dialog.delete_check.isEnabled()
    dialog.delete_check.click()
    assert host.delete is True
    dialog.convert_edit.setText('-c:v nope')
    dialog._convert_edited()
    assert host.convert_text == '-c:v nope'
    assert 'no nope encoder' in dialog.convert_status.text()
    dialog.convert_edit.setText('')
    dialog._convert_edited()
    assert host.convert_text == ''
    assert dialog.convert_edit.text() == '-c:v libx264 -crf 18'
    assert dialog.convert_status.text() == ''
    dialog.hide_check.click()
    assert host.hide is False
    assert 'shown again' in dialog.status_label.text()
    dialog.check_btn.click()
    assert host.checks == 1
    assert dialog.status_label.text() == 'There are no imported playlists to check.'
    host.sources = [PlaylistSource('old', 'http://x/old.m3u', 'http://gone')]
    dialog.check_btn.click()
    assert dialog.status_label.text() == 'The server of 1 playlist was removed, so it cannot be checked.'


def test_a_playlist_being_updated_cannot_be_refreshed(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    importer = dialogs.ImportPlaylistDialog(host)
    location = _playlist(tmp_path, TWO)
    importer.location_input.setText(location)
    _run(app, importer)

    # An update started elsewhere, such as the refresh at startup.
    host.busy.add(source_key(PlaylistSource('news', location, 'builtin')))
    dialog = dialogs.PlaylistsDialog(host)
    assert dialog.playlist_list.item(0).text() == 'news — updating…'
    assert not dialog.refresh_btn.isEnabled()
    assert dialog.remove_btn.isEnabled()

    host.busy.clear()
    dialog._follow_busy()
    assert dialog.playlist_list.item(0).text() == 'news'
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


def test_playlists_dialog_lists_servers_and_their_playlists(app, tmp_path):
    other = {'name': 'Living Room', 'url': 'http://10.0.0.2:9981'}
    host = FakeHost([BUILTIN, other], current=other)
    host.stored = [
        PlaylistSource('news', str(tmp_path / 'news.m3u'), 'builtin').to_dict(),
        PlaylistSource('films', str(tmp_path / 'films.m3u'), 'http://10.0.0.2:9981').to_dict(),
        PlaylistSource('old', str(tmp_path / 'old.m3u'), 'http://gone:9981').to_dict(),
    ]
    dialog = dialogs.PlaylistsDialog(host)
    servers = [dialog.server_list.item(row).text() for row in range(dialog.server_list.count())]
    assert servers == ['Built-in Server (1)', 'Living Room (1)', 'Removed servers (1)']
    # The server in use is selected first.
    assert dialog.server_list.currentRow() == 1
    assert dialog.title_label.text() == 'Living Room'
    assert dialog.playlist_list.item(0).text() == 'films'
    assert dialog.import_btn.isEnabled()

    dialog.server_list.setCurrentRow(2)
    assert dialog.playlist_list.item(0).text() == 'old'
    assert not dialog.refresh_btn.isEnabled()
    assert not dialog.import_btn.isEnabled()
    dialog.remove_btn.click()
    servers = [dialog.server_list.item(row).text() for row in range(dialog.server_list.count())]
    assert servers == ['Built-in Server (1)', 'Living Room (1)']

    dialog.server_list.setCurrentRow(0)
    assert dialog.playlist_list.item(0).text() == 'news'
    host.stored = []
    dialog._load()
    assert dialog.server_list.currentRow() == 0
    assert dialog.playlist_list.isHidden()
    assert not dialog.empty_label.isHidden()


GROUPS = (
    '#EXTM3U\n'
    '#EXTINF:-1 group-title="News",A\nhttp://x/a.ts\n'
    '#EXTINF:-1 group-title="News",B\nhttp://x/b.ts\n'
    '#EXTINF:-1 group-title="Sport",C\nhttp://x/c.ts\n'
)


def _grouped_plans():
    from tvhplayer.core.playlist import parse_playlist, plan_channels

    plans, _skipped = plan_channels(parse_playlist(GROUPS), '/usr/bin/ffmpeg', 'news')
    return plans


def test_choose_window_selects_groups_and_searches(app):
    plans = _grouped_plans()
    source = PlaylistSource('news', '/tmp/news.m3u', 'builtin', left_out=['name:B'])
    dialog = dialogs.ChooseChannelsDialog(plans, source)
    assert [dialog.tree.topLevelItem(i).text(0) for i in range(2)] == ['News (2)', 'Sport (1)']
    assert dialog.chosen_keys() == ['name:A', 'name:C']
    assert dialog.count_label.text() == '2 of 3 selected'

    dialog.search_input.setText('sport')
    assert dialog.tree.topLevelItem(0).isHidden()
    dialog.none_btn.click()
    assert dialog.chosen_keys() == ['name:A']
    dialog.search_input.setText('')
    dialog.none_btn.click()
    assert dialog.chosen_keys() == []
    assert not dialog.ok_btn.isEnabled()
    dialog.all_btn.click()
    assert dialog.chosen_keys() == ['name:A', 'name:B', 'name:C']
    dialog.tree.topLevelItem(1).setCheckState(0, dialogs.Qt.CheckState.Unchecked)
    app.processEvents()
    assert dialog.chosen_keys() == ['name:A', 'name:B']
    assert dialog.count_label.text() == '2 of 3 selected'


def test_job_adds_only_the_chosen_channels(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    host.hide_dead = False
    source = PlaylistSource('news', _playlist(tmp_path, GROUPS), 'builtin')

    def keep_news(plans, chosen):
        dialogs.choose_channels(chosen, plans, ['name:A', 'name:B'])
        return True

    events = _finish(app, dialogs.PlaylistJob(host, source, BUILTIN, first_import=True, choose=keep_news))
    assert events == ['Added 2 channels from news.']
    stored = PlaylistSource.from_dict(host.stored[-1])
    assert stored.chosen_groups == ['News']
    assert sorted(stored.muxes) == ['name:A', 'name:B']

    # A refresh keeps the choice without asking.
    _finish(app, dialogs.PlaylistJob(host, stored, BUILTIN))
    assert sorted(PlaylistSource.from_dict(host.stored[-1]).muxes) == ['name:A', 'name:B']


def test_cancelling_the_choice_changes_nothing(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    source = PlaylistSource('news', _playlist(tmp_path, GROUPS), 'builtin')
    job = dialogs.PlaylistJob(host, source, BUILTIN, first_import=True, choose=lambda _plans, _source: False)
    assert _finish(app, job) == [('failed', 'Nothing was changed.')]
    assert host.stored == []
    assert FakeAdmin.servers.get(BUILTIN['url'], {}).get('muxes', {}) == {}


def test_refresh_says_when_no_chosen_channel_is_left(app, tmp_path):
    host = FakeHost([BUILTIN], current=BUILTIN)
    source = PlaylistSource('news', _playlist(tmp_path, GROUPS), 'builtin', chosen_groups=['Films'])
    assert _finish(app, dialogs.PlaylistJob(host, source, BUILTIN)) == [('failed', dialogs.NONE_CHOSEN)]

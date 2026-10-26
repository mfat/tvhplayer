import functools
import http.server
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request

import pytest

from tvhplayer.core.builtin_server import find_bundled_binary
from tvhplayer.core.errors import PlaylistError, TvhAuthError, TvhConnectionError
from tvhplayer.core.playlist import SkippedEntry, parse_playlist, plan_channels
from tvhplayer.core.playlist_sync import (
    MAX_STREAMS,
    NETWORK_CONF,
    NOT_WORKING,
    PlaylistSource,
    SyncResult,
    check_message,
    error_message,
    ffmpeg_for_server,
    find_source,
    mux_conf,
    remove_playlist,
    result_message,
    server_key,
    show_all_channels,
    sync_playlist,
    unique_name,
    wait_for_checks,
)
from tvhplayer.core.tvh_admin import TvhAdmin
from tvhplayer.core.xmltv import load_guide


class FakeAdmin:
    """New and rescanned muxes stay pending until ``finish_scans``."""

    def __init__(self, dead=()):
        self.networks = {}
        self.muxes = {}
        self.services = {}
        self.saved = []
        self.deleted = []
        self.mapped = []
        self.scanned = []
        self.orphans_cleared = []
        self.dead = set(dead)
        self._next = 0

    def _uuid(self):
        self._next += 1
        return f'u{self._next}'

    def check_admin(self):
        pass

    def network_exists(self, uuid):
        return uuid in self.networks

    def create_network(self, conf):
        uuid = self._uuid()
        self.networks[uuid] = conf
        return uuid

    def update_network(self, uuid, conf):
        self.networks[uuid].update(conf)

    def list_muxes(self, network_uuid, fields=None):
        return [dict(row, uuid=uuid) for uuid, row in self.muxes.items() if row['network_uuid'] == network_uuid]

    def create_mux(self, network_uuid, conf):
        uuid = self._uuid()
        self.muxes[uuid] = dict(conf, network_uuid=network_uuid, name=conf['iptv_sname'], scan_state=1, scan_result=0)
        self.services[f's{uuid}'] = {'multiplex_uuid': uuid, 'enabled': True}
        return uuid

    def list_services(self, mux_uuids, fields=None):
        return [dict(row, uuid=uuid) for uuid, row in self.services.items() if row['multiplex_uuid'] in mux_uuids]

    def scan_network(self, network_uuid):
        self.scanned.append(network_uuid)
        for row in self.muxes.values():
            if row['network_uuid'] == network_uuid:
                row['scan_state'] = 1

    def scan_muxes(self, uuids):
        self.scanned.extend(uuids)
        for uuid in uuids:
            self.muxes[uuid]['scan_state'] = 1

    def finish_scans(self):
        for row in self.muxes.values():
            if row['scan_state']:
                row['scan_state'] = 0
                row['scan_result'] = 2 if row['name'] in self.dead else 1

    def visible(self):
        """Names whose channel the bouquet would show."""
        return sorted(
            self.muxes[row['multiplex_uuid']]['name'] for row in self.services.values()
            if row['enabled'] and row['multiplex_uuid'] in self.muxes
        )

    def save(self, nodes):
        self.saved.extend(nodes)
        for node in nodes:
            target = self.services if node['uuid'] in self.services else self.muxes
            target[node['uuid']].update({k: v for k, v in node.items() if k != 'uuid'})

    def delete(self, uuids):
        self.deleted.extend(uuids)
        for uuid in uuids:
            self.muxes.pop(uuid, None)
            self.networks.pop(uuid, None)

    def delete_unused_tags(self, names):
        self.tags_deleted = list(names)

    def map_network_bouquet(self, network_uuid):
        self.mapped.append(network_uuid)

    def delete_orphan_channels(self, network_uuid):
        self.orphans_cleared.append(network_uuid)
        return 0

    def delete_network(self, network_uuid):
        self.delete([uuid for uuid, row in self.muxes.items() if row['network_uuid'] == network_uuid])
        self.delete([network_uuid])


def _plans(text, ffmpeg='/usr/bin/ffmpeg'):
    plans, _skipped = plan_channels(parse_playlist(text), ffmpeg, 'List')
    return plans


FIRST = (
    '#EXTM3U\n'
    '#EXTINF:-1 tvg-id="a" tvg-chno="1",A\nhttp://x/a.ts\n'
    '#EXTINF:-1 tvg-id="b" tvg-chno="2",B\nhttp://x/b.ts\n'
)


def test_first_import_creates_network_and_muxes():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    checkpoints = []
    result = sync_playlist(admin, source, _plans(FIRST), checkpoint=lambda: checkpoints.append(dict(source.muxes)))
    assert (result.added, result.updated, result.removed) == (2, 0, 0)
    network = admin.networks[source.network_uuid]
    assert network['networkname'] == 'List'
    assert network['service_sid'] == NETWORK_CONF['service_sid'] == 1
    assert set(source.muxes) == {'id:a', 'id:b'}
    assert checkpoints[-1] == source.muxes
    assert admin.mapped == [source.network_uuid]
    mux = admin.muxes[source.muxes['id:a']]
    assert mux['iptv_sname'] == 'A'
    assert mux['channel_number'] == '1'
    assert mux['epg'] == 0


def test_refresh_edits_in_place_adds_and_removes():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    a_uuid = source.muxes['id:a']
    second = (
        '#EXTM3U\n'
        '#EXTINF:-1 tvg-id="a" tvg-chno="1",A renamed\nhttp://x/a-new.ts\n'
        '#EXTINF:-1 tvg-id="c",C\nhttp://x/c.ts\n'
    )
    result = sync_playlist(admin, source, _plans(second))
    assert (result.added, result.updated, result.removed) == (1, 1, 1)
    assert source.muxes['id:a'] == a_uuid
    assert admin.muxes[a_uuid]['iptv_sname'] == 'A renamed'
    assert 'http://x/a-new.ts' in admin.muxes[a_uuid]['iptv_url']
    assert set(source.muxes) == {'id:a', 'id:c'}


def test_unchanged_refresh_writes_nothing():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    admin.finish_scans()
    wait_for_checks(admin, source, SyncResult())
    admin.saved.clear()
    result = sync_playlist(admin, source, _plans(FIRST))
    assert (result.added, result.updated, result.removed) == (0, 0, 0)
    assert admin.saved == []


def test_channels_that_fail_the_scan_are_hidden():
    admin = FakeAdmin(dead={'B'})
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    result = sync_playlist(admin, source, _plans(FIRST))
    # Not tested yet, so shown.
    assert admin.visible() == ['A', 'B']
    seen = []
    wait_for_checks(admin, source, result, progress=lambda *args: seen.append(args), sleep=lambda _s: admin.finish_scans())
    assert admin.visible() == ['A']
    assert seen == [(0, 2), (2, 2)]
    assert (result.working, result.not_working) == (1, ['B'])
    assert result.skipped[-1] == SkippedEntry('B', NOT_WORKING)

    # A refresh of an unchanged playlist tests nothing.
    admin.dead = {'A'}
    result = sync_playlist(admin, source, _plans(FIRST))
    assert admin.scanned == []
    assert admin.visible() == ['A']

    # Checking the playlist tests every stream again; B kept its mux and comes back once it works.
    admin.scan_network(source.network_uuid)
    wait_for_checks(admin, source, result, sleep=lambda _s: admin.finish_scans())
    assert admin.visible() == ['B']
    assert len(admin.muxes) == 2


def test_a_refresh_tests_only_streams_whose_address_changed():
    admin = FakeAdmin(dead={'B'})
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    admin.finish_scans()
    wait_for_checks(admin, source, SyncResult())
    assert admin.visible() == ['A']
    renamed = FIRST.replace(',A\n', ',A renamed\n')
    assert renamed != FIRST
    sync_playlist(admin, source, _plans(renamed))
    assert admin.scanned == []
    moved = FIRST.replace('http://x/b.ts', 'http://x/b-new.ts')
    assert moved != FIRST
    admin.dead = set()
    result = sync_playlist(admin, source, _plans(moved))
    assert admin.scanned == [source.muxes['id:b']]
    wait_for_checks(admin, source, result, sleep=lambda _s: admin.finish_scans())
    assert admin.visible() == ['A', 'B']


def test_a_refresh_hides_channels_already_known_to_be_dead():
    admin = FakeAdmin(dead={'B'})
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    admin.finish_scans()
    # An older version left every service on, whatever the scan said.
    for row in admin.services.values():
        row['enabled'] = True
    sync_playlist(admin, source, _plans(FIRST))
    assert admin.visible() == ['A']


def test_stopping_the_check_keeps_unchecked_channels_shown():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    result = sync_playlist(admin, source, _plans(FIRST))
    wait_for_checks(admin, source, result, cancelled=lambda: True, sleep=lambda _s: None)
    assert result.check_stopped
    assert admin.visible() == ['A', 'B']


def test_without_checks_a_refresh_tests_nothing_and_hides_nothing():
    admin = FakeAdmin(dead={'B'})
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    result = sync_playlist(admin, source, _plans(FIRST))
    wait_for_checks(admin, source, result, sleep=lambda _s: admin.finish_scans())
    assert admin.visible() == ['A']
    sync_playlist(admin, source, _plans(FIRST), check=False)
    assert admin.scanned == []
    assert admin.visible() == ['A']
    assert show_all_channels(admin, source) == 1
    assert admin.visible() == ['A', 'B']
    assert show_all_channels(admin, PlaylistSource('Gone', 'http://x/gone.m3u', 'builtin')) == 0


def test_lost_muxes_are_adopted_by_address_and_duplicates_deleted():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    plans = _plans(FIRST)
    sync_playlist(admin, source, plans)
    # An older version lost the map and imported the playlist a second time.
    for plan in plans:
        admin.create_mux(source.network_uuid, mux_conf(plan))
    a_uuid = source.muxes['id:a']
    source.muxes = {'id:b': source.muxes['id:b']}
    result = sync_playlist(admin, source, plans)
    assert len(admin.muxes) == 2
    assert (result.added, result.removed) == (0, 2)
    assert source.muxes['id:a'] == a_uuid
    assert set(source.muxes.values()) == set(admin.muxes)


def test_refresh_switches_the_network_back_on():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/list.m3u', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    admin.networks[source.network_uuid]['enabled'] = False
    admin.networks[source.network_uuid]['max_streams'] = 2
    sync_playlist(admin, source, _plans(FIRST))
    assert admin.networks[source.network_uuid]['enabled'] is True
    assert admin.networks[source.network_uuid]['max_timeout'] == 30
    assert admin.networks[source.network_uuid]['max_streams'] == MAX_STREAMS
    assert admin.orphans_cleared == [source.network_uuid]


def test_network_streams_follow_the_account_limit():
    admin = FakeAdmin()
    source = PlaylistSource('List', 'http://x/get.php', 'builtin', max_streams=1)
    sync_playlist(admin, source, _plans(FIRST))
    assert admin.networks[source.network_uuid]['max_streams'] == 1
    source.max_streams = 20
    sync_playlist(admin, source, _plans(FIRST))
    assert admin.networks[source.network_uuid]['max_streams'] == MAX_STREAMS
    assert PlaylistSource.from_dict(dict(source.to_dict(), max_streams='2')).max_streams == 2
    assert PlaylistSource.from_dict({'max_streams': 'x'}).max_streams == 0


def test_server_values_compare_equal_to_planned_values():
    plan = _plans(FIRST)[0]
    conf = mux_conf(plan)
    row = dict(conf, channel_number=1, enabled=True)
    row.pop('iptv_icon')
    row.pop('iptv_tags')
    admin = FakeAdmin()
    source = PlaylistSource('List', '', 'builtin', network_uuid='n', muxes={plan.key: 'm'})
    admin.networks['n'] = {}
    admin.muxes['m'] = dict(row, network_uuid='n')
    sync_playlist(admin, source, [plan])
    assert admin.saved == []


def test_missing_network_is_created_again():
    admin = FakeAdmin()
    source = PlaylistSource('List', '', 'builtin', network_uuid='gone', muxes={'id:a': 'old'})
    result = sync_playlist(admin, source, _plans(FIRST))
    assert source.network_uuid != 'gone'
    assert result.added == 2
    assert 'old' not in source.muxes.values()


def test_cancel_keeps_saved_map_matching_server():
    admin = FakeAdmin()
    source = PlaylistSource('List', '', 'builtin')
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) > 1

    result = sync_playlist(admin, source, _plans(FIRST), cancelled=cancelled)
    assert result.cancelled
    assert result.added == 1
    assert set(source.muxes.values()) == set(admin.muxes)


def test_empty_playlist_never_removes_channels():
    admin = FakeAdmin()
    source = PlaylistSource('List', '', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    with pytest.raises(PlaylistError):
        sync_playlist(admin, source, [])
    assert len(admin.muxes) == 2


def test_remove_playlist_deletes_network():
    admin = FakeAdmin()
    source = PlaylistSource('List', '', 'builtin')
    sync_playlist(admin, source, _plans(FIRST))
    source.tags = ['News']
    remove_playlist(admin, source)
    assert admin.networks == {}
    assert admin.muxes == {}
    assert admin.tags_deleted == ['News']
    assert source.network_uuid == ''
    assert source.tags == []


def test_source_round_trips_and_names_its_server():
    source = PlaylistSource('L', '/tmp/a.m3u', 'builtin', 'n', {'id:a': 'm'}, True, ['News'])
    assert PlaylistSource.from_dict(source.to_dict()) == source
    assert server_key({'builtin': True, 'url': 'http://127.0.0.1:1'}) == 'builtin'
    assert server_key({'url': 'http://tv.lan:9981/'}) == 'http://tv.lan:9981'


# End to end against a real Tvheadend.

FFMPEG = shutil.which('ffmpeg')
TVHEADEND = find_bundled_binary()


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _api(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/{path}', timeout=5) as response:
        return json.loads(response.read().decode('utf-8'), strict=False)


def _wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.3)
    return predicate()


@pytest.fixture
def media(tmp_path):
    """A test-pattern MPEG-TS whose program number is 1234, served over HTTP."""
    folder = tmp_path / 'media'
    folder.mkdir()
    subprocess.run(
        [FFMPEG, '-nostdin', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=25',
         '-f', 'lavfi', '-i', 'sine', '-t', '20', '-c:v', 'mpeg2video', '-c:a', 'mp2',
         '-mpegts_service_id', '1234', '-f', 'mpegts', str(folder / 'a.ts')],
        check=True,
    )
    shutil.copy(folder / 'a.ts', folder / 'a2.ts')
    start = time.strftime('%Y%m%d%H%M%S', time.gmtime(time.time() - 600))
    stop = time.strftime('%Y%m%d%H%M%S', time.gmtime(time.time() + 3600))
    (folder / 'guide.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?><tv>'
        '<channel id="a"><display-name>Pattern</display-name></channel>'
        f'<programme start="{start} +0000" stop="{stop} +0000" channel="a"><title>Test Card</title></programme>'
        '</tv>\n',
        encoding='utf-8',
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


@pytest.fixture
def tvheadend():
    # Short config path: the XMLTV socket inside it must fit a Unix socket name.
    config = tempfile.mkdtemp(prefix='tvh', dir='/tmp')
    http_port, htsp_port = _free_port(), _free_port()
    process = subprocess.Popen(
        [str(TVHEADEND), '-c', config, '-C', '--noacl', '-B', '--bindaddr', '127.0.0.1',
         '--http_port', str(http_port), '--htsp_port', str(htsp_port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def ready():
        try:
            return _api(http_port, 'serverinfo')
        except OSError:
            return None

    try:
        assert _wait(ready, 60), 'Tvheadend did not start'
        yield http_port
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(config, ignore_errors=True)


def _channels(port):
    return {row['name']: row for row in _api(port, 'channel/grid?limit=1000')['entries']}


def _first_bytes(port, channel_uuid, size=188 * 200):
    url = f'http://127.0.0.1:{port}/stream/channel/{channel_uuid}?profile=pass'
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read(size)


@pytest.mark.skipif(not (FFMPEG and TVHEADEND), reason='needs ffmpeg and a Tvheadend build')
def test_import_plays_refreshes_and_removes(tvheadend, media):
    port = tvheadend
    text = (
        '#EXTM3U\n'
        f'#EXTINF:-1 tvg-id="a" tvg-chno="7" group-title="News",Pattern\n{media}/a.ts\n'
        '#EXTINF:-1 tvg-chno="8",Tone\n'
        f'pipe://{FFMPEG} -re -f lavfi -i sine -f lavfi -i testsrc -c:v mpeg2video -c:a mp2 -f mpegts pipe:1\n'
        f'#EXTINF:-1 tvg-chno="9",Gone\n{media}/missing.ts\n'
    )
    plans, skipped = plan_channels(parse_playlist(text), FFMPEG, 'Test', allow_commands=True)
    assert skipped == []
    source = PlaylistSource('Test', 'test.m3u', 'builtin')
    with TvhAdmin({'url': f'http://127.0.0.1:{port}'}) as admin:
        result = sync_playlist(admin, source, plans)
        assert result.added == 3
        wait_for_checks(admin, source, result, sleep=time.sleep)
        assert (result.working, result.not_working, result.check_stopped) == (2, ['Gone'], False)

        channels = _wait(lambda: len(_channels(port)) == 2 and _channels(port))
        server = {'url': f'http://127.0.0.1:{port}', 'builtin': True}
        assert load_guide(admin, server, f'{media}/guide.xml', new_channels=True)
        events = _wait(lambda: _api(port, 'epg/events/grid?limit=10')['entries'])
        assert [(row['channelName'], row['title']) for row in events] == [('Pattern', 'Test Card')]
        assert channels['Pattern']['number'] == 7
        pattern_uuid = channels['Pattern']['uuid']
        data = _first_bytes(port, pattern_uuid)
        assert len(data) == 188 * 200 and data[0] == 0x47
        data = _first_bytes(port, channels['Tone']['uuid'])
        assert len(data) == 188 * 200 and data[0] == 0x47

        # A switched-off network hides its muxes from the default grid and is never scanned.
        admin.save([{'uuid': source.network_uuid, 'enabled': False}])
        source.muxes = {}
        result = sync_playlist(admin, source, plans)
        assert (result.added, result.removed) == (0, 0)
        assert _api(port, 'mpegts/mux/grid?limit=100')['total'] == 3
        wait_for_checks(admin, source, result)
        assert (result.working, result.not_working) == (2, ['Gone'])
        assert sorted(_channels(port)) == ['Pattern', 'Tone']

        text = (
            '#EXTM3U\n'
            f'#EXTINF:-1 tvg-id="a" tvg-chno="7",Pattern renamed\n{media}/a2.ts\n'
        )
        plans, _skipped = plan_channels(parse_playlist(text), FFMPEG, 'Test')
        result = sync_playlist(admin, source, plans)
        assert (result.added, result.updated, result.removed) == (0, 1, 2)
        wait_for_checks(admin, source, result)
        assert (result.working, result.not_working) == (1, [])
        channels = _wait(lambda: list(_channels(port)) == ['Pattern renamed'] and _channels(port))
        assert channels['Pattern renamed']['uuid'] == pattern_uuid

        remove_playlist(admin, source)
        assert _wait(lambda: _channels(port) == {})
        tags = [row['name'] for row in _api(port, 'channeltag/grid')['entries']]
        assert not any(name.startswith('*** ') for name in tags)
        assert 'News' not in tags


def test_ffmpeg_location_per_server():
    assert ffmpeg_for_server({'builtin': True}, which=lambda _name: '/app/bin/ffmpeg') == '/app/bin/ffmpeg'
    with pytest.raises(PlaylistError):
        ffmpeg_for_server({'builtin': True}, which=lambda _name: None)
    assert ffmpeg_for_server({'url': 'http://tv.lan:9981'}) == '/usr/bin/ffmpeg'


def test_sources_are_found_and_named_per_server():
    sources = [PlaylistSource('ir', 'http://a/ir.m3u', 'builtin')]
    assert find_source(sources, ' http://a/ir.m3u ', 'builtin') is sources[0]
    assert find_source(sources, 'http://a/ir.m3u', 'http://tv.lan') is None
    assert unique_name(sources, 'ir', 'builtin') == 'ir 2'
    assert unique_name(sources, 'ir', 'http://tv.lan') == 'ir'


def test_check_messages_read_naturally():
    assert check_message('ir', SyncResult(working=3)) == 'Checked the channels from ir: all 3 are working.'
    assert check_message('ir', SyncResult(working=3, not_working=['b'])) == (
        'Checked the channels from ir: 3 working. 1 is hidden because it is not working.'
    )
    assert check_message('ir', SyncResult(working=1, not_working=['b', 'c'], check_stopped=True)) == (
        'Stopped checking the channels from ir. 2 are hidden because they are not working.'
    )


def test_result_messages_read_naturally():
    assert result_message('ir', SyncResult(added=1, working=1), True) == 'Added 1 channel from ir.'
    assert result_message('ir', SyncResult(added=1, films=244693), True) == (
        'Added 1 channel from ir. 244,693 films and series episodes were left out '
        'because TVHplayer imports only TV channels.'
    )
    assert result_message('ir', SyncResult(films=2), False) == 'The channels from ir are up to date.'
    assert result_message('ir', SyncResult(added=3, working=1, not_working=['b', 'c']), True) == (
        'Added 3 channels from ir. 2 are hidden because they are not working.'
    )
    assert result_message('ir', SyncResult(not_working=['b']), False) == (
        'The channels from ir are up to date. 1 channel is not working right now and is hidden.'
    )
    assert result_message('ir', SyncResult(added=2, check_stopped=True), True) == (
        'Added 2 channels from ir. Channels that were not checked yet stay in the list.'
    )
    assert result_message('ir', SyncResult(added=3, removed=2), False) == (
        'Updated the channels from ir: 3 added, 2 removed.'
    )
    assert result_message('ir', SyncResult(updated=4), False) == 'The channels from ir are up to date.'
    skipped = [SkippedEntry('a', 'x'), SkippedEntry('b', 'y')]
    assert result_message('ir', SyncResult(added=5, working=5, skipped=skipped), True) == (
        'Added 5 channels from ir. 2 entries could not be added.'
    )
    assert result_message('ir', SyncResult(added=2, cancelled=True), True) == (
        'Import stopped. 2 channels from ir were added.'
    )


def test_error_messages_are_plain():
    assert 'administrator' in error_message(TvhAuthError('HTTP 403'), 'Home')
    assert error_message(TvhConnectionError('refused'), 'Home').startswith('Could not reach Home.')
    assert error_message(PlaylistError('This file is not a TV playlist.'), 'Home') == (
        'This file is not a TV playlist.'
    )

import os
import re
import socket
import tempfile
import threading

import pytest

from tvhplayer.core.guide_feeds import GuideCache, GuideError, GuideSource, format_time
from tvhplayer.core.guide_match import Choice
from tvhplayer.core.guide_update import GuideReport, NO_SOCKET, server_channels, update_server_guide

NOW = 1_800_000_000


@pytest.fixture
def xmltv_socket():
    folder = tempfile.mkdtemp(prefix='tvhg', dir='/tmp')
    path = os.path.join(folder, 'xmltv.sock')
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(4)
    received = []
    done = threading.Event()

    def serve():
        while True:
            try:
                conn, _addr = listener.accept()
            except OSError:
                return
            with conn:
                chunks = []
                while True:
                    data = conn.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
                received.append(b''.join(chunks).decode('utf-8'))
                done.set()

    threading.Thread(target=serve, daemon=True).start()
    yield path, received
    listener.close()
    os.unlink(path)
    os.rmdir(folder)


class FakeAdmin:
    """A server with IPTV channels whose guide channels appear once a guide arrives."""

    def __init__(self, socket_path, received):
        self.socket_path = socket_path
        self.received = received
        self.saved = []
        self.deleted = []
        self.kept_after_import = False
        self.guide_rows = [
            {'uuid': 'old', 'id': 'tvhplayer.gone', 'modid': 'xmltv'},
            {'uuid': 'eit', 'id': 'BBCOne.uk', 'modid': '/usr/bin/tv_grab_uk'},
            {'uuid': 'test', 'id': 'Radio.uk', 'modid': 'xmltv'},
        ]
        self.channels = [
            {'uuid': 'c1', 'name': 'BBC One', 'services': ['s1'], 'epggrab': ['eit']},
            {'uuid': 'c2', 'name': 'BBC One HD', 'services': ['s2'], 'epggrab': []},
            {'uuid': 'c3', 'name': 'Dave', 'services': ['s3'], 'epggrab': []},
            {'uuid': 'c4', 'name': 'Radio', 'services': [], 'epggrab': ['old', 'test', 'eit']},
        ]

    def list_all_muxes(self):
        return [{'uuid': 'm1', 'iptv_epgid': 'BBCOne.uk'}, {'uuid': 'm2', 'iptv_epgid': 'BBCOne.uk@HD'},
                {'uuid': 'm3', 'iptv_epgid': ''}]

    def list_services_all(self):
        return [{'uuid': 's1', 'multiplex_uuid': 'm1'}, {'uuid': 's2', 'multiplex_uuid': 'm2'},
                {'uuid': 's3', 'multiplex_uuid': 'm3'}]

    def list_channels(self):
        return [dict(row) for row in self.channels]

    def list_guide_channels(self):
        rows = list(self.guide_rows)
        known = {row['id'] for row in rows}
        for text in self.received:
            for channel_id in re.findall(r'<channel id="([^"]+)"', text):
                if channel_id not in known:
                    known.add(channel_id)
                    rows.append({'uuid': 'ec-' + channel_id.split('.', 1)[1], 'id': channel_id, 'modid': 'xmltv'})
        return rows

    def enable_xmltv_socket(self):
        return self.socket_path

    def keep_guide_after_import(self):
        self.kept_after_import = True

    def save(self, nodes):
        self.saved.extend(nodes)
        for node in nodes:
            for row in self.channels:
                if row['uuid'] == node['uuid']:
                    row['epggrab'] = node['epggrab']

    def delete(self, uuids):
        self.deleted.extend(uuids)
        self.guide_rows = [row for row in self.guide_rows if row['uuid'] not in uuids]


def _guide(tmp_path):
    path = tmp_path / 'guide.xml'
    programmes = ''.join(
        f'<programme start="{format_time(NOW + h * 3600)}" stop="{format_time(NOW + (h + 1) * 3600)}" '
        f'channel="BBCOne.uk"><title>Show {h}</title></programme>'
        for h in range(48)
    )
    path.write_text(f'<tv><channel id="BBCOne.uk"><display-name>BBC One</display-name></channel>{programmes}</tv>')
    return str(path)


def _wait(received, count):
    for _ in range(200):
        if len(received) >= count:
            return
        threading.Event().wait(0.01)


def test_channels_carry_their_services_guide_ids(xmltv_socket):
    admin = FakeAdmin(*xmltv_socket)
    channels = {channel.uuid: channel for channel in server_channels(admin)}
    assert channels['c1'].epg_ids == ('BBCOne.uk',)
    assert channels['c2'].epg_ids == ('BBCOne.uk@HD',)
    assert channels['c3'].epg_ids == ()
    assert channels['c1'].epggrab == ('eit',)


def test_guide_is_sent_linked_and_sent_again(xmltv_socket, tmp_path):
    path, received = xmltv_socket
    admin = FakeAdmin(path, received)
    location = _guide(tmp_path)
    source = GuideSource(location, 'builtin')
    cache = GuideCache(tmp_path / 'cache')
    report = update_server_guide(
        admin, {'builtin': True}, cache, [source], {'c3': Choice(location, 'BBCOne.uk', 60)},
        now=NOW, sleep=lambda _s: None,
    )
    _wait(received, 2)
    assert len(received) == 2
    assert received[0] == received[1]
    assert 'channel="tvhplayer.c3"' in received[0]
    assert f'start="{format_time(NOW + 3600)}" stop="{format_time(NOW + 7200)}" channel="tvhplayer.c3"' in received[0]
    links = {node['uuid']: node['epggrab'] for node in admin.saved}
    # Each channel takes only its own guide channel. The radio, which has no
    # guide, loses ours and an old one sent through the socket, not another grabber's.
    assert links == {'c1': ['ec-c1'], 'c2': ['ec-c2'], 'c3': ['ec-c3'], 'c4': ['eit']}
    assert admin.deleted == ['old', 'test']
    assert admin.kept_after_import
    assert (report.channels, report.covered, report.unmatched) == (4, 3, ['Radio'])
    assert report.until == NOW + 49 * 3600
    assert source.updated == NOW and source.error == ''
    assert report.message(NOW) == 'TV guide loaded for 3 of 4 channels, up to 2 days ahead.'

    # Once linked, the guide is sent once.
    admin.saved.clear()
    update_server_guide(admin, {'builtin': True}, cache, [source], {'c3': Choice(location, 'BBCOne.uk', 60)},
                        now=NOW + 60, sleep=lambda _s: None)
    _wait(received, 3)
    assert len(received) == 3
    assert admin.saved == []


def test_a_failed_download_uses_the_last_copy(xmltv_socket, tmp_path):
    path, received = xmltv_socket
    admin = FakeAdmin(path, received)
    location = _guide(tmp_path)
    cache = GuideCache(tmp_path / 'cache')
    source = GuideSource(location, 'builtin', name='Mine')
    update_server_guide(admin, {'builtin': True}, cache, [source], {}, now=NOW, sleep=lambda _s: None)
    os.unlink(location)
    report = update_server_guide(admin, {'builtin': True}, cache, [source], {}, force=True, now=NOW + 10,
                                 sleep=lambda _s: None)
    assert report.failed == {'Mine': 'Could not open the guide file.'}
    assert source.error == 'Could not open the guide file.' and source.updated == NOW
    assert report.covered == 2
    assert report.message(NOW).endswith('Could not update Mine; the last copy was used.')


def test_other_servers_keep_what_others_sent(xmltv_socket, tmp_path):
    path, received = xmltv_socket
    admin = FakeAdmin(path, received)
    location = _guide(tmp_path)
    update_server_guide(admin, {'url': 'http://127.0.0.1:9981'}, GuideCache(tmp_path / 'cache'),
                        [GuideSource(location, 'http://127.0.0.1:9981')], {}, now=NOW, sleep=lambda _s: None)
    links = {node['uuid']: node['epggrab'] for node in admin.saved}
    assert links['c4'] == ['test', 'eit']
    assert admin.deleted == ['old']
    assert not admin.kept_after_import


def test_a_remote_socket_is_refused(xmltv_socket, tmp_path):
    path, received = xmltv_socket
    admin = FakeAdmin(path, received)
    with pytest.raises(GuideError) as info:
        update_server_guide(admin, {'url': 'http://tv.lan:9981'}, GuideCache(tmp_path), [], {}, now=NOW)
    assert str(info.value) == NO_SOCKET


def test_report_without_channels():
    assert GuideReport().message(NOW) == 'The server has no channels for the TV guide.'
    assert GuideReport(channels=5).message(NOW) == 'TV guide loaded for 0 of 5 channels.'


# --- Against a real Tvheadend build ------------------------------------------

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

from tvhplayer.core.builtin_server import find_bundled_binary  # noqa: E402
from tvhplayer.core.tvh_admin import TvhAdmin  # noqa: E402

TVHEADEND = find_bundled_binary()


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _api(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/{path}', timeout=5) as response:
        return json.loads(response.read().decode('utf-8'), strict=False)


def _until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.3)
    return predicate()


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
        assert _until(ready, 60), 'Tvheadend did not start'
        yield http_port
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(config, ignore_errors=True)


@pytest.mark.skipif(not TVHEADEND, reason='needs a Tvheadend build')
def test_real_server_shows_the_guide_on_every_channel(tvheadend, tmp_path):
    port = tvheadend
    server = {'url': f'http://127.0.0.1:{port}', 'builtin': True}
    now = int(time.time()) // 3600 * 3600
    location = tmp_path / 'guide.xml'
    location.write_text(
        '<tv><channel id="BBCOne.uk"><display-name>BBC One</display-name></channel>'
        + ''.join(
            f'<programme start="{format_time(now + h * 3600)}" stop="{format_time(now + (h + 1) * 3600)}" '
            f'channel="BBCOne.uk"><title>Show {h}</title></programme>'
            for h in range(6)
        )
        + '</tv>'
    )
    with TvhAdmin(server) as admin:
        network = admin.create_network({'networkname': 'Test', 'service_sid': 1, 'skipinitscan': True,
                                        'bouquet': True, 'epgauto_default': True})
        for number, (name, epg_id) in enumerate((('BBC One', 'BBCOne.uk'), ('BBC One HD', 'BBCOne.uk@HD'),
                                                 ('Other +1', ''))):
            admin.create_mux(network, {'enabled': 1, 'iptv_url': f'http://127.0.0.1:1/{number}',
                                       'iptv_sname': name, 'iptv_muxname': name, 'iptv_epgid': epg_id, 'epg': 0})
        admin.map_network_bouquet(network)
        channels = _until(lambda: len(admin.list_channels()) == 3 and {c['name']: c['uuid'] for c in admin.list_channels()})
        source = GuideSource(str(location), 'builtin')
        choices = {channels['Other +1']: Choice(str(location), 'BBCOne.uk', 60)}
        report = update_server_guide(admin, server, GuideCache(tmp_path / 'cache'), [source], choices)
        assert (report.channels, report.covered) == (3, 3)

        def titles():
            rows = _api(port, 'epg/events/grid?limit=100')['entries']
            found = {}
            for row in rows:
                found.setdefault(row['channelName'], []).append((row['start'] - now) // 3600)
            return len(found) == 3 and found

        found = _until(titles)
        assert sorted(found['BBC One']) == sorted(found['BBC One HD'])
        assert min(found['Other +1']) == min(found['BBC One']) + 1

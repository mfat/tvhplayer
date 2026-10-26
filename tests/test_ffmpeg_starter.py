import functools
import http.server
import json
import os
import subprocess
import sys
import threading

import pytest

from tvhplayer.core import builtin_server
from tvhplayer.core.ffmpeg_starter import (
    DEFAULT_USER_AGENT,
    best_variant,
    install_starter,
    request_headers,
    with_best_variant,
)
from tvhplayer.core.playlist import ffmpeg_command, tvh_split
from tvhplayer.core.playlist_sync import ffmpeg_for_server, retarget_commands

MASTER = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-STREAM-INF:BANDWIDTH=3625413,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
02.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=6128079,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
01.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=9000000,URI="iframes.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=793450,RESOLUTION=427x240
05.m3u8
"""


def test_the_highest_bandwidth_quality_is_picked():
    assert best_variant(MASTER, 'https://cdn.tv/AJM/index.m3u8') == 'https://cdn.tv/AJM/01.m3u8'


def test_a_quality_with_separate_sound_keeps_the_whole_list():
    text = (
        '#EXTM3U\n'
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="English",URI="audio/en.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=2000000,AUDIO="aac"\nvideo/hd.m3u8\n'
    )
    assert best_variant(text, 'https://cdn.tv/index.m3u8') is None
    # Sound inside the quality's own stream needs nothing else.
    inline = text.replace(',URI="audio/en.m3u8"', '')
    assert best_variant(inline, 'https://cdn.tv/index.m3u8') == 'https://cdn.tv/video/hd.m3u8'


@pytest.mark.parametrize('text', [
    '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.0,\nseg1.ts\n',
    'not a playlist',
    '',
])
def test_anything_but_a_list_of_qualities_is_left_alone(text):
    assert best_variant(text, 'https://cdn.tv/index.m3u8') is None


def test_a_quality_that_is_not_on_the_web_is_not_used():
    assert best_variant('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nfile:///etc/passwd\n', 'https://cdn.tv/i.m3u8') is None


def test_only_the_input_address_is_replaced_and_its_headers_are_sent():
    command = ffmpeg_command(
        '/usr/bin/ffmpeg', 'https://cdn.tv/index.m3u8',
        {'User-Agent': 'Agent/1', 'Referer': 'https://site.tv/'}, 'News', 'news',
    )
    args = tvh_split(command[7:])[1:]
    asked = []

    def fetch(url, headers):
        asked.append((url, headers))
        return MASTER, 'https://cdn.tv/redirected/index.m3u8'

    result = with_best_variant(args, fetch)
    assert asked == [('https://cdn.tv/index.m3u8', {'User-Agent': 'Agent/1', 'Referer': 'https://site.tv/'})]
    assert result[result.index('-i') + 1] == 'https://cdn.tv/redirected/01.m3u8'
    assert [arg for arg in result if 'm3u8' not in arg] == [arg for arg in args if 'm3u8' not in arg]


def test_ffmpeg_default_user_agent_is_sent_when_the_playlist_names_none():
    assert request_headers(['-reconnect', '1']) == {'User-Agent': DEFAULT_USER_AGENT}


def test_inputs_that_are_not_web_addresses_are_not_fetched():
    def fetch(*_args):
        raise AssertionError('fetched')

    args = ['-nostdin', '-i', 'pipe:0', '-c', 'copy', 'pipe:1']
    assert with_best_variant(args, fetch) == args
    assert with_best_variant(['-i', 'a', '-i', 'b'], fetch) == ['-i', 'a', '-i', 'b']


class _Lists(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = MASTER.encode() if self.path == '/index.m3u8' else b'\x47' * 188
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def web():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Lists)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


@pytest.fixture
def fake_ffmpeg(tmp_path):
    path = tmp_path / 'real' / 'ffmpeg'
    path.parent.mkdir()
    path.write_text('#!/bin/sh\nfor arg in "$@"; do echo "$arg"; done\n')
    os.chmod(path, 0o755)
    return path


def test_the_installed_stand_in_runs_ffmpeg_on_the_best_quality(tmp_path, web, fake_ffmpeg):
    starter = install_starter(str(fake_ffmpeg), tmp_path / 'bin' / 'ffmpeg')
    args = ['-nostdin', '-i', f'{web}/index.m3u8', '-c', 'copy', '-f', 'mpegts', 'pipe:1']
    output = subprocess.run([starter] + args, capture_output=True, text=True, timeout=20, env={})
    assert output.stdout.split('\n')[:-1] == ['-nostdin', '-i', f'{web}/01.m3u8', '-c', 'copy', '-f', 'mpegts', 'pipe:1']


def test_the_stand_in_passes_the_command_on_when_the_list_cannot_be_read(tmp_path, web, fake_ffmpeg):
    starter = install_starter(str(fake_ffmpeg), tmp_path / 'bin' / 'ffmpeg')
    for url in (f'{web}/stream.ts', 'http://127.0.0.1:1/index.m3u8'):
        args = ['-i', url, 'pipe:1']
        output = subprocess.run([starter] + args, capture_output=True, text=True, timeout=20)
        assert output.stdout.split('\n')[:-1] == args


def test_the_stand_in_is_written_once_and_only_where_python_can_run_it(tmp_path, monkeypatch):
    path = tmp_path / 'bin' / 'ffmpeg'
    assert install_starter('/usr/bin/ffmpeg', path) == str(path)
    assert path.read_text().startswith(f'#!{sys.executable} -I\n')
    assert os.access(path, os.X_OK)
    written = path.stat().st_mtime_ns
    assert install_starter('/usr/bin/ffmpeg', path) == str(path)
    assert path.stat().st_mtime_ns == written
    assert install_starter('/usr/bin/ffmpeg', path, python='/opt/my python/bin/python3') is None
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert install_starter('/usr/bin/ffmpeg', path) is None


def test_the_built_in_server_gets_the_stand_in_and_others_get_ffmpeg():
    builtin = {'builtin': True}
    assert ffmpeg_for_server(builtin, which=lambda _name: '/usr/bin/ffmpeg', starter=lambda _path: '/data/bin/ffmpeg') == '/data/bin/ffmpeg'
    assert ffmpeg_for_server(builtin, which=lambda _name: '/usr/bin/ffmpeg', starter=lambda _path: None) == '/usr/bin/ffmpeg'
    assert ffmpeg_for_server({'url': 'http://tv.lan:9981'}, starter=lambda _path: '/data/bin/ffmpeg') == '/usr/bin/ffmpeg'


def test_existing_channels_are_switched_to_the_stand_in_and_back():
    old = ffmpeg_command('/usr/bin/ffmpeg', 'https://cdn.tv/index.m3u8', name='News')
    new = ffmpeg_command('/home/me/.local/share/tvhplayer/bin/ffmpeg', 'https://cdn.tv/index.m3u8', name='News')
    rows = [
        {'uuid': 'a', 'iptv_url': old},
        {'uuid': 'b', 'iptv_url': new},
        {'uuid': 'c', 'iptv_url': 'https://cdn.tv/direct.m3u8'},
        {'uuid': 'd', 'iptv_url': 'pipe:///bin/sh -c "x | /usr/bin/ffmpeg -i pipe:0"'},
    ]
    stand_in = '/home/me/.local/share/tvhplayer/bin/ffmpeg'
    assert retarget_commands(rows, stand_in, ['/usr/bin/ffmpeg']) == [{'uuid': 'a', 'iptv_url': new}]
    assert retarget_commands(rows, '/usr/bin/ffmpeg', [stand_in]) == [{'uuid': 'b', 'iptv_url': old}]


def test_server_start_switches_its_channels(monkeypatch):
    rows = [{'uuid': 'a', 'iptv_url': ffmpeg_command('/usr/bin/ffmpeg', 'https://cdn.tv/i.m3u8')}]
    saved = []
    monkeypatch.setattr(builtin_server, '_post_json', lambda *_args, **_kw: {'entries': rows})
    monkeypatch.setattr(builtin_server, '_post', lambda _port, _path, form, *_args, **_kw: saved.append(json.loads(form['node'])) or True)
    changed = builtin_server.use_ffmpeg_starter(
        9981, which=lambda _name: '/usr/bin/ffmpeg', starter=lambda _path: '/data/bin/ffmpeg',
    )
    assert changed == 1
    assert saved == [[{'uuid': 'a', 'iptv_url': ffmpeg_command('/data/bin/ffmpeg', 'https://cdn.tv/i.m3u8')}]]
    monkeypatch.setattr(builtin_server, '_post_json', lambda *_args, **_kw: None)
    assert builtin_server.use_ffmpeg_starter(
        9981, which=lambda _name: '/usr/bin/ffmpeg', starter=lambda _path: '/data/bin/ffmpeg',
    ) == -1

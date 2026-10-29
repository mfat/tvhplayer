import shlex
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from tvhplayer.core.errors import PlaylistError
from tvhplayer.core.playlist import (
    FILE_FAILED,
    MAX_PIPE_ARGS,
    NOT_A_PLAYLIST,
    ONLY_FILMS,
    STOPPED,
    decode_playlist,
    ffmpeg_command,
    ffmpeg_input,
    load_playlist,
    load_xtream,
    parse_playlist,
    plan_channels,
    playlist_commands,
    playlist_name,
    shell_command,
    tvh_split,
    xtream_connections,
    xtream_playlist_url,
)

KODI = (
    '﻿#EXTM3U x-tvg-url="http://example.com/guide.xml.gz"\r\n'
    '#EXTINF:-1 tvg-id="news.ir" tvg-chno="10" tvg-logo="http://example.com/n.png" '
    'group-title="News;Iran",IRINN, live\r\n'
    '#EXTVLCOPT:http-referrer=https://telewebion.net/\r\n'
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0\r\n'
    'https://ncdn.telewebion.net/irinn2/live/playlist.m3u8\r\n'
    '\r\n'
    '#EXTGRP:Music\r\n'
    '#EXTINF:0,Radio One\r\n'
    'http://radio.example/one.mp3|User-Agent=VLC%2F3.0&!X-Token=abc\r\n'
    '#EXTINF:0 tvh-tags="Kids|Cartoons" tvh-chnum="5.1",Toons\r\n'
    'udp://@239.0.0.1:1234\r\n'
)


def test_parse_reads_kodi_dialect():
    playlist = parse_playlist(decode_playlist(KODI.encode('utf-8')))
    assert playlist.guide_url == 'http://example.com/guide.xml.gz'
    news, radio, toons = playlist.entries
    assert news.name == 'IRINN, live'
    assert news.url == 'https://ncdn.telewebion.net/irinn2/live/playlist.m3u8'
    assert news.headers == {'Referer': 'https://telewebion.net/', 'User-Agent': 'Mozilla/5.0'}
    assert news.groups == ['News', 'Iran']
    assert news.attrs['tvg-logo'] == 'http://example.com/n.png'
    assert radio.url == 'http://radio.example/one.mp3'
    assert radio.headers == {'User-Agent': 'VLC/3.0', 'X-Token': 'abc'}
    assert radio.groups == ['Music']
    assert toons.groups == ['Kids', 'Cartoons']


def test_parse_rejects_other_files():
    for text in ('', '<html></html>', 'http://example.com/a.ts\n'):
        with pytest.raises(PlaylistError) as info:
            parse_playlist(text)
        assert str(info.value) == NOT_A_PLAYLIST


def test_parse_skips_xtream_films_and_series():
    playlist = parse_playlist(
        '#EXTM3U\n'
        '#EXTINF:-1 group-title="News",News\n'
        'http://xtream.example:80/user/pass/1371\n'
        '#EXTINF:-1 group-title="Films",A Film\n'
        'http://xtream.example:80/movie/user/pass/835957.mkv\n'
        '#EXTINF:-1 group-title="Series",A Show S01E01\n'
        'http://xtream.example:80/series/user/pass/832464.mp4\n'
        '#EXTINF:-1,Movie Channel\n'
        'http://example.com/movie/live.m3u8\n'
    )
    assert [entry.name for entry in playlist.entries] == ['News', 'Movie Channel']
    assert playlist.entries[0].groups == ['News']
    assert playlist.films == 2


def test_playlist_of_only_films_says_so():
    with pytest.raises(PlaylistError) as info:
        parse_playlist('#EXTM3U\n#EXTINF:-1,A Film\nhttp://xtream.example/movie/u/p/1.mkv\n')
    assert str(info.value) == ONLY_FILMS


def test_decode_falls_back_to_latin1():
    assert decode_playlist('#EXTM3U\n#EXTINF:0,Café\n'.encode('latin-1')).endswith('Café\n')


def test_entry_without_extinf_is_named_from_its_address():
    playlist = parse_playlist('#EXTM3U\nhttp://example.com/live/sport.ts\n')
    assert playlist.entries[0].name == 'sport.ts'


def test_ffmpeg_command_round_trips_through_tvheadend_splitting():
    name = 'Das "Erste" \\ HD'
    command = ffmpeg_command(
        '/usr/bin/ffmpeg',
        'https://example.com/live.m3u8?a=1&b=2',
        {'User-Agent': 'Mozilla/5.0 (X11)', 'Referer': 'https://example.com/'},
        name,
        'My list',
    )
    assert command.startswith('pipe:///usr/bin/ffmpeg ')
    args = tvh_split(command[7:])
    assert len(args) < MAX_PIPE_ARGS
    assert args[args.index('-user_agent') + 1] == 'Mozilla/5.0 (X11)'
    assert args[args.index('-headers') + 1] == 'Referer: https://example.com/\r\n'
    assert args[args.index('-i') + 1] == 'https://example.com/live.m3u8?a=1&b=2'
    assert f'service_name={name}' in args
    assert 'service_provider=My list' in args
    assert args[args.index('-mpegts_service_id') + 1] == '1'
    assert args[-1] == 'pipe:1'


def test_reconnect_options_only_for_web_streams():
    assert '-reconnect' in ffmpeg_command('ffmpeg', 'http://example.com/a.ts')
    udp = ffmpeg_command('ffmpeg', 'udp://@239.0.0.1:1234', {'Referer': 'x'})
    assert '-reconnect' not in udp
    assert '-headers' not in udp


def test_ffmpeg_input_reads_tvheadend_style_playlist_lines():
    user = (
        'ffmpeg -loglevel fatal -headers "Referer: https://telewebion.net/" '
        '-i https://ncdn.telewebion.net/irinn2/live/playlist.m3u8 -c copy -f mpegts pipe:1'
    )
    assert ffmpeg_input(user) == (
        'https://ncdn.telewebion.net/irinn2/live/playlist.m3u8',
        {'Referer': 'https://telewebion.net/'},
    )
    kodinerds = (
        'ffmpeg -loglevel fatal -i https://example.com/master.m3u8 -vcodec copy -acodec copy '
        '-metadata service_name=Das\\ Erste\\ HD -f mpegts pipe:1'
    )
    assert ffmpeg_input(kodinerds) == ('https://example.com/master.m3u8', {})
    assert ffmpeg_input('/usr/bin/ffmpeg -user_agent UA -i http://a/b -f mpegts pipe:1') == (
        'http://a/b',
        {'User-Agent': 'UA'},
    )
    assert ffmpeg_input('streamlink --stdout https://example.com best') is None
    assert ffmpeg_input('ffmpeg -i pipe:0 -f mpegts pipe:1') is None
    assert ffmpeg_input('ffmpeg -i http://a -i http://b -f mpegts pipe:1') is None


def test_tvh_split_matches_spawn_parse_args():
    assert tvh_split('a  "b c" d\\ e \'f"g\' \\n') == ['a', 'b c', 'd e', 'f"g', '\n']
    assert tvh_split('x ""') == ['x']
    assert len(tvh_split(' '.join(['a'] * 100))) == MAX_PIPE_ARGS


def _plans(text, **kwargs):
    return plan_channels(parse_playlist(text), '/usr/bin/ffmpeg', 'List', **kwargs)


def test_plan_receives_every_entry_through_ffmpeg():
    plans, skipped = _plans(KODI)
    assert skipped == []
    assert [plan.name for plan in plans] == ['IRINN, live', 'Radio One', 'Toons']
    for plan in plans:
        assert plan.url.startswith('pipe:///usr/bin/ffmpeg ')
    news = plans[0]
    assert news.number == '10'
    assert news.icon == 'http://example.com/n.png'
    assert news.epg_id == 'news.ir'
    assert news.key == 'id:news.ir'
    assert plans[2].number == '5.1'
    assert plans[2].key == 'name:Toons'


def test_plan_rebuilds_playlist_ffmpeg_lines():
    text = (
        '#EXTM3U\n#EXTINF:-1,IRINN\n'
        'pipe://ffmpeg -loglevel fatal -re -headers "Referer: https://telewebion.net/" '
        '-i https://ncdn.telewebion.net/irinn2/live/playlist.m3u8 -c copy -f mpegts pipe:1\n'
    )
    plans, _skipped = _plans(text)
    args = tvh_split(plans[0].url[7:])
    assert args[0] == '/usr/bin/ffmpeg'
    assert '-re' not in args
    assert args[args.index('-headers') + 1] == 'Referer: https://telewebion.net/\r\n'


def test_plan_asks_before_running_playlist_programs():
    text = '#EXTM3U\n#EXTINF:-1,Squirrels\npipe:///usr/bin/streamlink --stdout "https://y.example/live" best\n'
    playlist = parse_playlist(text)
    assert [entry.name for entry in playlist_commands(playlist)] == ['Squirrels']
    plans, skipped = plan_channels(playlist, 'ffmpeg', 'List')
    assert plans == []
    assert skipped[0].name == 'Squirrels'
    plans, skipped = plan_channels(playlist, '/usr/bin/ffmpeg', 'List', allow_commands=True)
    args = tvh_split(plans[0].url[7:])
    assert args[:2] == ['/bin/sh', '-c']
    script = shlex.split(args[2])
    pipe = script.index('|')
    assert script[:pipe] == ['/usr/bin/streamlink', '--stdout', 'https://y.example/live', 'best']
    assert script[pipe + 1] == '/usr/bin/ffmpeg'
    assert script[-1] == 'pipe:1'


def test_plan_skips_files_on_another_computer():
    plans, skipped = _plans('#EXTM3U\n#EXTINF:-1,Local\nfile:///srv/a.ts\n')
    assert plans == []
    assert skipped[0].reason == 'It is a file on another computer.'


def test_keys_fall_back_to_names_when_ids_repeat():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1 tvg-id="bbc",BBC\nhttp://a/1.ts\n'
        '#EXTINF:-1 tvg-id="bbc",BBC HD\nhttp://a/2.ts\n'
        '#EXTINF:-1,Same\nhttp://a/3.ts\n'
        '#EXTINF:-1,Same\nhttp://a/4.ts\n'
    )
    plans, _skipped = _plans(text)
    assert [plan.key for plan in plans] == ['name:BBC', 'name:BBC HD', 'name:Same', 'name:Same #2']


def test_shell_command_round_trips():
    command = shell_command('ffmpeg', ['prog', 'a b', "it's"], 'N', '')
    args = tvh_split(command[7:])
    assert args[:2] == ['/bin/sh', '-c']
    assert shlex.split(args[2])[:3] == ['prog', 'a b', "it's"]


def test_playlist_names_come_from_file_or_host():
    assert playlist_name('https://iptv-org.github.io/iptv/countries/ir.m3u') == 'ir'
    assert playlist_name('http://www.provider.tv/get.php?username=a&type=m3u') == 'provider.tv'
    assert playlist_name('/home/me/My Channels.m3u8') == 'My Channels'
    assert playlist_name('file:///home/me/list.m3u') == 'list'


def test_load_playlist_reads_files(tmp_path):
    path = tmp_path / 'a.m3u'
    path.write_bytes(b'#EXTM3U\n#EXTINF:-1,A\nhttp://x/a.ts\n')
    assert load_playlist(str(path)).entries[0].name == 'A'
    assert load_playlist(path.as_uri()).entries[0].name == 'A'
    with pytest.raises(PlaylistError) as info:
        load_playlist(str(tmp_path / 'missing.m3u'))
    assert str(info.value) == FILE_FAILED


def test_provider_headers_apply_to_download_and_streams():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.headers.get('User-Agent'), self.headers.get('X-Token')))
            body = b'#EXTM3U\n#EXTINF:-1,A\nhttp://x/a.ts|X-Token=entry\n'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        playlist = load_playlist(
            f'http://127.0.0.1:{server.server_address[1]}/list.m3u',
            headers={'User-Agent': 'TV provider', 'X-Token': 'default', 'Referer': 'https://provider/'},
        )
        assert seen == [('TV provider', 'default')]
        assert playlist.entries[0].headers == {
            'User-Agent': 'TV provider', 'X-Token': 'entry', 'Referer': 'https://provider/',
        }
    finally:
        server.shutdown()
        server.server_close()


def test_native_xtream_live_channels_are_ingested(monkeypatch):
    calls = []

    class Reply:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    replies = [
        {'user_info': {'max_connections': '2'}},
        [{'category_id': '7', 'category_name': 'News'}],
        [{
            'stream_id': 42, 'name': 'World News', 'category_id': '7', 'epg_channel_id': 'world.news',
            'stream_icon': 'https://img/news.png', 'num': 11, 'container_extension': 'm3u8',
        }],
    ]

    def get(session, url, params=None, timeout=None):
        calls.append((url, params, dict(session.headers)))
        return Reply(replies.pop(0))

    monkeypatch.setattr(requests.Session, 'get', get)
    location = xtream_playlist_url('https://xc.example:8080/base/', 'u@x', 'p a')
    playlist = load_xtream(location, headers={'User-Agent': 'XC client'})
    assert location == 'https://xc.example:8080/base/get.php?username=u%40x&password=p+a'
    assert playlist.max_connections == 2
    assert playlist.guide_url == 'https://xc.example:8080/base/xmltv.php?username=u%40x&password=p+a'
    entry = playlist.entries[0]
    assert entry.name == 'World News'
    assert entry.url == 'https://xc.example:8080/base/live/u%40x/p%20a/42.m3u8'
    assert entry.groups == ['News']
    assert entry.attrs['tvg-id'] == 'world.news'
    assert entry.headers == {'User-Agent': 'XC client'}
    assert [call[1].get('action') for call in calls] == [None, 'get_live_categories', 'get_live_streams']


def test_load_playlist_downloads_and_stops_when_cancelled():
    body = b'#EXTM3U\n' + b'#EXTINF:-1,A\nhttp://x/a.ts\n' * 20000

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_address[1]}/get.php'
    try:
        assert len(load_playlist(url).entries) == 20000
        asked = []
        with pytest.raises(PlaylistError) as info:
            load_playlist(url, cancelled=lambda: asked.append(True) or len(asked) > 1)
        assert str(info.value) == STOPPED
        assert len(asked) == 2
    finally:
        server.shutdown()
        server.server_close()


class _Reply:
    def __init__(self, data):
        self._data = data

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def test_xtream_connections_asks_the_account(monkeypatch):
    asked = []

    def get(_session, url, timeout):
        asked.append(url)
        return _Reply(replies.pop(0))

    monkeypatch.setattr(requests.Session, 'get', get)
    replies = [{'user_info': {'max_connections': '1'}}]
    assert xtream_connections('http://xt.example:8080/get.php?username=u%40x&password=p&type=m3u_plus') == 1
    assert asked == ['http://xt.example:8080/player_api.php?username=u%40x&password=p']
    replies = [
        {'user_info': {'max_connections': '0'}},
        {'user_info': {}},
        ['not', 'a', 'dict'],
        ValueError('not JSON'),
        requests.ConnectionError(),
    ]
    for _ in range(5):
        assert xtream_connections('http://xt.example/get.php?username=u&password=p') is None
    for location in ('http://example.com/list.m3u', 'http://xt.example/get.php?username=u', '/home/u/get.php'):
        assert xtream_connections(location) is None
    assert len(asked) == 6

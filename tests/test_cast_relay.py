from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import requests

from tvhplayer.core.cast_relay import CastRelay, media_type


@contextmanager
def upstream():
    calls = []
    payload = b'live transport stream bytes'

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            calls.append((self.command, self.path, dict(self.headers)))
            body = payload
            kind = 'video/mp2t'
            if self.path == '/playlist':
                body = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:5,\nsegment.ts\n'
                kind = 'application/vnd.apple.mpegurl'
            if self.path == '/key':
                body = b'1234567890123456'
                kind = 'application/octet-stream'
            if self.path == '/private' and self.headers.get('Authorization') != 'Basic dXNlcjpwYXNz':
                self.send_response(401)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            partial = self.headers.get('Range') == 'bytes=2-5'
            if partial:
                body = payload[2:6]
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Accept-Ranges', 'bytes')
            if partial:
                self.send_header('Content-Range', f'bytes 2-5/{len(payload)}')
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls, payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.fixture
def client():
    session = requests.Session()
    session.trust_env = False
    yield session
    session.close()


def test_loopback_live_stream_is_served_at_a_temporary_url(client):
    with upstream() as (base, calls, payload):
        relay = CastRelay(base + '/live?ticket=secret', '127.0.0.1', bind_address='127.0.0.1')
        try:
            assert relay.inspect() == 'video/mp2t'
            assert [call[0] for call in calls] == ['HEAD']
            assert 'secret' not in relay.url
            response = client.get(relay.url, timeout=2)
            assert response.content == payload
            assert response.headers['Access-Control-Allow-Origin'] == '*'
            preflight = client.options(relay.url, timeout=2)
            assert preflight.status_code == 204
            assert 'Range' in preflight.headers['Access-Control-Allow-Headers']
            assert client.get(relay.origin + '/arbitrary?url=' + base, timeout=2).status_code == 404
            assert client.get(relay.url + '?source=' + base, timeout=2).status_code == 404
        finally:
            relay.close()
        with pytest.raises(requests.ConnectionError):
            client.get(relay.url, timeout=1)


def test_relay_serves_head_and_byte_ranges_without_losing_headers(client):
    with upstream() as (base, calls, payload):
        relay = CastRelay(base + '/recording', '127.0.0.1', bind_address='127.0.0.1')
        try:
            assert client.head(relay.url, timeout=2).headers['Content-Length'] == str(len(payload))
            response = client.get(relay.url, headers={'Range': 'bytes=2-5'}, timeout=2)
            assert response.status_code == 206
            assert response.content == payload[2:6]
            assert response.headers['Content-Range'] == f'bytes 2-5/{len(payload)}'
        finally:
            relay.close()


def test_credentials_stay_upstream(client):
    with upstream() as (base, calls, payload):
        source = base.replace('http://', 'http://user:pass@') + '/private'
        relay = CastRelay(source, '127.0.0.1', bind_address='127.0.0.1')
        try:
            assert 'user' not in relay.url and 'pass' not in relay.url
            response = client.get(relay.url, timeout=2)
            assert response.status_code == 200
            assert response.content == payload
        finally:
            relay.close()


def test_hls_rewrites_segments_and_key_uris_to_relay_urls(client):
    with upstream() as (base, calls, payload):
        relay = CastRelay(base + '/playlist', '127.0.0.1', bind_address='127.0.0.1')
        try:
            assert relay.inspect() == 'application/vnd.apple.mpegurl'
            response = client.get(relay.url, timeout=2)
            lines = response.text.splitlines()
            key_url = lines[1].split('URI="')[1].split('"')[0]
            segment_url = lines[3]
            assert key_url.startswith(relay.origin)
            assert segment_url.startswith(relay.origin)
            assert client.get(key_url, timeout=2).content == b'1234567890123456'
            assert client.get(segment_url, timeout=2).content == payload
        finally:
            relay.close()


def test_media_type_uses_response_headers_for_extensionless_streams():
    assert media_type('video/mp4; codecs=avc1', 'http://tv/stream/channel/abc') == 'video/mp4'
    assert media_type('application/vnd.apple.mpegurl', 'http://tv/stream/channel/abc') == 'application/vnd.apple.mpegurl'

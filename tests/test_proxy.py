import http.server
import io
import threading

import pytest
import requests

from tvhplayer.core import proxy
from tvhplayer.core.http_backend import HttpBackend
from tvhplayer.core.models import ServerConfig
from tvhplayer.core.recorder import LocalRecorder

DEAD_PROXY = 'http://127.0.0.1:9'


@pytest.fixture
def proxied_env(monkeypatch):
    """An http_proxy that goes nowhere, with VLC not yet started."""
    monkeypatch.setattr(proxy, '_saved_http_proxy', proxy._HIDDEN)
    monkeypatch.setenv('http_proxy', DEAD_PROXY)
    monkeypatch.delenv('HTTP_PROXY', raising=False)
    for name in ('no_proxy', 'NO_PROXY'):
        monkeypatch.delenv(name, raising=False)


class _ServerInfo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"sw_version": "4.3"}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.HTTPServer(('127.0.0.1', 0), _ServerInfo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def test_loopback_hosts():
    assert proxy.is_loopback_url('http://127.0.0.1:24111')
    assert proxy.is_loopback_url('http://127.8.0.2/')
    assert proxy.is_loopback_url('http://localhost:9981')
    assert proxy.is_loopback_url('http://[::1]:9981/stream')
    assert not proxy.is_loopback_url('http://192.168.1.5:9981')
    assert not proxy.is_loopback_url('http://nas.local:9981')
    assert not proxy.is_loopback_url('')


def test_vlc_loses_http_proxy_but_its_value_is_kept(proxied_env):
    import os

    proxy.hide_http_proxy_from_vlc()
    assert 'http_proxy' not in os.environ
    assert proxy.http_proxy() == DEAD_PROXY
    proxy.hide_http_proxy_from_vlc()
    assert proxy.http_proxy() == DEAD_PROXY


def test_local_server_lists_skip_the_proxy(proxied_env, local_server):
    backend = HttpBackend(ServerConfig.from_dict({'name': 'Built-in Server', 'url': local_server}))
    try:
        assert backend._session.trust_env is False
        assert backend._request('GET', 'api/serverinfo')['sw_version'] == '4.3'
    finally:
        backend.close()
    with pytest.raises(requests.RequestException):
        requests.get(local_server + '/api/serverinfo', timeout=2)


def test_remote_server_lists_keep_the_saved_proxy(proxied_env, monkeypatch):
    proxy.hide_http_proxy_from_vlc()
    session = requests.Session()
    proxy.configure_session(session, 'http://nas.example:9981')
    assert session.trust_env is True
    assert session.proxies == {'http': DEAD_PROXY}
    monkeypatch.setenv('no_proxy', 'nas.example')
    excluded = requests.Session()
    proxy.configure_session(excluded, 'http://nas.example:9981')
    assert excluded.proxies == {}


def test_children_get_the_proxy_only_for_remote_streams(proxied_env):
    proxy.hide_http_proxy_from_vlc()
    assert 'http_proxy' not in proxy.child_env('http://127.0.0.1:24111/stream/channel/1')
    assert proxy.child_env('http://nas.example:9981/stream/channel/1')['http_proxy'] == DEAD_PROXY
    assert proxy.child_env(None)['http_proxy'] == DEAD_PROXY


def test_local_recording_of_the_builtin_server_skips_the_proxy(proxied_env, monkeypatch, tmp_path):
    proxy.hide_http_proxy_from_vlc()
    seen = {}

    class _Done:
        returncode = 0
        stderr = io.BytesIO(b'')

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        seen['env'] = kwargs['env']
        return _Done()

    monkeypatch.setattr('tvhplayer.core.recorder.subprocess.Popen', fake_popen)
    recorder = LocalRecorder()
    recorder.start('http://127.0.0.1:24111/stream/channel/abc', tmp_path / 'a.ts')
    recorder.stop()
    assert 'http_proxy' not in seen['env']


def test_mpv_gets_the_proxy_only_for_remote_streams(proxied_env, monkeypatch):
    proxy.hide_http_proxy_from_vlc()
    assert proxy.stream_proxy('http://127.0.0.1:24111/stream/channel/1') == ''
    assert proxy.stream_proxy('http://nas.example:9981/stream/channel/1') == DEAD_PROXY
    monkeypatch.setenv('no_proxy', 'nas.example')
    assert proxy.stream_proxy('http://nas.example:9981/stream/channel/1') == ''

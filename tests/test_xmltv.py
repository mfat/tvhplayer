import functools
import gzip
import http.server
import os
import socket
import tempfile
import threading

import pytest

from tvhplayer.core.errors import PlaylistError
from tvhplayer.core.xmltv import GUIDE_FAILED, download_guide, load_guide, send_guide, usable_socket

GUIDE = b'<?xml version="1.0"?><tv><channel id="a"><display-name>A</display-name></channel></tv>\n'


@pytest.fixture
def web(tmp_path):
    (tmp_path / 'guide.xml').write_bytes(GUIDE)
    (tmp_path / 'guide.xml.gz').write_bytes(gzip.compress(GUIDE))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


@pytest.fixture
def xmltv_socket():
    """A Unix socket that records each connection's bytes, like Tvheadend's."""
    folder = tempfile.mkdtemp(prefix='tvhx', dir='/tmp')
    path = os.path.join(folder, 'xmltv.sock')
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(4)
    received = []

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
                received.append(b''.join(chunks))

    threading.Thread(target=serve, daemon=True).start()
    yield path, received
    listener.close()
    os.unlink(path)
    os.rmdir(folder)


def _wait_for(received, count):
    for _ in range(100):
        if len(received) >= count:
            return
        threading.Event().wait(0.02)


def test_download_unpacks_gzip(web, tmp_path):
    for name in ('guide.xml', 'guide.xml.gz'):
        path = download_guide(f'{web}/{name}', folder=tmp_path)
        with open(path, 'rb') as handle:
            assert handle.read() == GUIDE
        os.unlink(path)


def test_download_failure_is_plain(web, tmp_path):
    with pytest.raises(PlaylistError) as info:
        download_guide(f'{web}/missing.xml', folder=tmp_path)
    assert str(info.value) == GUIDE_FAILED
    assert list(tmp_path.glob('tvhplayer-guide-*')) == []


def test_send_guide_writes_the_file(xmltv_socket, tmp_path):
    path, received = xmltv_socket
    guide = tmp_path / 'g.xml'
    guide.write_bytes(GUIDE)
    send_guide(path, str(guide))
    _wait_for(received, 1)
    assert received == [GUIDE]


class Admin:
    def __init__(self, socket_path='', grabber=False):
        self.socket_path = socket_path
        self.grabber = grabber
        self.enabled = False
        self.grabber_url = None

    def enable_xmltv_socket(self):
        self.enabled = True
        return self.socket_path

    def use_url_grabber(self, url):
        if self.grabber:
            self.grabber_url = url
        return self.grabber


def test_local_server_gets_the_guide_twice_for_new_channels(web, xmltv_socket):
    path, received = xmltv_socket
    admin = Admin(path)
    assert load_guide(admin, {'builtin': True}, f'{web}/guide.xml.gz', new_channels=True)
    _wait_for(received, 2)
    assert received == [GUIDE, GUIDE]
    assert load_guide(admin, {'url': 'http://127.0.0.1:9981'}, f'{web}/guide.xml', new_channels=False)
    _wait_for(received, 3)
    assert len(received) == 3


def test_remote_server_uses_its_url_grabber_or_nothing(web):
    admin = Admin('/no/such.sock', grabber=True)
    assert load_guide(admin, {'url': 'http://tv.lan:9981'}, f'{web}/guide.xml', True)
    assert not admin.enabled
    assert admin.grabber_url == f'{web}/guide.xml'
    assert not load_guide(Admin(), {'url': 'http://tv.lan:9981'}, f'{web}/guide.xml', True)


def test_usable_socket_needs_a_local_socket(xmltv_socket, tmp_path):
    path, _received = xmltv_socket
    assert usable_socket({'builtin': True}, path)
    assert not usable_socket({'url': 'http://tv.lan:9981'}, path)
    plain = tmp_path / 'file'
    plain.write_text('x')
    assert not usable_socket({'builtin': True}, str(plain))

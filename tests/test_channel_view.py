import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _png():
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt6.QtGui import QPixmap

    image = QPixmap(80, 40)
    image.fill(Qt.GlobalColor.blue)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)


def test_logo_loader_fetches_once_caches_on_disk_and_skips_failures(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    from tvhplayer.channel_view import LOGO_SIZE, LogoLoader, logo_pixmap

    app = QApplication.instance() or QApplication([])
    png = _png()
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.path, self.headers.get('Authorization')))
            if self.path == '/imagecache/1':
                self.send_response(200)
                self.send_header('Content-Length', str(len(png)))
                self.end_headers()
                self.wfile.write(png)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    box = {'url': base, 'username': 'u', 'password': 'p'}
    loader = LogoLoader(cache_dir=tmp_path)
    got = []
    loader.loaded.connect(lambda reference, data: got.append((reference, data)))
    try:
        loader.request(box, 'imagecache/1', f'{base}/imagecache/1')
        loader.request(box, 'imagecache/1', f'{base}/imagecache/1')
        loader.request(box, 'imagecache/2', f'{base}/imagecache/2')
        deadline = time.monotonic() + 5
        while (not got or len(hits) < 2) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert got == [('imagecache/1', png)]
        assert sorted(path for path, _auth in hits) == ['/imagecache/1', '/imagecache/2']
        assert all(auth and auth.startswith('Basic ') for _path, auth in hits)
        assert loader.cached(base, 'imagecache/1') == png
        assert loader.cached(base, 'imagecache/2') is None

        # A failed logo is not asked for again until forget().
        loader.request(box, 'imagecache/2', f'{base}/imagecache/2')
        time.sleep(0.2)
        assert len(hits) == 2
        loader.forget()
        loader.request(box, 'imagecache/2', f'{base}/imagecache/2')
        deadline = time.monotonic() + 5
        while len(hits) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(hits) == 3

        pixmap = logo_pixmap(png)
        assert pixmap.size() == LOGO_SIZE
        assert logo_pixmap(b'not an image') is None
    finally:
        loader.shutdown()
        server.shutdown()

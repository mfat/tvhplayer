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
        assert [reference for reference, _image in got] == ['imagecache/1']
        assert got[0][1].size() == LOGO_SIZE
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

        # The next request is read from the disk cache, not the server.
        got.clear()
        loader.forget()
        loader.request(box, 'imagecache/1', '')
        deadline = time.monotonic() + 5
        while not got and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert [reference for reference, _image in got] == ['imagecache/1']
        assert len(hits) == 3

        pixmap = logo_pixmap(png)
        assert pixmap.size() == LOGO_SIZE
        assert logo_pixmap(b'not an image') is None
    finally:
        loader.shutdown()
        server.shutdown()


def _model(channels):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    from tvhplayer.channel_view import ChannelTableModel, ChannelTableView

    app = QApplication.instance() or QApplication([])
    model = ChannelTableModel()
    view = ChannelTableView()
    view.setModel(model)
    model.set_channels(channels)
    return app, model, view


def _names(model):
    return [model.channel_at(row).name for row in range(model.rowCount())]


def test_channel_model_sorts_filters_and_keeps_the_current_channel():
    from PyQt6.QtCore import Qt

    from tvhplayer.channel_view import COL_NAME, COL_NUMBER
    from tvhplayer.core.models import Channel

    channels = [
        Channel(uuid='a', name='bbc one', number=1),
        Channel(uuid='b', name='Arte', number=12),
        Channel(uuid='c', name='BBC Two', number=2),
    ]
    app, model, view = _model(channels)
    assert _names(model) == ['bbc one', 'Arte', 'BBC Two']
    view.setCurrentCell(2, COL_NAME)

    model.sort(COL_NAME, Qt.SortOrder.AscendingOrder)
    assert _names(model) == ['Arte', 'bbc one', 'BBC Two']
    assert view.currentRow() == 2
    model.sort(COL_NUMBER, Qt.SortOrder.DescendingOrder)
    assert _names(model) == ['Arte', 'BBC Two', 'bbc one']
    assert view.currentRow() == 1

    # Name or number, any case; the current channel follows its new row.
    model.set_filter('BBC')
    assert _names(model) == ['BBC Two', 'bbc one']
    assert view.currentRow() == 0
    model.set_filter('12')
    assert _names(model) == ['Arte']
    assert view.currentRow() == -1
    model.set_filter('', members={'a', 'b'})
    assert _names(model) == ['Arte', 'bbc one']
    model.set_filter('')
    assert model.rowCount() == 3
    assert model.find_row(lambda channel: channel.uuid == 'c') == 1

    # Type-ahead in the name column.
    match = model.match(model.index(0, COL_NAME), Qt.ItemDataRole.DisplayRole, 'bb')
    assert [index.row() for index in match] == [1]
    view.close()


def test_channel_model_marks_playing_and_recording_rows_once():
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor

    from tvhplayer.channel_view import COL_NAME, COL_STATUS
    from tvhplayer.core.models import Channel

    news = Channel(uuid='news', name='News', number=1)
    sport = Channel(uuid='sport', name='Sport', number=2)
    app, model, view = _model([news, sport])
    model.describe = lambda channel, playing, recording: f'{channel.name} {playing} {recording}'
    changes = []
    model.dataChanged.connect(lambda *args: changes.append(args))
    colors = {'playing': (QColor('#1e3a8a'), QColor('#ffffff')), 'recording': None}

    model.set_marks(sport, {'news'}, colors)
    assert model.index(1, COL_STATUS).data() == 'Playing'
    assert model.index(0, COL_STATUS).data() == 'Recording'
    assert model.index(1, COL_NAME).data(Qt.ItemDataRole.BackgroundRole) == QColor('#1e3a8a')
    assert model.index(0, COL_NAME).data(Qt.ItemDataRole.BackgroundRole) is None
    assert model.index(1, COL_NAME).data(Qt.ItemDataRole.AccessibleDescriptionRole) == 'Sport True False'
    assert model.index(1, COL_STATUS).data(Qt.ItemDataRole.AccessibleDescriptionRole) == 'Sport: playing'
    count = len(changes)
    assert count > 0
    model.set_marks(Channel(uuid='sport', name='Sport', number=2), {'news'}, dict(colors))
    assert len(changes) == count
    model.set_marks(None, set(), colors)
    assert model.index(1, COL_STATUS).data() == ''
    view.close()


def test_channel_model_handles_a_very_large_list_quickly():
    from PyQt6.QtCore import Qt

    from tvhplayer.channel_view import COL_NAME
    from tvhplayer.core.models import Channel

    channels = [Channel(uuid=f'c{n}', name=f'Channel {n:06d}', number=n + 1) for n in range(400_000)]
    app, model, view = _model([])
    view.setCurrentCell(0, COL_NAME)
    started = time.monotonic()
    model.set_channels(channels)
    model.set_filter('channel 399')
    assert model.rowCount() == 1000
    model.set_filter('')
    model.sort(COL_NAME, Qt.SortOrder.DescendingOrder)
    assert model.channel_at(0).name == 'Channel 399999'
    # An item per cell took tens of seconds for this many channels.
    assert time.monotonic() - started < 5
    view.close()

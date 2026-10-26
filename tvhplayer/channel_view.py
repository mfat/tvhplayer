"""Pieces of the channel list that are not tied to the main window.

Column positions, the thin progress bar under the programme on now, and
the logo loader. Logos are fetched off the UI thread and cached on disk,
so a long list fills in without holding up the window.
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PyQt6.QtCore import QObject, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate

try:
    from .core.channel_info import (
        COLUMN_NAME,
        COLUMN_NEXT,
        COLUMN_NOW,
        COLUMN_NUMBER,
        COLUMN_STATUS,
        COLUMN_TYPE,
    )
    from .core.config import default_cache_dir
    from .core.proxy import configure_session
    from .core.urls import http_auth
except ImportError:
    from core.channel_info import (
        COLUMN_NAME,
        COLUMN_NEXT,
        COLUMN_NOW,
        COLUMN_NUMBER,
        COLUMN_STATUS,
        COLUMN_TYPE,
    )
    from core.config import default_cache_dir
    from core.proxy import configure_session
    from core.urls import http_auth

# Logical column indices. Number, name, and status keep the places older
# code reads them from; the user can still drag them anywhere on screen.
COL_NUMBER = 0
COL_NAME = 1
COL_STATUS = 2
COL_NOW = 3
COL_NEXT = 4
COL_TYPE = 5

COLUMN_INDEX = {
    COLUMN_NUMBER: COL_NUMBER,
    COLUMN_NAME: COL_NAME,
    COLUMN_STATUS: COL_STATUS,
    COLUMN_NOW: COL_NOW,
    COLUMN_NEXT: COL_NEXT,
    COLUMN_TYPE: COL_TYPE,
}
COLUMN_KEYS = {index: key for key, index in COLUMN_INDEX.items()}
COLUMN_TITLES = {
    COL_NUMBER: 'Number',
    COL_NAME: 'Channel Name',
    COL_STATUS: 'Status',
    COL_NOW: 'Now',
    COL_NEXT: 'Next',
    COL_TYPE: 'Type',
}
# Menu labels, in menu order.
COLUMN_MENU = (
    (COLUMN_NUMBER, '&Number'),
    (COLUMN_NOW, 'N&ow Playing'),
    (COLUMN_NEXT, 'Ne&xt'),
    (COLUMN_TYPE, '&Type (Radio, HD, Encrypted)'),
    (COLUMN_STATUS, '&Status'),
)

# Share of the programme already shown, 0 to 1, on Now cells.
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1

LOGO_SIZE = QSize(40, 24)


class ProgressDelegate(QStyledItemDelegate):
    """Draws the cell as usual, then a thin bar along its bottom edge."""

    BAR_HEIGHT = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not self.enabled:
            return
        value = index.data(PROGRESS_ROLE)
        if value is None:
            return
        rect = option.rect.adjusted(4, 0, -4, -2)
        bar = QRect(rect.left(), rect.bottom() - self.BAR_HEIGHT + 1, rect.width(), self.BAR_HEIGHT)
        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        track = QColor(palette.highlightedText().color() if selected else palette.mid().color())
        track.setAlpha(90)
        fill = palette.highlightedText().color() if selected else palette.highlight().color()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(bar, track)
        done = QRect(bar.left(), bar.top(), int(bar.width() * float(value)), bar.height())
        painter.fillRect(done, fill)
        painter.restore()


def logo_image(data, size=LOGO_SIZE):
    """Fit image bytes inside ``size`` on a clear canvas, so names line up.

    Returns None when the bytes are not an image Qt can read. Unlike a
    pixmap, the image can be made off the UI thread.
    """
    image = QImage()
    if not data or not image.loadFromData(data):
        return None
    scaled = image.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
    painter.end()
    return canvas


def logo_pixmap(data, size=LOGO_SIZE):
    """Pixmap of ``logo_image``, or None when the bytes are not an image."""
    image = logo_image(data, size)
    return QPixmap.fromImage(image) if image is not None else None


def padded_pixmap(image=None, size=LOGO_SIZE):
    canvas = QPixmap(size)
    canvas.fill(Qt.GlobalColor.transparent)
    if image is not None and not image.isNull():
        painter = QPainter(canvas)
        painter.drawPixmap(
            (size.width() - image.width()) // 2,
            (size.height() - image.height()) // 2,
            image,
        )
        painter.end()
    return canvas


class LogoLoader(QObject):
    """Read and fetch channel logos in the background.

    ``loaded`` carries the reference and the logo fitted by ``logo_image``.
    Bytes are kept on disk under the cache folder, keyed by server and
    reference, so the next start shows logos without asking the server
    again. Reading that cache and decoding happen off the UI thread too: a
    list of thousands of channels would otherwise freeze the window.
    """

    loaded = pyqtSignal(str, QImage)

    MAX_BYTES = 2 * 1024 * 1024
    TIMEOUT = 10

    def __init__(self, parent=None, cache_dir=None, workers=4):
        super().__init__(parent)
        self._cache_dir = (cache_dir or default_cache_dir()) / 'logos'
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='logo')
        self._local = threading.local()
        self._lock = threading.Lock()
        self._pending = set()
        self._failed = set()
        # Not cached and asked for without an address; a request with one still fetches.
        self._uncached = set()
        self._generation = 0

    def _cache_path(self, server_url, reference):
        digest = hashlib.sha1(f'{server_url}\n{reference}'.encode('utf-8')).hexdigest()
        return self._cache_dir / digest

    def cached(self, server_url, reference):
        """Bytes from the disk cache, or None."""
        try:
            return self._cache_path(server_url, reference).read_bytes() or None
        except OSError:
            return None

    def request(self, server, reference, url):
        """Load ``reference`` from the disk cache, or fetch ``url`` when it is not there.

        Nothing happens while it is queued, or after it failed before. An
        empty ``url`` only reads the cache.
        """
        key = (server.get('url') or '', reference)
        with self._lock:
            if key in self._pending or key in self._failed or (not url and key in self._uncached):
                return
            self._pending.add(key)
            generation = self._generation
        self._pool.submit(self._load, dict(server), reference, url, generation)

    def request_file(self, reference, path):
        """Load a logo from a file on this computer, such as a picon."""
        key = ('', reference)
        with self._lock:
            if key in self._pending or key in self._failed:
                return
            self._pending.add(key)
            generation = self._generation
        self._pool.submit(self._load_file, reference, path, generation)

    def forget(self):
        """Drop queued work and remembered failures, for example after a server change."""
        with self._lock:
            self._generation += 1
            self._pending.clear()
            self._failed.clear()
            self._uncached.clear()

    def shutdown(self):
        self.forget()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _session(self, base):
        sessions = getattr(self._local, 'sessions', None)
        if sessions is None:
            sessions = self._local.sessions = {}
        session = sessions.get(base)
        if session is None:
            session = sessions[base] = requests.Session()
            configure_session(session, base)
        return session

    def _load(self, server, reference, url, generation):
        server_url = server.get('url') or ''
        image = logo_image(self.cached(server_url, reference))
        if image is not None:
            self._finish((server_url, reference), reference, image, generation)
            return
        if not url:
            with self._lock:
                if generation == self._generation:
                    self._pending.discard((server_url, reference))
                    self._uncached.add((server_url, reference))
            return
        data = self._fetch(server, url)
        image = logo_image(data)
        if image is not None:
            try:
                path = self._cache_path(server_url, reference)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except OSError:
                pass
        self._finish((server_url, reference), reference, image, generation)

    def _load_file(self, reference, path, generation):
        try:
            image = logo_image(Path(path).read_bytes())
        except OSError:
            image = None
        self._finish(('', reference), reference, image, generation)

    def _fetch(self, server, url):
        try:
            response = self._session(server.get('url') or '').get(
                url, auth=http_auth(server), timeout=self.TIMEOUT, stream=True,
            )
            data = None
            if response.status_code == 200:
                data = response.raw.read(self.MAX_BYTES + 1, decode_content=True)
                if len(data) > self.MAX_BYTES:
                    data = None
            response.close()
            return data
        except (requests.RequestException, OSError, ValueError):
            return None

    def _finish(self, key, reference, image, generation):
        with self._lock:
            if generation != self._generation:
                return
            self._pending.discard(key)
            if image is None:
                self._failed.add(key)
                return
        try:
            self.loaded.emit(reference, image)
        except RuntimeError:
            # The window closed while this logo was on its way.
            pass

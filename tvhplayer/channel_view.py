"""Pieces of the channel list that are not tied to the main window.

Column positions, the table model and view, the thin progress bar under the
programme on now, and the logo loader. Logos are fetched off the UI thread
and cached on disk, so a long list fills in without holding up the window.
"""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QTableView

try:
    from .core.channel_info import (
        COLUMN_NAME,
        COLUMN_NEXT,
        COLUMN_NOW,
        COLUMN_NUMBER,
        COLUMN_STATUS,
        COLUMN_TYPE,
        channel_key,
        progress,
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
        channel_key,
        progress,
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
# The channel's logo reference, read by the logo requests for rows on screen.
LOGO_ROLE = Qt.ItemDataRole.UserRole + 2
CHANNEL_KEY_ROLE = Qt.ItemDataRole.UserRole + 3

_DISPLAY = Qt.ItemDataRole.DisplayRole
_DECORATION = Qt.ItemDataRole.DecorationRole
_TOOLTIP = Qt.ItemDataRole.ToolTipRole
_ACCESSIBLE_TEXT = Qt.ItemDataRole.AccessibleTextRole
_ACCESSIBLE_DESCRIPTION = Qt.ItemDataRole.AccessibleDescriptionRole


def programme_text(event, now, with_start=False):
    """Cell text, tooltip, and spoken text for one programme, or blanks without one."""
    if event is None:
        return '', '', None
    start = datetime.fromtimestamp(event.start).strftime('%H:%M') if event.start else ''
    stop = datetime.fromtimestamp(event.stop).strftime('%H:%M') if event.stop else ''
    text = f'{start} {event.title}' if with_start and start else event.title
    lines = [event.title]
    if event.subtitle:
        lines.append(event.subtitle)
    when = f'{start}–{stop}' if start and stop else start
    if not with_start and event.stop and event.stop > now:
        minutes = max(1, (event.stop - now + 59) // 60)
        when = f'{when}, {minutes} min left' if when else f'{minutes} min left'
    if when:
        lines.append(when)
    if event.summary and event.summary != event.subtitle:
        lines.append(event.summary)
    return text, '\n'.join(lines), ', '.join(lines[:3])


class ChannelTableModel(QAbstractTableModel):
    """The channel list as a table, worked out cell by cell as the view asks.

    A list of tens of thousands of channels made an item per cell up front,
    and searching hid rows one by one. Here the rows are positions in the
    channel list: sorting and searching rebuild that list in Python, and
    playing marks, programmes, and logos are looked up when a cell is drawn.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels = []
        self._keys = []
        self._logo_refs = []
        # Positions in _channels: every channel in sort order, and those the filter keeps.
        self._order = []
        self._rows = []
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._search = ''
        self._members = None
        self._playing = None
        self._recording = frozenset()
        self._now_next = {}
        self._show_progress = True
        self._kinds = {}
        self._logos = False
        self._pixmaps = {}
        self._placeholder = None
        # Spoken description of a channel row: describe(channel, is_playing, is_recording).
        self.describe = lambda channel, is_playing, is_recording: ''

    # Qt model interface

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMN_TITLES)

    def headerData(self, section, orientation, role=_DISPLAY):
        if role == _DISPLAY and orientation == Qt.Orientation.Horizontal:
            return COLUMN_TITLES.get(section)
        return None

    def data(self, index, role=_DISPLAY):
        if not index.isValid():
            return None
        position = self._rows[index.row()]
        column = index.column()
        if role == _DISPLAY:
            return self._display(position, column)
        if role == _DECORATION:
            if column == COL_NAME and self._logos:
                return self._pixmaps.get(self._logo_refs[position]) or self._placeholder
            return None
        if role in (_TOOLTIP, _ACCESSIBLE_TEXT, _ACCESSIBLE_DESCRIPTION, PROGRESS_ROLE):
            return self._extra(position, column, role)
        if role == CHANNEL_KEY_ROLE:
            return self._keys[position]
        if role == LOGO_ROLE and column == COL_NAME:
            return self._logo_refs[position]
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self._sort_column = column
        self._sort_order = order
        self._relayout(sort=True)

    def match(self, start, role, value, hits=1, flags=Qt.MatchFlag.MatchStartsWith | Qt.MatchFlag.MatchWrap):
        """Type-ahead in the name column, without a call back into Python per row."""
        plain = Qt.MatchFlag.MatchStartsWith | Qt.MatchFlag.MatchWrap
        if role != _DISPLAY or start.column() != COL_NAME or flags != plain or hits != 1:
            return super().match(start, role, value, hits, flags)
        text = str(value).casefold()
        count = len(self._rows)
        first = max(start.row(), 0)
        for step in range(count):
            row = (first + step) % count
            if self._channels[self._rows[row]].name.casefold().startswith(text):
                return [self.index(row, COL_NAME)]
        return []

    # What the window changes

    def set_channels(self, channels, logo_refs=None):
        self.beginResetModel()
        self._channels = list(channels)
        self._keys = [channel_key(channel) for channel in self._channels]
        self._logo_refs = list(logo_refs) if logo_refs is not None else [''] * len(self._channels)
        self._order = self._sorted(range(len(self._channels)))
        self._rows = self._filtered(self._order)
        self.endResetModel()

    def set_filter(self, search, members=None):
        """Keep the channels whose name or number holds ``search``, and in ``members`` when given."""
        search = (search or '').lower()
        members = frozenset(members) if members is not None else None
        if search == self._search and members == self._members:
            return
        self._search = search
        self._members = members
        self._relayout()

    def set_marks(self, playing, recording):
        """The channel that is on, and the keys of channels being recorded."""
        playing_id = (str(playing.uuid or ''), playing.htsp_id) if playing is not None else None
        recording = frozenset(recording)
        if playing_id == self._playing and recording == self._recording:
            return
        self._playing = playing_id
        self._recording = recording
        self._changed(range(len(COLUMN_TITLES)))

    def set_programmes(self, now_next, show_progress):
        self._now_next = now_next
        self._show_progress = show_progress
        self._changed((COL_NAME, COL_NOW, COL_NEXT))

    def set_kinds(self, kinds):
        self._kinds = kinds
        self._changed((COL_TYPE,))

    def set_logos(self, enabled, pixmaps, placeholder):
        """Show logos from ``pixmaps``, by reference, and ``placeholder`` for those still loading.

        The window keeps adding to ``pixmaps``; ``logos_arrived`` redraws them.
        """
        self._logos = enabled
        self._pixmaps = pixmaps
        self._placeholder = placeholder
        self.logos_arrived()

    def logos_arrived(self):
        self._changed((COL_NAME,), [_DECORATION])

    # Reading rows

    def channel_at(self, row):
        if 0 <= row < len(self._rows):
            return self._channels[self._rows[row]]
        return None

    def key_at(self, row):
        return self._keys[self._rows[row]] if 0 <= row < len(self._rows) else ''

    def logo_reference_at(self, row):
        return self._logo_refs[self._rows[row]] if 0 <= row < len(self._rows) else ''

    def find_row(self, matches):
        """First shown row whose channel ``matches``, or -1."""
        channels = self._channels
        return next((row for row, position in enumerate(self._rows) if matches(channels[position])), -1)

    def is_listed(self, matches):
        """Whether any channel matches, shown or left out by the filter."""
        return any(matches(channel) for channel in self._channels)

    def is_playing(self, channel):
        playing = self._playing
        if playing is None or channel is None:
            return False
        if playing[0] and channel.uuid and str(channel.uuid) == playing[0]:
            return True
        return playing[1] is not None and channel.htsp_id == playing[1]

    def is_recording(self, row):
        return self.key_at(row) in self._recording

    # Cells

    def _status(self, position):
        parts = []
        if self.is_playing(self._channels[position]):
            parts.append('Playing')
        if self._keys[position] in self._recording:
            parts.append('Recording')
        return ', '.join(parts)

    def _programmes(self, position, now):
        """The programme on now, unless it ended, and the next one."""
        now_next = self._now_next.get(self._keys[position])
        if now_next is None:
            return None, None
        current = now_next.now
        if current is not None and current.stop and current.stop <= now:
            current = None
        return current, now_next.next

    def _programme(self, position, column, now):
        current, following = self._programmes(position, now)
        return current if column == COL_NOW else following

    def _display(self, position, column):
        channel = self._channels[position]
        if column == COL_NAME:
            return channel.name
        if column == COL_NUMBER:
            return channel.number
        if column == COL_STATUS:
            return self._status(position)
        if column in (COL_NOW, COL_NEXT):
            now = int(time.time())
            event = self._programme(position, column, now)
            return programme_text(event, now, with_start=column == COL_NEXT)[0]
        if column == COL_TYPE:
            kind = self._kinds.get(self._keys[position])
            return kind.label() if kind is not None else ''
        return None

    def _extra(self, position, column, role):
        channel = self._channels[position]
        if column in (COL_NOW, COL_NEXT):
            now = int(time.time())
            event = self._programme(position, column, now)
            if role == PROGRESS_ROLE:
                if column != COL_NOW or not self._show_progress:
                    return None
                return progress(event, now)
            if role == _ACCESSIBLE_DESCRIPTION or event is None:
                return None
            _, tooltip, spoken = programme_text(event, now, with_start=column == COL_NEXT)
            return tooltip if role == _TOOLTIP else spoken
        if role == PROGRESS_ROLE:
            return None
        if column == COL_TYPE:
            kind = self._kinds.get(self._keys[position])
            if role == _TOOLTIP and kind is not None and kind.provider:
                return f'Provider: {kind.provider}'
            return None
        if role == _TOOLTIP:
            return None
        if column == COL_NUMBER:
            return f'Channel {channel.number}' if role == _ACCESSIBLE_TEXT else 'Channel number'
        if column == COL_NAME:
            if role == _ACCESSIBLE_TEXT:
                return channel.name
            return self.describe(
                channel,
                self.is_playing(channel),
                self._keys[position] in self._recording,
            )
        if column == COL_STATUS:
            status = self._status(position)
            if not status:
                return None
            return status if role == _ACCESSIBLE_TEXT else f'{channel.name}: {status.lower()}'
        return None

    # Order and filter

    def _sort_value(self, position):
        column = self._sort_column
        if column == COL_NUMBER:
            return self._channels[position].number or 0
        value = self._display(position, column)
        return str(value or '').casefold()

    def _sorted(self, positions):
        positions = list(positions)
        if self._sort_column < 0:
            return positions
        return sorted(
            positions,
            key=self._sort_value,
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )

    def _filtered(self, positions):
        search = self._search
        members = self._members
        if not search and members is None:
            return list(positions)
        channels = self._channels
        keys = self._keys
        kept = []
        for position in positions:
            if members is not None and keys[position] not in members:
                continue
            if search:
                channel = channels[position]
                if search not in channel.name.lower() and search not in str(channel.number).lower():
                    continue
            kept.append(position)
        return kept

    def _relayout(self, sort=False):
        """Sort or filter again, keeping the current row and selection on their channels."""
        self.layoutAboutToBeChanged.emit()
        old = self.persistentIndexList()
        old_positions = [self._rows[index.row()] if index.isValid() else None for index in old]
        if sort:
            self._order = self._sorted(self._order)
        self._rows = self._filtered(self._order)
        row_of = {position: row for row, position in enumerate(self._rows)} if old else {}
        new = []
        for index, position in zip(old, old_positions):
            row = row_of.get(position)
            new.append(self.index(row, index.column()) if row is not None else QModelIndex())
        self.changePersistentIndexList(old, new)
        self.layoutChanged.emit()

    def _changed(self, columns, roles=None):
        """Tell the view that cells in ``columns`` changed. It repaints the rows on screen."""
        if not self._rows:
            return
        last = len(self._rows) - 1
        for column in columns:
            self.dataChanged.emit(self.index(0, column), self.index(last, column), roles or [])


class ChannelTableView(QTableView):
    """Table view with the row helpers the window reads the channel list through."""

    def currentRow(self):
        index = self.currentIndex()
        return index.row() if index.isValid() else -1

    def rowCount(self):
        model = self.model()
        return model.rowCount() if model is not None else 0

    def setCurrentCell(self, row, column):
        model = self.model()
        if model is not None:
            self.setCurrentIndex(model.index(row, column))


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
        # After shutdown the pool takes no work; a late request is dropped.
        self._closed = False

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
            if self._closed:
                return
            if key in self._pending or key in self._failed or (not url and key in self._uncached):
                return
            self._pending.add(key)
            generation = self._generation
        self._pool.submit(self._load, dict(server), reference, url, generation)

    def request_file(self, reference, path):
        """Load a logo from a file on this computer, such as a picon."""
        key = ('', reference)
        with self._lock:
            if self._closed:
                return
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
        with self._lock:
            self._closed = True
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

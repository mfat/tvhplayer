"""The TV guide: every channel against time, in a window of its own.

The grid is painted rather than built from widgets, so a few hundred
channels over two weeks stay quick. Programmes are fetched off the UI
thread six hours at a time as the view reaches them. Moving the focus
renames the grid for assistive technology, as elsewhere in the app.
"""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QByteArray, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
)

try:
    from .a11y import announce, announce_label, buddy_label, describe, prefers_high_contrast
    from .core.backend import create_backend
    from .core.channel_info import channel_icon_reference, channel_key, channels_in_tag
    from .core.dvr import GRID_LIMIT
    from .core.guide_grid import (
        GUIDE_DAYS,
        RECORDING,
        SCHEDULED,
        SLOT_SECONDS,
        SPAN_SECONDS,
        GuideData,
        cell_at,
        cell_description,
        clock,
        day_label,
        entries_by_event,
        local_midnight,
        recording_state,
        row_cells,
        slot_start,
        spans_between,
        timing_text,
    )
    from .core.models import EpgQuery
    from .core.playlist_sync import server_key
    from .player_bar import RECORD_RED
except ImportError:
    from a11y import announce, announce_label, buddy_label, describe, prefers_high_contrast
    from core.backend import create_backend
    from core.channel_info import channel_icon_reference, channel_key, channels_in_tag
    from core.dvr import GRID_LIMIT
    from core.guide_grid import (
        GUIDE_DAYS,
        RECORDING,
        SCHEDULED,
        SLOT_SECONDS,
        SPAN_SECONDS,
        GuideData,
        cell_at,
        cell_description,
        clock,
        day_label,
        entries_by_event,
        local_midnight,
        recording_state,
        row_cells,
        slot_start,
        spans_between,
        timing_text,
    )
    from core.models import EpgQuery
    from core.playlist_sync import server_key
    from player_bar import RECORD_RED

GRID_HELP = (
    "Programmes by channel and time. Arrow keys move between programmes, Home goes back to now, "
    "Enter watches the channel, Ctrl+R records the programme, and Shift+F10 opens more actions. "
    "Type a channel name or number to jump to it."
)
TICK_MS = 30000
# Not a server key, so the first channel list always starts a read.
_NO_SERVER_YET = object()
# Typed letters within this many seconds of each other jump to a channel together.
TYPEAHEAD_SECONDS = 1.0


def _blend(base, over, amount):
    return QColor(
        round(base.red() + (over.red() - base.red()) * amount),
        round(base.green() + (over.green() - base.green()) * amount),
        round(base.blue() + (over.blue() - base.blue()) * amount),
    )


class GuideFetch(QObject):
    """Read the programmes in some spans of time, off the UI thread.

    It uses its own backend connection, so it never shares one with the
    window. ``loaded`` comes once per span; ``failed`` stops the rest.
    """

    loaded = pyqtSignal(object, object, list)
    failed = pyqtSignal(object, str)
    finished = pyqtSignal(object)

    def __init__(self, server, spans, open_backend=None, parent=None):
        super().__init__(parent)
        self.server = dict(server)
        self.spans = list(spans)
        self._open_backend = open_backend or create_backend
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name='guide-fetch', daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stopped.set()

    def _emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            # The window closed while this was on its way.
            pass

    def _run(self):
        backend = None
        span = None
        try:
            backend = self._open_backend(self.server)
            for span in self.spans:
                if self._stopped.is_set():
                    break
                events = []
                offset = 0
                while not self._stopped.is_set():
                    batch = backend.query_epg(EpgQuery(
                        ends_after=span,
                        starts_before=span + SPAN_SECONDS,
                        limit=GRID_LIMIT,
                        offset=offset,
                    ))
                    events.extend(batch)
                    if len(batch) < GRID_LIMIT:
                        break
                    offset += GRID_LIMIT
                if not self._stopped.is_set():
                    self._emit(self.loaded, self, span, events)
        except Exception as e:
            print(f"Debug: Could not load the guide: {e}")
            self._emit(self.failed, self, str(e) or type(e).__name__)
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
            self._emit(self.finished, self)


class GuideGrid(QAbstractScrollArea):
    """Channels down the side, time across the top, a box per programme.

    ``logo`` and ``playing`` are callables from the window: a channel's
    logo pixmap or None, and the key of the channel playing or None.
    """

    focus_changed = pyqtSignal()
    activated = pyqtSignal(object, object)
    record_requested = pyqtSignal(object, object)
    menu_requested = pyqtSignal(object, object, QPoint)
    spans_needed = pyqtSignal(list)
    view_moved = pyqtSignal()

    CHANNEL_WIDTH = 220
    PX_PER_MINUTE = 5
    LOGO = QSize(40, 24)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = GuideData()
        self.channels = []
        self.origin = slot_start(int(time.time()))
        self.end = self.origin + GUIDE_DAYS * 86400
        self.recordings = None
        self.logo = lambda channel: None
        self.playing = lambda: None
        self.message = ''
        self._row = 0
        self._event = None
        self._anchor = self.origin
        self._typed = ''
        self._typed_at = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMinimumSize(480, 240)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        describe(self, "TV guide", GRID_HELP)
        self._spans_timer = QTimer(self)
        self._spans_timer.setSingleShot(True)
        self._spans_timer.setInterval(120)
        self._spans_timer.timeout.connect(self._ask_for_spans)
        self._update_metrics()

    # ------------------------------------------------------------ geometry

    def _update_metrics(self):
        metrics = QFontMetrics(self.font())
        self.row_height = max(48, metrics.lineSpacing() * 2 + 18)
        self.ruler_height = max(28, metrics.lineSpacing() + 12)

    def changeEvent(self, event):
        if event.type() == event.Type.FontChange:
            self._update_metrics()
            self._update_scrollbars()
        super().changeEvent(event)

    def _timeline_width(self):
        return max(0, self.viewport().width() - self.CHANNEL_WIDTH)

    def _rows_height(self):
        return max(0, self.viewport().height() - self.ruler_height)

    def _x(self, when):
        """Viewport x of a time."""
        offset = (when - self.origin) / 60 * self.PX_PER_MINUTE
        return self.CHANNEL_WIDTH + offset - self.horizontalScrollBar().value()

    def _time_at(self, x):
        return self.origin + int((x - self.CHANNEL_WIDTH + self.horizontalScrollBar().value()) * 60 / self.PX_PER_MINUTE)

    def _y(self, row):
        return self.ruler_height + row * self.row_height - self.verticalScrollBar().value()

    def visible_span(self):
        """Times at the left and right edges of the programme area."""
        start = self._time_at(self.CHANNEL_WIDTH)
        return start, start + int(self._timeline_width() * 60 / self.PX_PER_MINUTE)

    def _visible_rows(self):
        first = max(0, self.verticalScrollBar().value() // self.row_height)
        last = min(len(self.channels), first + self._rows_height() // self.row_height + 2)
        return range(first, last)

    def _update_scrollbars(self):
        total = int((self.end - self.origin) / 60 * self.PX_PER_MINUTE)
        bar = self.horizontalScrollBar()
        bar.setRange(0, max(0, total - self._timeline_width()))
        bar.setPageStep(max(1, self._timeline_width()))
        bar.setSingleStep(SLOT_SECONDS // 60 * self.PX_PER_MINUTE // 2)
        bar = self.verticalScrollBar()
        bar.setRange(0, max(0, len(self.channels) * self.row_height - self._rows_height()))
        bar.setPageStep(max(1, self._rows_height()))
        bar.setSingleStep(self.row_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scrollbars()
        self._spans_timer.start()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()
        self._spans_timer.start()
        self.view_moved.emit()

    def scroll_to_time(self, when):
        """Put ``when`` at the left edge, or as near as the grid allows."""
        when = min(max(when, self.origin), self.end)
        self.horizontalScrollBar().setValue(int((when - self.origin) / 60 * self.PX_PER_MINUTE))

    def _ask_for_spans(self):
        start, end = self.visible_span()
        # Read the next span early, so scrolling on rarely waits.
        wanted = spans_between(start, min(end + SPAN_SECONDS // 2, self.end), self.origin)
        missing = [span for span in wanted if span not in self.data.loaded and span < self.end]
        if missing:
            self.spans_needed.emit(missing)

    def check_spans(self):
        self._spans_timer.start()

    # ------------------------------------------------------------ content

    def reset(self, origin):
        self.origin = origin
        self.end = origin + GUIDE_DAYS * 86400
        self.data.clear()
        self._event = None
        self._anchor = origin
        self._update_scrollbars()
        self.horizontalScrollBar().setValue(0)
        self.viewport().update()

    def set_channels(self, channels):
        """Show ``channels``, keeping the focused channel when it is still there."""
        current = self.current_channel()
        self.channels = list(channels)
        self._update_scrollbars()
        row = 0
        if current is not None:
            keys = [channel_key(channel) for channel in self.channels]
            if channel_key(current) in keys:
                row = keys.index(channel_key(current))
        self._row = min(row, max(0, len(self.channels) - 1))
        self._refocus(scroll=False)
        self.viewport().update()

    def set_recordings(self, entries):
        self.recordings = None if entries is None else entries_by_event(entries)
        self.viewport().update()

    def add_events(self, span, events):
        self.data.add(span, events)
        if self._event is not None:
            # A newer copy of the focused programme, if this span had one.
            for event in self.data.events(channel_key(self.channels[self._row])) if self.channels else []:
                if event.event_id is not None and event.event_id == self._event.event_id:
                    self._event = event
                    break
        else:
            self._refocus(scroll=False)
        self.viewport().update()
        self.focus_changed.emit()

    def state_of(self, event):
        return recording_state(event, self.recordings) if event is not None else ''

    # ------------------------------------------------------------ focus

    def current_channel(self):
        if 0 <= self._row < len(self.channels):
            return self.channels[self._row]
        return None

    def current_event(self):
        return self._event

    def _cells(self, row):
        if not 0 <= row < len(self.channels):
            return []
        return row_cells(self.data.events(channel_key(self.channels[row])), self.origin, self.end)

    def _refocus(self, scroll=True):
        """Focus the programme at the anchor time on the current row."""
        cells = self._cells(self._row)
        index = cell_at(cells, self._anchor)
        self._event = cells[index].event if index >= 0 else None
        if scroll:
            self._ensure_visible()
        self.viewport().update()
        self._announce()
        self.focus_changed.emit()

    def focus_channel(self, channel, when=None):
        """Focus ``channel`` at ``when`` (now by default) and bring it into view."""
        keys = [channel_key(item) for item in self.channels]
        if channel is not None and channel_key(channel) in keys:
            self._row = keys.index(channel_key(channel))
        self.focus_time(int(time.time()) if when is None else when)

    def focus_time(self, when):
        self._anchor = max(when, self.origin)
        self.scroll_to_time(slot_start(self._anchor))
        self._refocus()

    def _focus_cell(self, row, cell):
        self._row = row
        self._event = cell.event if cell is not None else None
        if cell is not None:
            start, _end = self.visible_span()
            self._anchor = max(cell.start, start)
        self._ensure_visible()
        self.viewport().update()
        self._announce()
        self.focus_changed.emit()

    def _ensure_visible(self):
        bar = self.verticalScrollBar()
        top = self._row * self.row_height
        if top < bar.value():
            bar.setValue(top)
        elif top + self.row_height > bar.value() + self._rows_height():
            bar.setValue(top + self.row_height - self._rows_height())
        if self._event is None:
            return
        start, end = self.visible_span()
        event_start = max(self._event.start, self.origin)
        if event_start >= end or self._event.stop <= start:
            self.scroll_to_time(slot_start(event_start))
        elif event_start < start and self._event.stop < end:
            self.scroll_to_time(slot_start(event_start))

    def _announce(self):
        channel = self.current_channel()
        if channel is None:
            announce(self, "TV guide, no channels")
            return
        if self._event is None:
            announce(self, f"{channel.name}, no programme information")
            return
        announce(self, cell_description(channel.name, self._event, int(time.time()), self.state_of(self._event)))

    def _move(self, rows=0, cells=0):
        if not self.channels:
            return
        if rows:
            self._row = min(max(self._row + rows, 0), len(self.channels) - 1)
            self._refocus()
            return
        row_cells_ = self._cells(self._row)
        index = -1
        if self._event is not None:
            for position, cell in enumerate(row_cells_):
                if cell.event is self._event or (
                    cell.event.event_id is not None and cell.event.event_id == self._event.event_id
                ):
                    index = position
                    break
        target = index + cells if index >= 0 else cell_at(row_cells_, self._anchor)
        if 0 <= target < len(row_cells_):
            self._focus_cell(self._row, row_cells_[target])
            return
        # Past the last programme read so far: move the view on, which reads more.
        start, end = self.visible_span()
        step = SLOT_SECONDS * 2
        if cells > 0 and end < self.end:
            self._anchor = max(self._anchor, start) + step
            self.scroll_to_time(start + step)
        elif cells < 0 and start > self.origin:
            self._anchor = max(self.origin, min(self._anchor, start) - step)
            self.scroll_to_time(start - step)
        else:
            QApplication.beep()

    def _typeahead(self, text):
        now = time.monotonic()
        if now - self._typed_at > TYPEAHEAD_SECONDS:
            self._typed = ''
        self._typed_at = now
        self._typed += text.casefold()
        typed = self._typed
        count = len(self.channels)
        for step in range(count):
            row = (self._row + step + (1 if len(typed) == 1 else 0)) % count
            channel = self.channels[row]
            if channel.name.casefold().startswith(typed) or str(channel.number or '').startswith(typed):
                self._row = row
                self._refocus()
                return
        QApplication.beep()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        page = max(1, self._rows_height() // self.row_height - 1)
        if key == Qt.Key.Key_Up:
            self._move(rows=-1)
        elif key == Qt.Key.Key_Down:
            self._move(rows=1)
        elif key == Qt.Key.Key_Left:
            self._move(cells=-1)
        elif key == Qt.Key.Key_Right:
            self._move(cells=1)
        elif key == Qt.Key.Key_PageUp:
            self._move(rows=-page)
        elif key == Qt.Key.Key_PageDown:
            self._move(rows=page)
        elif key == Qt.Key.Key_Home and ctrl:
            self._move(rows=-len(self.channels))
        elif key == Qt.Key.Key_End and ctrl:
            self._move(rows=len(self.channels))
        elif key == Qt.Key.Key_Home:
            self.focus_time(int(time.time()))
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.current_channel() is not None:
                self.activated.emit(self.current_channel(), self._event)
        elif ctrl and key == Qt.Key.Key_R:
            if self.current_channel() is not None and self._event is not None:
                self.record_requested.emit(self.current_channel(), self._event)
        elif key == Qt.Key.Key_Menu or (key == Qt.Key.Key_F10 and mods & Qt.KeyboardModifier.ShiftModifier):
            self._open_menu(self._focus_point())
        elif event.text() and event.text().isprintable() and not ctrl and event.text().strip():
            self._typeahead(event.text())
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.viewport().update()
        self._announce()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.viewport().update()

    # ------------------------------------------------------------ mouse

    def _hit(self, pos):
        """(row, cell or None, on the channel column) at a viewport point."""
        if pos.y() < self.ruler_height:
            return None, None, False
        row = int((pos.y() - self.ruler_height + self.verticalScrollBar().value()) // self.row_height)
        if not 0 <= row < len(self.channels):
            return None, None, False
        if pos.x() < self.CHANNEL_WIDTH:
            return row, None, True
        when = self._time_at(pos.x())
        for cell in self._cells(row):
            if cell.start <= when < cell.stop:
                return row, cell, False
        return row, None, False

    def mousePressEvent(self, event):
        row, cell, on_channel = self._hit(event.position().toPoint())
        if row is None:
            return super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if cell is not None:
            self._focus_cell(row, cell)
        else:
            self._row = row
            if on_channel:
                self._anchor = max(int(time.time()), self.visible_span()[0])
            else:
                self._anchor = self._time_at(event.position().x())
            self._refocus(scroll=False)
        if event.button() == Qt.MouseButton.RightButton:
            self._open_menu(event.position().toPoint())

    def mouseDoubleClickEvent(self, event):
        row, _cell, _on_channel = self._hit(event.position().toPoint())
        if row is not None and event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.current_channel(), self._event)

    def _focus_point(self):
        y = self._y(self._row) + self.row_height // 2
        x = self.CHANNEL_WIDTH + 24
        if self._event is not None:
            x = int(min(max(self._x(self._event.start), self.CHANNEL_WIDTH) + 24, self.viewport().width() - 24))
        return QPoint(x, y)

    def _open_menu(self, pos):
        if self.current_channel() is not None:
            self.menu_requested.emit(self.current_channel(), self._event, self.viewport().mapToGlobal(pos))

    def viewportEvent(self, event):
        if event.type() == event.Type.ToolTip:
            row, cell, on_channel = self._hit(event.pos())
            if cell is not None:
                lines = [cell.event.title or 'No title', timing_text(cell.event, int(time.time()))]
                if cell.event.subtitle:
                    lines.append(cell.event.subtitle)
                QToolTip.showText(event.globalPos(), '\n'.join(lines), self.viewport())
            elif row is not None and on_channel:
                QToolTip.showText(event.globalPos(), self.channels[row].name, self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    # ------------------------------------------------------------ painting

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        window = palette.color(QPalette.ColorRole.Window)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        high_contrast = prefers_high_contrast()
        width = self.viewport().width()
        height = self.viewport().height()
        painter.fillRect(self.viewport().rect(), base)
        now = int(time.time())
        start, end = self.visible_span()
        line = QColor(text)
        line.setAlpha(40)
        font = QFont(self.font())
        bold = QFont(font)
        bold.setBold(True)
        small = QFont(font)
        small.setPointSizeF(max(7.0, font.pointSizeF() * 0.88))
        if not self.channels:
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                QRectF(0, self.ruler_height, width, height - self.ruler_height),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.message or "No channels to show.",
            )
        painter.setClipRect(QRectF(self.CHANNEL_WIDTH, self.ruler_height, width - self.CHANNEL_WIDTH, height))
        unloaded = [
            span for span in spans_between(start, end, self.origin)
            if span not in self.data.loaded and span < self.end
        ]
        for row in self._visible_rows():
            y = self._y(row)
            painter.setPen(QPen(line, 1))
            painter.drawLine(QPointF(self.CHANNEL_WIDTH, y + self.row_height - 0.5), QPointF(width, y + self.row_height - 0.5))
            cells = row_cells(self.data.events(channel_key(self.channels[row])), max(start - SPAN_SECONDS, self.origin), end)
            for cell in cells:
                self._paint_cell(painter, cell, row, now, font, bold, small, high_contrast)
            for span in unloaded:
                left = max(self._x(span), self.CHANNEL_WIDTH)
                right = min(self._x(span + SPAN_SECONDS), width)
                if not any(cell.stop > span and cell.start < span + SPAN_SECONDS for cell in cells):
                    painter.setFont(small)
                    painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
                    painter.drawText(QRectF(left + 8, y, right - left - 16, self.row_height),
                                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Loading…")
            if not cells and not unloaded and self.data.loaded:
                painter.setFont(small)
                painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
                painter.drawText(QRectF(self.CHANNEL_WIDTH + 8, y, width - self.CHANNEL_WIDTH - 16, self.row_height),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "No programme information")
            if row == self._row and self._event is None and self.hasFocus():
                anchor_x = max(self._x(slot_start(self._anchor)), self.CHANNEL_WIDTH)
                painter.setPen(QPen(highlight, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(anchor_x + 1, y + 2, self.PX_PER_MINUTE * 30 - 2, self.row_height - 4), 4, 4)
        now_x = self._x(now)
        if self.CHANNEL_WIDTH <= now_x <= width:
            painter.setPen(QPen(highlight, 2))
            painter.drawLine(QPointF(now_x, self.ruler_height), QPointF(now_x, height))
        painter.setClipping(False)
        self._paint_channels(painter, window, text, highlight, line, font, bold, small)
        self._paint_ruler(painter, window, text, highlight, line, bold, small, start, end, now)
        painter.end()

    def _paint_cell(self, painter, cell, row, now, font, bold, small, high_contrast):
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        event = cell.event
        x0 = self._x(cell.start)
        x1 = self._x(cell.stop)
        y = self._y(row)
        rect = QRectF(x0 + 1.5, y + 2, max(1.0, x1 - x0 - 3), self.row_height - 5)
        focused = row == self._row and self._event is not None and (
            event is self._event or (event.event_id is not None and event.event_id == self._event.event_id)
        )
        airing = event.start <= now < event.stop
        ended = event.stop <= now
        if focused:
            fill = highlight
            ink = palette.color(QPalette.ColorRole.HighlightedText)
        elif airing:
            fill = _blend(base, highlight, 0.16)
            ink = text
        else:
            fill = _blend(base, text, 0.06)
            ink = palette.color(QPalette.ColorRole.PlaceholderText) if ended else text
        painter.setPen(QPen(_blend(base, text, 0.5 if high_contrast else 0.18), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4, 4)
        if focused and not self.hasFocus():
            painter.setPen(QPen(text, 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        if airing and event.stop > event.start:
            done = (now - max(event.start, cell.start)) / max(1, cell.stop - cell.start)
            bar = QRectF(rect.left() + 3, rect.bottom() - 4, max(0.0, (rect.width() - 6) * min(1.0, done)), 2)
            painter.fillRect(bar, ink if focused else highlight)
        # Keep the title in view when the programme began before the left edge.
        left = max(rect.left(), self.CHANNEL_WIDTH + 2) + 6
        right = rect.right() - 6
        state = self.state_of(event)
        if state:
            dot = 8
            centre = QPointF(right - dot / 2, rect.top() + 6 + dot / 2)
            if right - left > dot + 12:
                painter.setPen(QPen(QColor(RECORD_RED), 2))
                painter.setBrush(QColor(RECORD_RED) if state == RECORDING else Qt.BrushStyle.NoBrush)
                painter.drawEllipse(centre, dot / 2, dot / 2)
                right -= dot + 6
        if right - left < 8:
            return
        painter.setPen(ink)
        title_metrics = QFontMetrics(bold)
        small_metrics = QFontMetrics(small)
        top = rect.top() + (rect.height() - title_metrics.height() - small_metrics.height()) / 2
        painter.setFont(bold)
        painter.drawText(
            QRectF(left, top, right - left, title_metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(event.title or 'No title', Qt.TextElideMode.ElideRight, int(right - left)),
        )
        painter.setFont(small)
        when = f'{clock(event.start)} – {clock(event.stop)}'
        painter.drawText(
            QRectF(left, top + title_metrics.height(), rect.right() - 6 - left, small_metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            small_metrics.elidedText(when, Qt.TextElideMode.ElideRight, int(rect.right() - 6 - left)),
        )

    def _paint_channels(self, painter, window, text, highlight, line, font, bold, small):
        height = self.viewport().height()
        painter.fillRect(QRectF(0, self.ruler_height, self.CHANNEL_WIDTH, height), window)
        painter.setClipRect(QRectF(0, self.ruler_height, self.CHANNEL_WIDTH, height))
        playing = self.playing()
        metrics = QFontMetrics(font)
        for row in self._visible_rows():
            channel = self.channels[row]
            y = self._y(row)
            key = channel_key(channel)
            if row == self._row:
                painter.fillRect(QRectF(0, y, self.CHANNEL_WIDTH, self.row_height), _blend(window, highlight, 0.14))
            if key == playing:
                painter.fillRect(QRectF(0, y + 4, 4, self.row_height - 8), highlight)
            painter.setPen(QPen(line, 1))
            painter.drawLine(QPointF(0, y + self.row_height - 0.5), QPointF(self.CHANNEL_WIDTH, y + self.row_height - 0.5))
            x = 10
            number = str(channel.number) if channel.number else ''
            if channel.number_minor is not None and number:
                number += f'.{channel.number_minor}'
            painter.setPen(text)
            painter.setFont(small)
            painter.drawText(QRectF(x, y, 34, self.row_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, number)
            x += 42
            pixmap = self.logo(channel)
            if pixmap is not None:
                painter.drawPixmap(int(x), int(y + (self.row_height - pixmap.height()) / 2), pixmap)
                x += self.LOGO.width() + 8
            painter.setFont(bold if key == playing else font)
            name = channel.name
            if key == playing:
                name = f'▶ {name}'
            painter.drawText(
                QRectF(x, y, self.CHANNEL_WIDTH - x - 8, self.row_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                metrics.elidedText(name, Qt.TextElideMode.ElideRight, int(self.CHANNEL_WIDTH - x - 8)),
            )
        painter.setClipping(False)
        painter.setPen(QPen(line, 1))
        painter.drawLine(QPointF(self.CHANNEL_WIDTH - 0.5, 0), QPointF(self.CHANNEL_WIDTH - 0.5, height))

    def _paint_ruler(self, painter, window, text, highlight, line, bold, small, start, end, now):
        width = self.viewport().width()
        painter.fillRect(QRectF(0, 0, width, self.ruler_height), window)
        painter.setPen(text)
        painter.setFont(bold)
        painter.drawText(
            QRectF(10, 0, self.CHANNEL_WIDTH - 20, self.ruler_height),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            day_label(max(start, now), now),
        )
        painter.setClipRect(QRectF(self.CHANNEL_WIDTH, 0, width - self.CHANNEL_WIDTH, self.ruler_height))
        tick = slot_start(start)
        while tick <= end:
            x = self._x(tick)
            midnight = local_midnight(tick) == tick
            painter.setPen(QPen(line, 1))
            painter.drawLine(QPointF(x, self.ruler_height * 0.55), QPointF(x, self.ruler_height))
            painter.setPen(text)
            painter.setFont(bold if midnight else small)
            label = day_label(tick, now) if midnight else clock(tick)
            painter.drawText(QRectF(x + 4, 0, 200, self.ruler_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            tick += SLOT_SECONDS
        now_x = self._x(now)
        if self.CHANNEL_WIDTH <= now_x <= width:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            marker = QPainterPath()
            marker.moveTo(now_x - 5, self.ruler_height - 6)
            marker.lineTo(now_x + 5, self.ruler_height - 6)
            marker.lineTo(now_x, self.ruler_height)
            marker.closeSubpath()
            painter.drawPath(marker)
        painter.setClipping(False)
        painter.setPen(QPen(line, 1))
        painter.drawLine(QPointF(0, self.ruler_height - 0.5), QPointF(width, self.ruler_height - 0.5))


class GuideWindow(QDialog):
    """The guide in its own window, so the picture keeps playing beside it.

    ``host`` is the main window. The guide reads its channels, groups,
    logos, and recordings, and asks it to play and record.
    """

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("TV Guide")
        self.setModal(False)
        self.setAccessibleName("TV Guide")
        self.setAccessibleDescription("Programmes on every channel, with buttons to watch and record.")
        self.resize(1100, 680)
        self._server = _NO_SERVER_YET
        self._fetch = None
        self._queue = []
        self._error = ''
        self._server_message = ''
        self._overrides = {}

        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.tag_combo.currentIndexChanged.connect(self._apply_channels)
        describe(self.tag_combo, description="Show only the channels in one group.")
        self.tag_label = buddy_label("&Group:", self.tag_combo)
        bar.addWidget(self.tag_label)
        bar.addWidget(self.tag_combo)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find channel")
        self.find_box.setClearButtonEnabled(True)
        self.find_box.textChanged.connect(self._apply_channels)
        self.find_box.returnPressed.connect(lambda: self.grid.setFocus(Qt.FocusReason.OtherFocusReason))
        describe(self.find_box, "Find channel", "Show only channels whose name or number contains this text.")
        bar.addWidget(buddy_label("F&ind:", self.find_box))
        bar.addWidget(self.find_box, 1)
        self.day_combo = QComboBox()
        self.day_combo.activated.connect(self._on_day_chosen)
        describe(self.day_combo, description="Move the guide to another day, at the same time of day.")
        bar.addWidget(buddy_label("&Day:", self.day_combo))
        bar.addWidget(self.day_combo)
        self.now_btn = QPushButton("&Now")
        self.now_btn.clicked.connect(self.go_to_now)
        describe(self.now_btn, "Now", "Go back to what is on now. Keyboard: Home in the guide.")
        bar.addWidget(self.now_btn)
        self.reload_btn = QPushButton("&Reload")
        self.reload_btn.clicked.connect(self.reload)
        describe(self.reload_btn, "Reload", "Read the guide from the server again.")
        bar.addWidget(self.reload_btn)
        layout.addLayout(bar)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(4)
        describe(self.busy, "Loading the guide")
        self.busy.hide()
        layout.addWidget(self.busy)

        self.grid = GuideGrid(self)
        self.grid.logo = self._logo
        self.grid.playing = self._playing_key
        self.grid.focus_changed.connect(self._show_details)
        self.grid.activated.connect(self._watch)
        self.grid.record_requested.connect(self.toggle_recording)
        self.grid.menu_requested.connect(self._show_menu)
        self.grid.spans_needed.connect(self._want_spans)
        self.grid.view_moved.connect(self._sync_day_combo)
        layout.addWidget(self.grid, 1)

        details = QFrame()
        details.setFrameShape(QFrame.Shape.StyledPanel)
        details.setAccessibleName("Programme details")
        # Spare height goes to the grid.
        details.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        details_layout = QHBoxLayout(details)
        text_column = QVBoxLayout()
        self.channel_label = QLabel()
        self.title_label = QLabel()
        title_font = QFont(self.title_label.font())
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() * 1.25)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        self.timing_label = QLabel()
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        description_scroll = QScrollArea()
        description_scroll.setWidget(self.description_label)
        description_scroll.setWidgetResizable(True)
        description_scroll.setFrameShape(QFrame.Shape.NoFrame)
        description_scroll.setFixedHeight(QFontMetrics(self.font()).lineSpacing() * 4 + 6)
        description_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label, name in (
            (self.channel_label, "Channel"),
            (self.title_label, "Programme"),
            (self.timing_label, "Time"),
            (self.description_label, "Description"),
        ):
            label.setAccessibleDescription(name)
        text_column.addWidget(self.channel_label)
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.timing_label)
        text_column.addWidget(description_scroll)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        text_column.addWidget(self.status_label)
        details_layout.addLayout(text_column, 1)
        buttons = QVBoxLayout()
        self.watch_btn = QPushButton("&Watch")
        self.watch_btn.clicked.connect(lambda: self._watch(self.grid.current_channel(), self.grid.current_event()))
        self.record_btn = QPushButton("Re&cord")
        self.record_btn.clicked.connect(lambda: self.toggle_recording(self.grid.current_channel(), self.grid.current_event()))
        self.series_btn = QPushButton("Record &Series")
        self.series_btn.clicked.connect(lambda: self.record_series(self.grid.current_event()))
        describe(self.series_btn, "Record series", "Record every episode of this series on the server.")
        for button in (self.watch_btn, self.record_btn, self.series_btn):
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            buttons.addWidget(button)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(close_btn)
        details_layout.addLayout(buttons)
        layout.addWidget(details)
        # Enter belongs to the grid and the find box, never to a default button.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(TICK_MS)
        logo_loader = getattr(host, 'logo_loader', None)
        if logo_loader is not None:
            logo_loader.loaded.connect(lambda *_: self.grid.viewport().update())
        self._restore_geometry()
        self.channels_changed()

    # ------------------------------------------------------------ host

    def _logo(self, channel):
        host = self.host
        options = getattr(host, 'channel_options', {}) or {}
        if not options.get('logos', True) or not hasattr(host, '_logo_for'):
            return None
        reference_for = getattr(host, 'channel_logo_reference', channel_icon_reference)
        reference = reference_for(channel)
        if not reference:
            return None
        return host._logo_for(reference, getattr(host, '_backend', None))

    def _playing_key(self):
        playing = getattr(self.host, '_playing_channel', None)
        channel = playing() if callable(playing) else None
        return channel_key(channel) if channel is not None else None

    def _host_channels(self):
        channels = list(getattr(self.host, '_channels', None) or [])
        options = getattr(self.host, 'channel_options', {}) or {}
        if options.get('hide_disabled'):
            channels = [channel for channel in channels if channel.enabled]
        return channels

    def _current_server(self):
        server = self.host.current_server() if hasattr(self.host, 'current_server') else None
        ready = getattr(self.host, '_server_requests_ready', None)
        if server and callable(ready) and not ready():
            return None
        return server or None

    def channels_changed(self):
        """The main window has a new channel list, perhaps from another server."""
        server = self._current_server()
        key = server_key(server) if server else None
        if key != self._server:
            self._server = key
            self._restart(server)
        self._refresh_tags()
        self._apply_channels()

    def recordings_changed(self, entries):
        self._overrides.clear()
        self.grid.set_recordings(entries)
        self._show_details()

    def playing_changed(self):
        self.grid.viewport().update()

    # ------------------------------------------------------------ fetching

    def _restart(self, server=None):
        if self._fetch is not None:
            self._fetch.stop()
            self._fetch = None
        self._queue = []
        self._error = ''
        self.grid.reset(slot_start(int(time.time())))
        self.grid.set_recordings(getattr(self.host, '_dvr_entries', None))
        self._fill_days()
        self.busy.hide()
        if server is None:
            server = self._current_server()
        self._server_message = "" if server else "Choose a server, or wait for the built-in server to start."
        self.grid.message = self._server_message
        self.grid.check_spans()

    def reload(self):
        self._server = _NO_SERVER_YET
        self.channels_changed()

    def _want_spans(self, spans):
        missing = [span for span in spans if span not in self._queue]
        if not missing or self._error:
            return
        self._queue.extend(missing)
        self._start_fetch()

    def _start_fetch(self):
        if self._fetch is not None or not self._queue:
            return
        server = self._current_server()
        if not server:
            self._queue = []
            return
        spans = sorted(self._queue)
        self._fetch = GuideFetch(server, spans, parent=self)
        self._fetch.loaded.connect(self._on_loaded)
        self._fetch.failed.connect(self._on_failed)
        self._fetch.finished.connect(self._on_finished)
        self.busy.show()
        self._fetch.start()

    def _on_loaded(self, fetch, span, events):
        if fetch is not self._fetch:
            return
        if span in self._queue:
            self._queue.remove(span)
        self.grid.add_events(span, events)

    def _on_failed(self, fetch, message):
        if fetch is not self._fetch:
            return
        self._error = message
        self._queue = []
        self.grid.message = f"Could not load the guide: {message}"
        self.grid.viewport().update()
        self._status(f"Could not load the guide: {message}. Press Reload to try again.")

    def _on_finished(self, fetch):
        fetch.deleteLater()
        if fetch is not self._fetch:
            return
        self._fetch = None
        self.busy.hide()
        if self._queue and not self._error:
            self._start_fetch()
        else:
            self.grid.check_spans()

    def _status(self, message):
        statusbar = getattr(self.host, 'statusbar', None)
        if statusbar is not None:
            statusbar.showMessage(message)
        announce_label(self.status_label, message)

    # ------------------------------------------------------------ channels and days

    def _refresh_tags(self):
        combo = self.tag_combo
        tags = list(getattr(self.host, '_channel_tags', None) or [])
        channels = self._host_channels()
        wanted = combo.currentData()
        if wanted is None:
            options = getattr(self.host, 'channel_options', {}) or {}
            wanted = options.get('tag', '') if options.get('tag_filter') else ''
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("All channels", "")
            for tag in tags:
                count = len(channels_in_tag(channels, tag))
                if count:
                    combo.addItem(f"{tag.name or 'Unnamed'} ({count})", tag.uuid)
            index = combo.findData(wanted) if wanted else 0
            combo.setCurrentIndex(max(index, 0))
        finally:
            combo.blockSignals(False)
        shown = combo.count() > 1
        combo.setVisible(shown)
        self.tag_label.setVisible(shown)

    def _apply_channels(self):
        channels = self._host_channels()
        uuid = self.tag_combo.currentData() or ''
        if uuid:
            for tag in getattr(self.host, '_channel_tags', None) or []:
                if tag.uuid == uuid:
                    channels = channels_in_tag(channels, tag)
                    break
        text = self.find_box.text().strip().casefold()
        if text:
            channels = [
                channel for channel in channels
                if text in channel.name.casefold() or str(channel.number or '').startswith(text)
            ]
        self.grid.data.set_channels(self._host_channels())
        self.grid.set_channels(channels)
        if self._error:
            self.grid.message = f"Could not load the guide: {self._error}"
        elif text or uuid:
            self.grid.message = "No channels match."
        else:
            self.grid.message = self._server_message
        self._show_details()

    def _fill_days(self):
        combo = self.day_combo
        now = int(time.time())
        combo.blockSignals(True)
        try:
            combo.clear()
            day = local_midnight(now)
            while day < self.grid.end:
                combo.addItem(day_label(max(day, now), now), day)
                day = local_midnight(day + 26 * 3600)
        finally:
            combo.blockSignals(False)

    def _on_day_chosen(self, index):
        day = self.day_combo.itemData(index)
        if day is None:
            return
        start, _end = self.grid.visible_span()
        offset = start - local_midnight(start)
        target = local_midnight(day + 3600) + offset
        when = max(target, int(time.time())) if day <= int(time.time()) else target
        self.grid.focus_time(when)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync_day_combo(self):
        start, _end = self.grid.visible_span()
        index = self.day_combo.findData(local_midnight(start))
        if index >= 0 and index != self.day_combo.currentIndex():
            self.day_combo.blockSignals(True)
            self.day_combo.setCurrentIndex(index)
            self.day_combo.blockSignals(False)

    def go_to_now(self):
        self.grid.focus_time(int(time.time()))
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_channel(self, channel=None):
        """Open the guide at ``channel`` and now."""
        if slot_start(int(time.time())) - self.grid.origin >= 3 * 3600:
            # Hours old: what has ended is gone, and what was read may have changed.
            self._restart()
        self.show()
        self.raise_()
        self.activateWindow()
        self.grid.focus_channel(channel)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_tick(self):
        self.grid.viewport().update()
        self._show_details()

    # ------------------------------------------------------------ details and actions

    def _state(self, event):
        if event is None:
            return ''
        if event.event_id in self._overrides:
            return self._overrides[event.event_id]
        return self.grid.state_of(event)

    def _show_details(self):
        channel = self.grid.current_channel()
        event = self.grid.current_event()
        now = int(time.time())
        if channel is None:
            self.channel_label.setText("")
            self.title_label.setText("")
            self.timing_label.setText(self._error and f"Could not load the guide: {self._error}" or "")
            self.description_label.setText("")
            for button in (self.watch_btn, self.record_btn, self.series_btn):
                button.setEnabled(False)
            return
        number = f"{channel.number}  " if channel.number else ""
        self.channel_label.setText(f"{number}{channel.name}")
        self.watch_btn.setEnabled(True)
        describe(self.watch_btn, f"Watch {channel.name}", "Play this channel now in the main window.")
        if event is None:
            self.title_label.setText("No programme information")
            self.timing_label.setText(self._error and f"Could not load the guide: {self._error}" or "")
            self.description_label.setText("")
            self.record_btn.setText("Re&cord")
            self.record_btn.setEnabled(False)
            self.series_btn.setEnabled(False)
            return
        state = self._state(event)
        timing = timing_text(event, now)
        if state == RECORDING:
            timing += " · Recording"
        elif state == SCHEDULED:
            timing += " · Recording scheduled"
        self.title_label.setText(event.title or "No title")
        self.timing_label.setText(timing)
        text = "\n\n".join(part for part in (event.subtitle, event.description) if part)
        self.description_label.setText(text or "No description.")
        ended = event.stop <= now
        if state == RECORDING:
            self.record_btn.setText("Stop Re&cording")
            describe(self.record_btn, "Stop recording", "Stop this recording on the server and keep what was recorded.")
        elif state == SCHEDULED:
            self.record_btn.setText("&Cancel Recording")
            describe(self.record_btn, "Cancel recording", "Cancel the recording scheduled for this programme.")
        else:
            self.record_btn.setText("Re&cord")
            describe(self.record_btn, "Record", "Record this programme on the server. Keyboard: Ctrl+R in the guide.")
        self.record_btn.setEnabled(event.event_id is not None and (bool(state) or not ended))
        self.series_btn.setEnabled(bool(event.serieslink_uri) and event.event_id is not None and not ended)

    def _watch(self, channel, event=None):
        if channel is None:
            return
        self.host.play_channel_by_data(channel)
        self.grid.viewport().update()

    def _entry_for(self, event):
        recordings = self.grid.recordings or {}
        entry = recordings.get(event.event_id)
        if entry is not None:
            return entry
        for item in getattr(self.host, '_dvr_entries', None) or []:
            if event.dvr_uuid and item.uuid == event.dvr_uuid:
                return item
        return None

    def toggle_recording(self, channel, event):
        """Record the programme, or cancel or stop the recording it already has."""
        if channel is None or event is None or event.event_id is None:
            return
        state = self._state(event)
        title = event.title or "the programme"
        try:
            backend = self.host.get_backend()
            if state:
                entry = self._entry_for(event)
                if entry is None:
                    self._status(f"The recording of {title} is not in the list yet. Try again in a moment.")
                    self.host._refresh_tasks()
                    return
                if state == RECORDING:
                    backend.stop_dvr_entry(entry)
                    message = f"Stopped recording {title}. The recorded file is kept."
                else:
                    backend.cancel_dvr_entry(entry)
                    message = f"Cancelled the recording of {title}."
                self._overrides[event.event_id] = ''
            else:
                if event.stop <= int(time.time()):
                    return
                if not self.host.server_recordings_ready():
                    return
                backend.create_dvr_entry_by_event(event.event_id)
                self._overrides[event.event_id] = RECORDING if event.start <= int(time.time()) else SCHEDULED
                message = f"Recording {title} on {channel.name}." if event.start <= int(time.time()) else (
                    f"Scheduled {title} on {channel.name}, {clock(event.start)}."
                )
        except Exception as e:
            print(f"Debug: Could not change the recording: {e}")
            self._status(f"Could not change the recording of {title}: {e}")
            return
        self._status(message)
        self.grid.viewport().update()
        self._show_details()
        self.host._refresh_tasks()
        if hasattr(self.host, 'sync_recording_indicator'):
            self.host.sync_recording_indicator()

    def record_series(self, event):
        if event is None or event.event_id is None or not event.serieslink_uri:
            return
        title = event.title or "this series"
        if not self.host.server_recordings_ready():
            return
        try:
            self.host.get_backend().create_autorec_by_series(event.event_id)
        except Exception as e:
            print(f"Debug: Could not record the series: {e}")
            self._status(f"Could not record {title} as a series: {e}")
            return
        self._overrides[event.event_id] = RECORDING if event.start <= int(time.time()) else SCHEDULED
        self._status(f"Recording every episode of {title}.")
        self.grid.viewport().update()
        self._show_details()
        self.host._refresh_tasks()

    def _show_menu(self, channel, event, position):
        menu = QMenu(self)
        menu.setAccessibleName("Programme actions")
        watch = menu.addAction(f"Watch {channel.name}")
        watch.triggered.connect(lambda: self._watch(channel, event))
        if event is not None and event.event_id is not None:
            state = self._state(event)
            label = {RECORDING: "Stop Recording", SCHEDULED: "Cancel Recording"}.get(state, "Record")
            record = menu.addAction(label)
            record.setEnabled(bool(state) or event.stop > int(time.time()))
            record.triggered.connect(lambda: self.toggle_recording(channel, event))
            series = menu.addAction("Record Series")
            series.setEnabled(bool(event.serieslink_uri) and event.stop > int(time.time()))
            series.triggered.connect(lambda: self.record_series(event))
        menu.addSeparator()
        listing = menu.addAction("Show EPG")
        listing.triggered.connect(lambda: self.host.show_channel_epg(channel))
        now = menu.addAction("Go to Now")
        now.triggered.connect(self.go_to_now)
        menu.exec(position)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Find):
            self.find_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.find_box.selectAll()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.find_box.hasFocus() and self.find_box.text():
            self.find_box.clear()
            self.grid.setFocus(Qt.FocusReason.OtherFocusReason)
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ window

    def _restore_geometry(self):
        config = getattr(self.host, 'config', None) or {}
        saved = (config.get('guide_window') or {}).get('geometry') if isinstance(config.get('guide_window'), dict) else None
        if saved:
            try:
                self.restoreGeometry(QByteArray.fromHex(saved.encode('ascii')))
            except Exception:
                pass

    def _save_geometry(self):
        config = getattr(self.host, 'config', None)
        if config is None:
            return
        config['guide_window'] = {'geometry': bytes(self.saveGeometry().toHex()).decode('ascii')}
        save = getattr(self.host, 'save_config', None)
        if callable(save):
            save()

    def done(self, result):
        # Escape and Close hide the window; the guide read so far is kept.
        self._save_geometry()
        super().done(result)

    def closeEvent(self, event):
        self._save_geometry()
        super().closeEvent(event)

    def shutdown(self):
        if self._fetch is not None:
            self._fetch.stop()
            self._fetch = None
        self._tick.stop()

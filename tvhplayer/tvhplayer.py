from datetime import datetime, timedelta
import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QSplitter, QFrame,
    QListWidget, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox, QApplication,
    QPushButton, QLabel, QSlider, QStatusBar, QSpinBox, QGraphicsOpacityEffect, QFileDialog,
    QMenu, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QPlainTextEdit, QSizePolicy, QToolButton,
    QAbstractItemView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QCheckBox, QStackedWidget, QProgressBar, QButtonGroup,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, QUrl
from PyQt6.QtGui import (
    QIcon, QAction, QShortcut, QPainter, QPen, QColor, QPixmap, QDesktopServices,
    QFont, QFontDatabase, QFontMetrics, QKeySequence, QPalette, QValidator,
)
import html
import json
# Replace this line:
#from . import resources_rc

# With this more flexible import approach:
try:
    from . import resources_rc  # noqa: F401  # package import; registers Qt icons
except ImportError:
    import resources_rc  # noqa: F401  # source-tree fallback; registers Qt icons
try:
    from .core.backend import create_backend
    from .core.builtin_server import (
        apply_builtin_endpoint,
        builtin_config_dir,
        ensure_builtin_server,
        find_builtin_server,
        find_bundled_binary,
        builtin_requests_ready,
        is_builtin_server,
        platform_supports_builtin,
        quit_confirmation,
        recording_titles,
        upcoming_recordings,
    )
    from .core.config import ConfigStore
    from .core.logs import SERVER_LOG, configure_logging, log_dir
    from .core.dvr import instant_recording_title
    from .core.errors import TvhAuthError, TvhError
    from .core.server_log import ServerLogFeed
    from .core.models import PROTOCOL_HTTP, PROTOCOL_HTSP, Channel, recordings_to_stop
    from .core.recorder import STALL_LIMIT, LocalRecorder
    from .core.vlc_player import VlcPlayer
    from .core.playlist_sync import PlaylistSource, find_source, server_key
    from .core.playback_status import STARTING, find_subscription, starting_caption
    from .builtin_supervisor import BuiltinSupervisor
    from .file_manager import show_in_file_manager
    from .player_bar import (
        DOT_SVG,
        PILL_DARK,
        PILL_DARK_HOVER,
        RECORD_RED,
        FloatingBar,
        PlayerBar,
        svg_icon,
    )
    from .playlist_dialogs import BUSY as PLAYLIST_BUSY, ImportPlaylistDialog, PlaylistJob, PlaylistsDialog
    from .settings_dialog import SettingsDialog
    from .core.channel_info import (
        channel_icon_reference,
        channel_key,
        channel_kinds,
        channel_list_options,
        channels_in_tag,
        progress,
        recording_channel_keys,
    )
    from .channel_view import (
        COL_NAME,
        COL_NEXT,
        COL_NOW,
        COL_NUMBER,
        COL_STATUS,
        COL_TYPE,
        COLUMN_INDEX,
        COLUMN_KEYS,
        COLUMN_MENU,
        COLUMN_TITLES,
        LOGO_SIZE,
        PROGRESS_ROLE,
        LogoLoader,
        ProgressDelegate,
        logo_pixmap,
        padded_pixmap,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.backend import create_backend
    from core.builtin_server import (
        apply_builtin_endpoint,
        builtin_config_dir,
        ensure_builtin_server,
        find_builtin_server,
        find_bundled_binary,
        builtin_requests_ready,
        is_builtin_server,
        platform_supports_builtin,
        quit_confirmation,
        recording_titles,
        upcoming_recordings,
    )
    from core.config import ConfigStore
    from core.logs import SERVER_LOG, configure_logging, log_dir
    from core.dvr import instant_recording_title
    from core.errors import TvhAuthError, TvhError
    from core.server_log import ServerLogFeed
    from core.models import PROTOCOL_HTTP, PROTOCOL_HTSP, Channel, recordings_to_stop
    from core.recorder import STALL_LIMIT, LocalRecorder
    from core.vlc_player import VlcPlayer
    from core.playlist_sync import PlaylistSource, find_source, server_key
    from core.playback_status import STARTING, find_subscription, starting_caption
    from builtin_supervisor import BuiltinSupervisor
    from file_manager import show_in_file_manager
    from player_bar import (
        DOT_SVG,
        PILL_DARK,
        PILL_DARK_HOVER,
        RECORD_RED,
        FloatingBar,
        PlayerBar,
        svg_icon,
    )
    from playlist_dialogs import BUSY as PLAYLIST_BUSY, ImportPlaylistDialog, PlaylistJob, PlaylistsDialog
    from settings_dialog import SettingsDialog
    from core.channel_info import (
        channel_icon_reference,
        channel_key,
        channel_kinds,
        channel_list_options,
        channels_in_tag,
        progress,
        recording_channel_keys,
    )
    from channel_view import (
        COL_NAME,
        COL_NEXT,
        COL_NOW,
        COL_NUMBER,
        COL_STATUS,
        COL_TYPE,
        COLUMN_INDEX,
        COLUMN_KEYS,
        COLUMN_MENU,
        COLUMN_TITLES,
        LOGO_SIZE,
        PROGRESS_ROLE,
        LogoLoader,
        ProgressDelegate,
        logo_pixmap,
        padded_pixmap,
    )
try:
    from .a11y import (
        ShortcutHelpDialog,
        announce,
        announce_label,
        buddy_label,
        button_stylesheet,
        describe,
        find_shortcut,
        prefers_high_contrast,
        quality_colors,
        quality_phrase,
        row_emphasis,
        set_item_access,
    )
except ImportError:
    from a11y import (
        ShortcutHelpDialog,
        announce,
        announce_label,
        buddy_label,
        button_stylesheet,
        describe,
        find_shortcut,
        prefers_high_contrast,
        quality_colors,
        quality_phrase,
        row_emphasis,
        set_item_access,
    )
# or
#from tvhplayer import resources_rc  # Use absolute import
import time
import subprocess
import threading
import traceback
from pathlib import Path
import logging
import platform

CHANNEL_RELOAD_SECONDS = 30
# Now/next is asked for again this often, and sooner when a programme ends.
NOW_NEXT_REFRESH_SECONDS = 600
NOW_NEXT_TICK_MS = 30000
LOGO_ROLE = Qt.ItemDataRole.UserRole + 2
CHANNEL_KEY_ROLE = Qt.ItemDataRole.UserRole + 3



def fit_table_columns(table, stretch_columns):
    """Size short columns to their text and give the leftover window width to stretch_columns."""
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    for column in stretch_columns:
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)


class DVRStatusDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("DVR Status")
        self.resize(800, 600)
        self.setup_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(5000)  # Update every 5 seconds
        
        # Initial update
        self.update_status()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.setAccessibleName("DVR Status")
        self.setAccessibleDescription(
            "Scheduled, finished, and failed recordings. "
            "The Status column says whether a recording is in progress."
        )
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Recording categories")
        layout.addWidget(self.tabs)
        
        # Upcoming/Current recordings tab
        self.upcoming_table = QTableWidget()
        self.upcoming_table.setColumnCount(5)  # Added one more column for status
        self.upcoming_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Duration', 'Status'])
        fit_table_columns(self.upcoming_table, (1,))
        self._prepare_table(self.upcoming_table)
        describe(
            self.upcoming_table,
            "Upcoming and current recordings",
            "Channel, title, start time, duration, and status. Status is written in the last column.",
        )
        self.tabs.addTab(self.upcoming_table, "Upcoming/Current")  # Changed tab title
        
        # Finished recordings tab
        self.finished_table = QTableWidget()
        self.finished_table.setColumnCount(4)
        self.finished_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Duration'])
        fit_table_columns(self.finished_table, (1,))
        self._prepare_table(self.finished_table)
        describe(self.finished_table, "Finished recordings", "Channel, title, start time, and duration.")
        self.tabs.addTab(self.finished_table, "Finished")
        
        # Failed recordings tab
        self.failed_table = QTableWidget()
        self.failed_table.setColumnCount(4)
        self.failed_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Error'])
        fit_table_columns(self.failed_table, (1, 3))
        self._prepare_table(self.failed_table)
        describe(self.failed_table, "Failed recordings", "Channel, title, start time, and the error text.")
        self.tabs.addTab(self.failed_table, "Failed")

        self.tabs.currentChanged.connect(self._update_controls)

        btn_layout = QHBoxLayout()
        self.stop_btn = QPushButton("Stop &Recording")
        self.stop_btn.setToolTip("Stop the selected in-progress recording. The recorded file is kept.")
        describe(
            self.stop_btn,
            "Stop Recording",
            "Stop the selected in-progress recording. The recorded file is kept.",
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_selected)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addStretch()
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setAutoDefault(True)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.action_label = QLabel("")
        self.action_label.setWordWrap(True)
        self.action_label.setAccessibleName("Recording action result")
        layout.addWidget(self.action_label)

    def _prepare_table(self, table):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.itemSelectionChanged.connect(self._update_controls)

    def _selected_entry(self):
        table = self.tabs.currentWidget()
        if not isinstance(table, QTableWidget):
            return None
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _update_controls(self):
        entry = self._selected_entry()
        can_stop = entry is not None and entry.category() == 'recording'
        self.stop_btn.setEnabled(can_stop)

    def stop_selected(self):
        """Stop the selected in-progress recording via the backend."""
        entry = self._selected_entry()
        if entry is None or entry.category() != 'recording':
            return
        title = entry.title or 'recording'
        channel = entry.channel_name or 'channel'
        try:
            print(f"Debug: Stopping DVR entry: {title} ({entry.uuid}) on {channel}")
            self.backend.stop_dvr_entry(entry)
            announce_label(
                self.action_label,
                f"Stopped {title} on {channel}. The recorded file is kept.",
            )
            self.update_status()
            self._sync_parent_indicator()
        except Exception as e:
            print(f"Debug: Error stopping DVR entry: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            QMessageBox.critical(self, "Error", f"Failed to stop recording: {str(e)}")

    def _sync_parent_indicator(self):
        """Clear the main-window pulse when no server recording is still running."""
        parent = self.parent()
        if parent is None or not hasattr(parent, 'stop_recording_indicator'):
            return
        recorder = getattr(parent, 'local_recorder', None)
        if recorder is not None and recorder.is_running:
            return
        try:
            running = [
                item for item in self.backend.list_dvr_entries()
                if item.category() == 'recording'
            ]
        except Exception:
            return
        if not running and getattr(parent, 'is_recording', False):
            parent.stop_recording_indicator()
            if hasattr(parent, 'statusbar'):
                parent.statusbar.showMessage("Recording stopped")

    def _fill_row(self, table, row, values, entry, emphasis=None):
        colors = row_emphasis(emphasis)
        summary = ", ".join(str(value) for value in values if value)
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, entry)
                set_item_access(item, summary)
            if colors is not None:
                item.setBackground(colors[0])
                item.setForeground(colors[1])
            table.setItem(row, col, item)

    def _entry_key(self, entry):
        if entry is None:
            return None
        if entry.htsp_id is not None:
            return ('htsp', entry.htsp_id)
        return ('uuid', entry.uuid)

    def _restore_selection(self, table, key):
        if key is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            if self._entry_key(item.data(Qt.ItemDataRole.UserRole)) == key:
                table.selectRow(row)
                return
        
    def update_status(self):
        selected_key = self._entry_key(self._selected_entry())
        try:
            entries = self.backend.list_dvr_entries()
            upcoming = []
            finished = []
            failed = []
            for entry in entries:
                start = datetime.fromtimestamp(entry.start)
                duration = timedelta(seconds=entry.duration)
                bucket = entry.category()
                if bucket == 'recording':
                    upcoming.append((entry, start, duration, True))
                elif bucket == 'upcoming':
                    upcoming.append((entry, start, duration, False))
                elif bucket == 'finished':
                    finished.append((entry, start, duration))
                else:
                    error_msg = entry.error
                    if not error_msg and entry.errors:
                        error_msg = f"Recording failed with {entry.errors} errors"
                    if not error_msg and entry.errorcode:
                        error_msg = f"Error code: {entry.errorcode}"
                    failed.append((entry, start, error_msg or 'Unknown error'))

            upcoming.sort(key=lambda x: x[1])
            self.upcoming_table.setRowCount(len(upcoming))
            for i, (entry, start, duration, is_recording) in enumerate(upcoming):
                self._fill_row(
                    self.upcoming_table,
                    i,
                    [
                        entry.channel_name,
                        entry.title,
                        start.strftime('%Y-%m-%d %H:%M'),
                        str(duration),
                        "Recording" if is_recording else "Scheduled",
                    ],
                    entry,
                    'recording' if is_recording else None,
                )

            finished.sort(key=lambda x: x[1], reverse=True)
            self.finished_table.setRowCount(len(finished))
            for i, (entry, start, duration) in enumerate(finished):
                self._fill_row(
                    self.finished_table,
                    i,
                    [
                        entry.channel_name,
                        entry.title,
                        start.strftime('%Y-%m-%d %H:%M'),
                        str(duration),
                    ],
                    entry,
                )

            failed.sort(key=lambda x: x[1], reverse=True)
            self.failed_table.setRowCount(len(failed))
            for i, (entry, start, error) in enumerate(failed):
                self._fill_row(
                    self.failed_table,
                    i,
                    [
                        entry.channel_name,
                        entry.title,
                        start.strftime('%Y-%m-%d %H:%M'),
                        error,
                    ],
                    entry,
                    'failed',
                )

            self._restore_selection(self.tabs.currentWidget(), selected_key)
            self._update_controls()
        except Exception as e:
            print(f"Debug: Error updating DVR status: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
    
    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)


def _clock(seconds):
    """Format a duration as HH:MM:SS."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_size(num_bytes):
    """Format a byte count. ``None`` means the file does not exist yet."""
    if num_bytes is None:
        return ""
    size = max(0, int(num_bytes))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


def _byte_count(value):
    if isinstance(value, bool) or value is None or value == '':
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value.strip())
    return None


def _entry_filesize(entry):
    """Bytes recorded so far.

    HTSP reports the growing file in ``dataSize``. The copy under
    ``files[].size`` is taken when the file is opened and does not grow.
    HTTP reports the same live size as ``filesize``.
    """
    raw = getattr(entry, 'raw', None) or {}
    live = []
    stored = []
    for key in ('dataSize', 'data_size'):
        count = _byte_count(raw.get(key))
        if count is not None:
            live.append(count)
    for key in ('filesize', 'file_size', 'size'):
        count = _byte_count(raw.get(key))
        if count is not None:
            stored.append(count)
    positive = [count for count in live if count > 0]
    if positive:
        return max(positive)
    positive = [count for count in stored if count > 0]
    if positive:
        return max(positive)
    if live or stored:
        return 0
    return None


_TASK_TABLE_DESCRIPTION = (
    "Ongoing, scheduled, and completed recordings. "
    "The first column is a status icon. Recording rows are listed first."
)
_TASK_STATUS_ICONS = {}


def _task_status_icon(status):
    """Small glyph for a task status. The status word stays in its own column."""
    cached = _TASK_STATUS_ICONS.get(status)
    if cached is not None:
        return cached
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if status == 'Recording':
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#dc2626'))
        painter.drawEllipse(QRectF(2, 2, 12, 12))
    elif status == 'Scheduled':
        pen = QPen(QColor('#1d4ed8'))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(2, 2, 12, 12))
        painter.drawLine(QPointF(8, 8), QPointF(8, 4.5))
        painter.drawLine(QPointF(8, 8), QPointF(11, 9))
    else:
        pen = QPen(QColor('#166534'))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(3, 8.5), QPointF(6.5, 12))
        painter.drawLine(QPointF(6.5, 12), QPointF(13, 4))
    painter.end()
    icon = QIcon(pixmap)
    _TASK_STATUS_ICONS[status] = icon
    return icon


class _StatusIconDelegate(QStyledItemDelegate):
    """Draw the status glyph in the middle of the first column.

    An item view keeps the decoration on the leading edge. Aligning the
    item text does not move that glyph.
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        icon = QIcon(opt.icon)
        opt.icon = QIcon()
        opt.text = ""
        opt.features = opt.features & ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if icon.isNull():
            return
        size = opt.decorationSize
        if size.isEmpty():
            size = QSize(16, 16)
        cell = opt.rect
        target = QRect(
            cell.x() + (cell.width() - size.width()) // 2,
            cell.y() + (cell.height() - size.height()) // 2,
            size.width(),
            size.height(),
        )
        icon.paint(painter, target, Qt.AlignmentFlag.AlignCenter)


class TasksPanel(QFrame):
    """Ongoing, scheduled, and completed recordings, with search and a status filter."""

    close_requested = pyqtSignal()
    # Generation, entries or None, error or None; sent from the fetch thread.
    _server_fetched = pyqtSignal(int, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # The splitter reparents this pane, so keep the window that owns the backend.
        self._host = parent
        self._server_tasks = []
        # Server recordings are read off the UI thread over a connection of the
        # pane's own, which only the fetch thread touches. One fetch runs at a time.
        self.open_backend = create_backend
        self._backend = None
        self._backend_key = None
        self._fetching = False
        self._fetch_again = False
        # Bumped when the server changes, so an answer from the old one is dropped.
        self._generation = 0
        self._server_fetched.connect(self._on_server_fetched)
        self._tasks = []
        self._error_text = ""
        self._table_description = None
        self.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Raised)
        self.setAccessibleName("Tasks")
        self.setAccessibleDescription(
            "Ongoing, scheduled, and completed recordings. "
            "Filter by text or by status, then stop, cancel, or reveal the selected one."
        )
        self.setMinimumWidth(220)
        self._build_ui()
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh)
        self.update_timer.start(5000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        heading = QLabel("Tasks")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        heading.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        heading.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.close_btn = QToolButton()
        self.close_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_btn.setAutoRaise(True)
        describe(self.close_btn, "Close Tasks", "Hide the Tasks panel. View > Tasks shows it again.")
        self.close_btn.setToolTip("Close Tasks")
        self.close_btn.clicked.connect(self.close_requested.emit)
        heading_row = QHBoxLayout()
        heading_row.addWidget(heading, 1)
        heading_row.addWidget(self.close_btn)
        layout.addLayout(heading_row)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Channel or title")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        describe(
            self.search_box,
            "Filter tasks",
            "Filter tasks by channel, title, kind, or status.",
        )
        self.search_box.textChanged.connect(self._apply_filter)
        filter_row = QHBoxLayout()
        filter_label = buddy_label("Fi&lter:", self.search_box)
        filter_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        filter_row.addWidget(filter_label)
        filter_row.addWidget(self.search_box, 1)
        layout.addLayout(filter_row)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["Active", "All", "Recording", "Scheduled", "Completed"])
        self.status_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        describe(
            self.status_combo,
            "Task status",
            "Show scheduled and in-progress recordings, every task, only recordings, "
            "only scheduled recordings, or only completed recordings.",
        )
        self.status_combo.currentIndexChanged.connect(self._apply_filter)
        show_row = QHBoxLayout()
        show_label = buddy_label("Sho&w:", self.status_combo)
        show_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        show_row.addWidget(show_label)
        show_row.addWidget(self.status_combo, 1)
        layout.addLayout(show_row)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.task_table = QTableWidget(0, 7)
        self.task_table.setHorizontalHeaderLabels(
            ["", "Kind", "Channel", "Title", "Status", "Size", "Detail"]
        )
        status_header = self.task_table.horizontalHeaderItem(0)
        set_item_access(
            status_header,
            "Status icon",
            "Recording, scheduled, or completed.",
        )
        status_header.setToolTip("Status")
        self.task_table.setIconSize(QSize(16, 16))
        self.task_table.setItemDelegateForColumn(0, _StatusIconDelegate(self.task_table))
        fit_table_columns(self.task_table, (3, 6))
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(0, 36)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        describe(
            self.task_table,
            "Tasks",
            _TASK_TABLE_DESCRIPTION,
        )
        self.task_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_table.customContextMenuRequested.connect(self._show_task_menu)
        self.task_table.itemSelectionChanged.connect(self._update_action)
        layout.addWidget(self.task_table, 1)

        self.action_btn = QPushButton("Stop")
        self.action_btn.setEnabled(False)
        self.action_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action_btn.clicked.connect(self.run_action)
        self._set_action("Stop", "Stop the selected recording. The recorded file is kept.", False)
        self.reveal_btn = QPushButton("Reveal")
        self.reveal_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        describe(
            self.reveal_btn,
            "Reveal in File Manager",
            "Show the selected local recording in the file manager, with the file selected.",
        )
        self.reveal_btn.setToolTip("Show the file in the file manager")
        self.reveal_btn.clicked.connect(self.reveal_selected)
        self._set_reveal(False)
        action_row = QHBoxLayout()
        action_row.addWidget(self.action_btn, 1)
        action_row.addWidget(self.reveal_btn, 1)
        layout.addLayout(action_row)

    def clear_server_tasks(self):
        """Drop cached server rows, for example after the server changes."""
        self._server_tasks = []
        self._generation += 1

    def refresh(self, server=True):
        """Redraw the tasks and, with server, start reading the server's recordings.

        The server's answer redraws the rows when it arrives. A failed server
        fetch keeps the rows already shown.
        """
        if server:
            self._fetch_server_tasks()
        self._redraw()

    def _redraw(self):
        tasks = list(self._server_tasks)
        local = self._local_task()
        if local is not None:
            tasks.append(local)
        self._tasks = sorted(tasks, key=self._sort_key)
        self._apply_filter()

    def selected_task(self):
        row = self.task_table.currentRow()
        if row < 0:
            return None
        item = self.task_table.item(row, 0)
        if item is None or not item.isSelected():
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def run_action(self):
        """Stop a recording or cancel a scheduled timer."""
        task = self.selected_task()
        host = self._host
        if task is None or host is None:
            return
        title = task.get('title') or 'recording'
        channel = task.get('channel') or 'channel'
        try:
            if task['kind'] == 'Local':
                host.stop_local_recording()
            elif task['bucket'] == 'recording':
                host.get_backend().stop_dvr_entry(task['entry'])
                self._tell(host, f"Stopped {title} on {channel}. The recorded file is kept.")
                if hasattr(host, 'sync_recording_indicator'):
                    host.sync_recording_indicator()
            else:
                host.get_backend().cancel_dvr_entry(task['entry'])
                self._tell(host, f"Cancelled {title} on {channel}.")
        except Exception as exc:
            print(f"Debug: Error updating task: {exc}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            QMessageBox.critical(self, "Error", f"Failed to update the task: {exc}")
            return
        self.refresh()

    def reveal_selected(self):
        """Show the selected local recording in the file manager."""
        task = self.selected_task()
        path = (task or {}).get('path') or ''
        host = self._host
        if not self._can_reveal(task):
            return
        if show_in_file_manager(path):
            self._tell(host, f"Showing {Path(path).name} in the file manager")
            return
        folder = os.path.dirname(os.path.abspath(path))
        if folder and os.path.isdir(folder) and show_in_file_manager(folder):
            self._tell(host, f"Showing {Path(folder).name} in the file manager")
            return
        self._tell(host, "Couldn't show the recording in the file manager")

    def _show_task_menu(self, position):
        index = self.task_table.indexAt(position)
        if not index.isValid():
            return
        self.task_table.selectRow(index.row())
        menu = QMenu(self)
        menu.setAccessibleName("Task actions")
        action = menu.addAction("Reveal in File Manager")
        action.setEnabled(self._can_reveal(self.selected_task()))
        action.triggered.connect(self.reveal_selected)
        menu.exec(self.task_table.viewport().mapToGlobal(position))

    def _tell(self, host, message):
        statusbar = getattr(host, 'statusbar', None)
        if statusbar is not None:
            statusbar.showMessage(message)

    def _fetch_server_tasks(self):
        host = self._host
        server = host.current_server() if host is not None and hasattr(host, 'current_server') else None
        if not server or (hasattr(host, '_server_requests_ready') and not host._server_requests_ready()):
            self._apply_server_entries([])
            return
        if self._fetching:
            # Ask again once the running fetch is done, so a change just made shows.
            self._fetch_again = True
            return
        self._fetching = True
        self._fetch_again = False
        thread = threading.Thread(
            target=self._read_server_entries,
            args=(self._generation, dict(server)),
            name='tasks-fetch',
            daemon=True,
        )
        thread.start()

    def _read_server_entries(self, generation, server):
        """Runs on the fetch thread."""
        entries = error = None
        try:
            key = sorted((name, str(value)) for name, value in server.items())
            if self._backend is not None and self._backend_key != key:
                self._close_backend()
            if self._backend is None:
                self._backend = self.open_backend(server)
                self._backend_key = key
            entries = self._backend.list_dvr_entries()
        except Exception as exc:
            error = exc
            # Connect again next time; the connection may be broken.
            self._close_backend()
        try:
            self._server_fetched.emit(generation, entries, error)
        except RuntimeError:
            # The window closed while the server was answering.
            self._close_backend()

    def _close_backend(self):
        backend, self._backend, self._backend_key = self._backend, None, None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass

    def _on_server_fetched(self, generation, entries, error):
        self._fetching = False
        if generation != self._generation:
            # The server changed while this one was answering.
            self._fetch_server_tasks()
            return
        if error is None:
            self._apply_server_entries(entries)
        else:
            print(f"Debug: Error refreshing tasks: {error}")
            self._set_error("Couldn't refresh server recordings")
        self._redraw()
        if self._fetch_again:
            self._fetch_server_tasks()

    def _apply_server_entries(self, entries):
        fetched = self._tasks_from_entries(entries)
        self._server_tasks = fetched
        self._set_error("")
        host = self._host
        if host is not None and hasattr(host, 'channel_recordings_changed'):
            host.channel_recordings_changed(
                [task['entry'] for task in fetched if task.get('entry') is not None]
            )

    def _tasks_from_entries(self, entries):
        tasks = []
        now = int(datetime.now().timestamp())
        for entry in entries:
            category = entry.category()
            if category == 'recording':
                bucket = 'recording'
                status = 'Recording'
                start_text = datetime.fromtimestamp(entry.start).strftime('%Y-%m-%d %H:%M')
                detail = (
                    f"Started {start_text}, elapsed {_clock(now - entry.start)}, "
                    f"{_clock(entry.start + entry.duration - now)} left"
                )
            elif category == 'upcoming':
                bucket = 'scheduled'
                status = 'Scheduled'
                start_text = datetime.fromtimestamp(entry.start).strftime('%Y-%m-%d %H:%M')
                detail = f"Starts {start_text}, duration {_clock(entry.duration)}"
            elif category == 'finished':
                bucket = 'completed'
                status = 'Completed'
                finished_at = (entry.start or 0) + (entry.duration or 0)
                finished_text = datetime.fromtimestamp(finished_at).strftime('%Y-%m-%d %H:%M')
                detail = f"Finished {finished_text}, duration {_clock(entry.duration)}"
            else:
                continue
            size_bytes = _entry_filesize(entry)
            if size_bytes is None or (bucket not in ('recording', 'completed') and not size_bytes):
                size_text = ""
            else:
                size_text = _format_size(size_bytes)
            if entry.htsp_id is not None:
                key = ('server', 'htsp', entry.htsp_id)
            else:
                key = ('server', 'uuid', entry.uuid)
            tasks.append({
                'kind': 'Server',
                'bucket': bucket,
                'key': key,
                'entry': entry,
                'channel': entry.channel_name or '',
                'title': entry.title or '',
                'status': status,
                'size': size_text,
                'detail': detail,
                'start': entry.start or 0,
                'path': '',
            })
        return tasks

    def _local_task(self):
        host = self._host
        recorder = getattr(host, 'local_recorder', None) if host is not None else None
        if recorder is None:
            return None
        running = bool(getattr(recorder, 'is_running', False))
        # Read the file here. LocalRecorder.status() is what counts stalls,
        # and the recording monitor is the only caller of that.
        path = getattr(recorder, 'file_path', None) or ''
        if not running and (not path or not os.path.exists(path)):
            return None
        try:
            size = os.path.getsize(path) if path and os.path.exists(path) else 0
        except OSError:
            size = 0
        channel = getattr(host, '_recording_channel', None)
        channel_name = getattr(channel, 'name', '') or 'Local'
        title = Path(path).name or 'Local recording'
        started = getattr(recorder, 'started_at', None) or 0
        elapsed = time.time() - started if started else 0
        if running:
            detail = f"{path}, {_clock(elapsed)}"
            if getattr(recorder, 'stall_count', 0) > STALL_LIMIT:
                detail += ", stalled"
            bucket = 'recording'
            status = 'Recording'
        else:
            detail = path
            bucket = 'completed'
            status = 'Completed'
        return {
            'kind': 'Local',
            'bucket': bucket,
            'key': ('local',),
            'entry': None,
            'channel': channel_name,
            'title': title,
            'status': status,
            'size': _format_size(size),
            'detail': detail,
            'start': int(started),
            'path': path,
        }

    def _sort_key(self, task):
        order = {'recording': 0, 'scheduled': 1, 'completed': 2}.get(task['bucket'], 9)
        start = task['start']
        if task['bucket'] == 'completed':
            start = -start
        return (order, start, task.get('title') or '')

    def _can_reveal(self, task):
        return bool(task and task.get('kind') == 'Local' and task.get('path'))

    def _matches(self, task, query, status_filter):
        if status_filter == 'Active' and task['bucket'] not in ('recording', 'scheduled'):
            return False
        if status_filter == 'Recording' and task['bucket'] != 'recording':
            return False
        if status_filter == 'Scheduled' and task['bucket'] != 'scheduled':
            return False
        if status_filter == 'Completed' and task['bucket'] != 'completed':
            return False
        if not query:
            return True
        haystack = " ".join([
            task.get('kind') or '',
            task.get('channel') or '',
            task.get('title') or '',
            task.get('status') or '',
        ]).casefold()
        return query in haystack

    def _apply_filter(self, *_args):
        selected = None
        current = self.selected_task()
        if current is not None:
            selected = current.get('key')
        query = self.search_box.text().strip().casefold()
        status_filter = self.status_combo.currentText()
        visible = [
            task for task in self._tasks
            if self._matches(task, query, status_filter)
        ]
        self.task_table.blockSignals(True)
        self.task_table.setRowCount(0)
        for task in visible:
            self._add_row(task)
        self.task_table.blockSignals(False)
        if visible:
            self._set_empty("")
            self._restore_selection(selected)
        else:
            self.task_table.clearSelection()
            if self._tasks:
                self._set_empty("No matching tasks")
            else:
                self._set_empty("No tasks")
        self._update_action()

    def _add_row(self, task):
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        values = [
            task['kind'],
            task['channel'],
            task['title'],
            task['status'],
            task.get('size') or '',
            task['detail'],
        ]
        summary = (
            f"{task['kind']}, {task['channel']}, {task['title']}, "
            f"{task['status']}, {task.get('size') or 'no file yet'}. {task['detail']}"
        )
        colors = row_emphasis('recording' if task['bucket'] == 'recording' else None)
        icon_item = QTableWidgetItem()
        icon_item.setIcon(_task_status_icon(task['status']))
        icon_item.setData(Qt.ItemDataRole.UserRole, task)
        set_item_access(icon_item, summary, task['detail'])
        icon_item.setToolTip(task['status'])
        if colors is not None:
            icon_item.setBackground(colors[0])
            icon_item.setForeground(colors[1])
        self.task_table.setItem(row, 0, icon_item)
        for offset, value in enumerate(values):
            col = offset + 1
            item = QTableWidgetItem(value)
            # ElideRight hides the tail of Title and Detail. The cell tooltip
            # has to be that full text; the row description would replace it.
            if value:
                item.setToolTip(value)
            if colors is not None:
                item.setBackground(colors[0])
                item.setForeground(colors[1])
            self.task_table.setItem(row, col, item)

    def _restore_selection(self, key):
        if key is None:
            self.task_table.clearSelection()
            return
        for row in range(self.task_table.rowCount()):
            item = self.task_table.item(row, 0)
            task = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if task is not None and task.get('key') == key:
                self.task_table.selectRow(row)
                return
        self.task_table.clearSelection()

    def _update_action(self):
        task = self.selected_task()
        self._set_reveal(self._can_reveal(task))
        if task is None:
            self._set_action(
                "Stop",
                "Stop the selected recording. The recorded file is kept.",
                False,
            )
            return
        if task['bucket'] == 'completed':
            self._set_action(
                "Stop",
                "Completed recordings are finished. There is nothing to stop.",
                False,
            )
            return
        if task['bucket'] == 'scheduled':
            self._set_action(
                "Cancel",
                "Cancel the selected scheduled recording.",
                True,
            )
            return
        if task['kind'] == 'Local':
            self._set_action(
                "Stop",
                "Stop this local recording and keep the file saved so far.",
                True,
            )
            return
        self._set_action(
            "Stop",
            "Stop the selected recording. The recorded file is kept.",
            True,
        )

    def _set_action(self, name, description, enabled):
        self.action_btn.setText(name)
        self.action_btn.setEnabled(enabled)
        describe(self.action_btn, name, description)
        self.action_btn.setToolTip("")

    def _set_reveal(self, enabled):
        self.reveal_btn.setEnabled(enabled)

    def _set_error(self, message):
        if message == self._error_text:
            return
        self._error_text = message
        if message:
            announce_label(self.error_label, message)
            self.error_label.show()
            return
        self.error_label.hide()
        self.error_label.setText("")
        self.error_label.setAccessibleName("")

    def _set_empty(self, message):
        """Keep the column table visible. Speak the empty state without a filler label."""
        if message:
            description = message
        else:
            description = _TASK_TABLE_DESCRIPTION
        if description == self._table_description:
            return
        self._table_description = description
        self.task_table.setAccessibleDescription(description)


def format_minutes(minutes):
    """'1 h 30 min', '45 min', '2 h'."""
    hours, rest = divmod(int(minutes), 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if rest:
        parts.append(f"{rest} min")
    return ' '.join(parts) or '0 min'


class MinutesSpinBox(QSpinBox):
    """Minutes, shown as '1 h 30 min'."""

    def textFromValue(self, value):
        return format_minutes(value)

    def valueFromText(self, text):
        hours = minutes = 0
        parts = text.replace('h', ' h ').replace('min', ' min ').split()
        for number, unit in zip(parts, parts[1:]):
            if number.isdigit() and unit == 'h':
                hours = int(number)
            elif number.isdigit() and unit == 'min':
                minutes = int(number)
        if text.strip().isdigit():
            minutes = int(text.strip())
        return hours * 60 + minutes

    def validate(self, text, pos):
        return QValidator.State.Acceptable, text, pos


class RecordingDurationDialog(QDialog):
    """Record on Server: how long to record, and when it will stop.

    With the programme on now known, "This programme" records until it ends.
    """

    PRESETS = [('30', "30 min", 30), ('60', "1 h", 60), ('120', "2 h", 120), ('240', "4 h", 240)]
    CUSTOM_STEP = 15

    def __init__(self, parent=None, channel=None, event=None):
        super().__init__(parent)
        self.setWindowTitle("Record on Server")
        self.setModal(True)
        self._channel = channel
        now = int(time.time())
        self._event = event if event is not None and event.event_id and event.stop > now else None
        self._choice = 'prog' if self._event is not None else '60'
        self.setup_ui()
        # The start is "now", so keep the end time shown up to date.
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_summary)
        self._clock.start(15000)

    def setup_ui(self):
        contrast = prefers_high_contrast()
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(14)
        self.setAccessibleName("Record on Server")
        self.setAccessibleDescription("Choose how long to record the selected channel on the server.")

        if self._channel is not None:
            heading = QVBoxLayout()
            heading.setSpacing(2)
            name = QLabel(self._channel.name)
            font = name.font()
            font.setBold(True)
            if font.pointSizeF() > 0:
                font.setPointSizeF(font.pointSizeF() + 2)
            name.setFont(font)
            heading.addWidget(name)
            if self._event is not None:
                until = datetime.fromtimestamp(self._event.stop).strftime('%H:%M')
                now_label = QLabel(f"Now: {self._event.title} · until {until}")
                _text_color(now_label, '#5b6065')
                heading.addWidget(now_label)
            layout.addLayout(heading)

        choose = QVBoxLayout()
        choose.setSpacing(6)
        record_for = QLabel("Record for")
        choose.addWidget(record_for)
        segments = QFrame()
        segments.setObjectName("segments")
        if not contrast:
            segments.setStyleSheet(
                "#segments { border: 1px solid #b6b9bc; border-radius: 4px; background: #fcfcfc; }"
                "#segments QPushButton { border: none; border-left: 1px solid #d1d3d5; "
                "background: transparent; color: #232629; min-height: 32px; padding: 0 6px; }"
                "#segments QPushButton[first=\"true\"] { border-left: none; }"
                "#segments QPushButton:checked { background: #3daee9; color: #ffffff; font-weight: 600; }"
                "#segments QPushButton:focus { border: 2px solid palette(highlight); }"
            )
        segment_layout = QHBoxLayout(segments)
        segment_layout.setContentsMargins(0, 0, 0, 0)
        segment_layout.setSpacing(0 if not contrast else 4)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.preset_buttons = {}
        options = []
        if self._event is not None:
            options.append(('prog', "This programme", f"Record until {self._event.title} ends"))
        for key, label, minutes in self.PRESETS:
            options.append((key, label, f"Record for {format_minutes(minutes)}"))
        options.append(('custom', "Custom", "Choose the length in steps of 15 minutes"))
        for index, (key, label, description) in enumerate(options):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty('first', index == 0)
            describe(button, label, description)
            button.toggled.connect(lambda on, key=key: on and self._choose(key))
            self.preset_group.addButton(button)
            self.preset_buttons[key] = button
            segment_layout.addWidget(button, 2 if key == 'prog' else 1)
        record_for.setBuddy(self.preset_buttons[options[0][0]])
        choose.addWidget(segments)
        layout.addLayout(choose)

        self.custom_row = QWidget()
        custom_layout = QHBoxLayout(self.custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        self.less_btn = QPushButton("−")
        self.less_btn.setFixedSize(32, 32)
        describe(self.less_btn, "Shorter", "15 minutes shorter")
        self.custom_spin = MinutesSpinBox()
        self.custom_spin.setRange(self.CUSTOM_STEP, 24 * 60)
        self.custom_spin.setSingleStep(self.CUSTOM_STEP)
        self.custom_spin.setValue(90)
        self.custom_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.custom_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.custom_spin.setFixedSize(110, 32)
        describe(self.custom_spin, "Length", "Recording length, in steps of 15 minutes. Up and Down change it.")
        self.more_btn = QPushButton("+")
        self.more_btn.setFixedSize(32, 32)
        describe(self.more_btn, "Longer", "15 minutes longer")
        self.less_btn.clicked.connect(self.custom_spin.stepDown)
        self.more_btn.clicked.connect(self.custom_spin.stepUp)
        self.custom_spin.valueChanged.connect(self._update_summary)
        steps = QLabel("steps of 15 min")
        _text_color(steps, '#5b6065')
        custom_layout.addWidget(self.less_btn)
        custom_layout.addWidget(self.custom_spin)
        custom_layout.addWidget(self.more_btn)
        custom_layout.addWidget(steps)
        custom_layout.addStretch(1)
        layout.addWidget(self.custom_row)

        summary = QFrame()
        summary.setObjectName("summary")
        if not contrast:
            summary.setStyleSheet(
                "#summary { background: #fcfcfc; border: 1px solid #d6d8da; border-radius: 4px; }"
            )
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(8)
        dot = QLabel()
        dot.setPixmap(status_dot(STATUS_UNREACHABLE, 10))
        summary_layout.addWidget(dot)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_layout.addWidget(self.summary_label, 1)
        layout.addWidget(summary)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.record_btn = buttons.addButton(" &Record", QDialogButtonBox.ButtonRole.AcceptRole)
        self.record_btn.setIcon(QIcon(status_dot('#ffffff' if not contrast else STATUS_UNREACHABLE, 10)))
        self.record_btn.setDefault(True)
        if not contrast:
            self.record_btn.setStyleSheet(
                "QPushButton { background: #3daee9; color: #ffffff; font-weight: 600; "
                "border: 1px solid #2a95cf; border-radius: 3px; min-width: 96px; min-height: 28px; "
                "padding: 0 10px; } QPushButton:focus { border: 2px solid palette(highlight); }"
            )
        describe(cancel, "Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.preset_buttons[self._choice].setChecked(True)
        self._choose(self._choice)

    def _choose(self, key):
        self._choice = key
        self.custom_row.setVisible(key == 'custom')
        self._update_summary()
        self.adjustSize()

    def _minutes(self):
        if self._choice == 'custom':
            return self.custom_spin.value()
        for key, _label, minutes in self.PRESETS:
            if key == self._choice:
                return minutes
        return 0

    def _update_summary(self):
        start = datetime.now()
        start_text = start.strftime('%H:%M')
        if self.programme_event() is not None:
            end = datetime.fromtimestamp(self._event.stop)
            detail = f"stops when {html.escape(self._event.title)} ends"
        else:
            end = start + timedelta(minutes=self._minutes())
            detail = format_minutes(self._minutes())
        self.summary_label.setText(f"Records <b>{start_text} – {end.strftime('%H:%M')}</b> · {detail}")
        self.summary_label.setAccessibleName(
            f"Records {start_text} to {end.strftime('%H:%M')}, {html.unescape(detail)}"
        )

    def programme_event(self):
        """The programme on now when "This programme" is chosen, else None."""
        return self._event if self._choice == 'prog' else None

    def set_duration(self, hours, minutes):
        total = hours * 60 + minutes
        for key, _label, preset in self.PRESETS:
            if preset == total:
                self.preset_buttons[key].setChecked(True)
                return
        self.custom_spin.setValue(total)
        self.preset_buttons['custom'].setChecked(True)

    def get_duration(self):
        """Return duration in seconds"""
        event = self.programme_event()
        if event is not None:
            return max(event.stop - int(time.time()), 0)
        return self._minutes() * 60

SERVER_STATUS_ROLE = Qt.ItemDataRole.UserRole + 1
URL_HINT = "Include http:// or https:// and the port."
UNTITLED_SERVER = "Untitled server"
# Status dot colours. The status is always spelled out too.
STATUS_CONNECTED = '#27ae60'
STATUS_UNREACHABLE = '#da4453'
STATUS_INVALID = '#f67400'
STATUS_TESTING = '#3daee9'
STATUS_UNKNOWN = '#bdc3c7'
STATUS_STOPPED = '#7f8c8d'
POSITIVE_TEXT = '#27ae60'
NEGATIVE_TEXT = '#da4453'


def validate_server_url(url):
    """What is wrong with a server address, or '' when it looks usable."""
    if not url:
        return "Enter the server address"
    if url.startswith('http://'):
        rest = url[7:]
    elif url.startswith('https://'):
        rest = url[8:]
    else:
        return "Must start with http:// or https://"
    host = rest.split('/', 1)[0]
    if ':' in host:
        host, port = host.split(':', 1)
        if not (port.isascii() and port.isdigit()):
            return "Invalid port number"
        if not 1 <= int(port) <= 65535:
            return "Port must be between 1 and 65535"
    if not host:
        return "Enter a host name or IP address"
    if all(c in '0123456789.' for c in host):
        parts = host.split('.')
        if len(parts) != 4 or not all(parts):
            return "Invalid IP address format"
        if any(int(part) > 255 for part in parts):
            return "IP numbers must be between 0 and 255"
    return ""


def status_dot(color, size=10):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    painter.end()
    return pixmap


def _smaller_font(font):
    small = QFont(font)
    if small.pointSizeF() > 0:
        small.setPointSizeF(max(small.pointSizeF() - 1, 6))
    elif small.pixelSize() > 0:
        small.setPixelSize(max(small.pixelSize() - 1, 8))
    return small


def _text_color(label, color):
    """Colour a label's text, or use the style's own colour."""
    label.setStyleSheet(f"color: {color};" if color and not prefers_high_contrast() else "")


class ServerListDelegate(QStyledItemDelegate):
    """The server name, with a smaller status line under it."""

    PADDING = 10

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        height = (
            QFontMetrics(option.font).height()
            + QFontMetrics(_smaller_font(option.font)).height()
            + self.PADDING
        )
        return QSize(size.width(), max(size.height(), height))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name = opt.text
        status = index.data(SERVER_STATUS_ROLE) or ''
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        opt.text = ''
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        opt.text = name
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        rect = rect.adjusted(2, 0, -2, 0)
        palette = opt.palette
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        main = palette.highlightedText().color() if selected else palette.text().color()
        dim = main if selected or prefers_high_contrast() else palette.placeholderText().color()
        small = _smaller_font(opt.font)
        name_metrics = QFontMetrics(opt.font)
        status_metrics = QFontMetrics(small)
        top = rect.top() + (rect.height() - name_metrics.height() - status_metrics.height()) // 2
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(main)
        painter.drawText(
            QRect(rect.left(), top, rect.width(), name_metrics.height()),
            align,
            name_metrics.elidedText(name, Qt.TextElideMode.ElideRight, rect.width()),
        )
        painter.setFont(small)
        painter.setPen(dim)
        painter.drawText(
            QRect(rect.left(), top + name_metrics.height(), rect.width(), status_metrics.height()),
            align,
            status_metrics.elidedText(status, Qt.TextElideMode.ElideRight, rect.width()),
        )
        painter.restore()


class ConnectionTest(QObject):
    """Try to reach one server off the UI thread."""

    # token, ok, milliseconds, error text
    done = pyqtSignal(int, bool, int, str)

    def __init__(self, server, token):
        super().__init__()
        self._server = dict(server)
        self._token = token
        self._thread = threading.Thread(target=self._run, name='server-test', daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        started = time.monotonic()
        backend = None
        ok, error = True, ''
        try:
            backend = create_backend(self._server)
            backend.ping()
        except Exception as exc:
            ok, error = False, str(exc) or exc.__class__.__name__
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
        self.done.emit(self._token, ok, int((time.monotonic() - started) * 1000), error)


class ServerDialog(QDialog):
    """Servers on the left, the selected one's settings on the right.

    Edits apply as they are typed. Closing keeps them once every server has
    a name and a usable address.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Server Management")
        self.setModal(True)
        self.servers = []
        # id(server) -> {'phase': 'testing'|'done', 'ok', 'ms', 'error', 'token'}
        self.test_results = {}
        self._tests = set()
        self._test_token = 0
        self._loading = False
        self._supervisor = getattr(parent, 'builtin', None)
        self.setup_ui()
        self.setMinimumSize(780, 480)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setAccessibleName("Server Management")
        self.setAccessibleDescription(
            "Add, edit, or remove TVHeadend servers. Changes are kept when the window closes."
        )
        columns = QHBoxLayout()
        columns.setSpacing(12)
        layout.addLayout(columns, 1)

        left = QWidget()
        left.setFixedWidth(250)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.server_list = QListWidget()
        self.server_list.setItemDelegate(ServerListDelegate(self.server_list))
        self.server_list.setIconSize(QSize(10, 10))
        describe(
            self.server_list,
            "Servers",
            "Press Enter to edit the selected server, or Delete to remove it.",
        )
        left_layout.addWidget(buddy_label("&Servers:", self.server_list))
        left_layout.addWidget(self.server_list, 1)
        self.add_btn = QPushButton("+ &Add Server…")
        describe(self.add_btn, "Add server", "Add a new server to the list")
        self.add_btn.clicked.connect(self.add_server)
        left_layout.addWidget(self.add_btn)
        columns.addWidget(left)

        self.detail_panel = QFrame()
        self.detail_panel.setFrameShape(QFrame.Shape.StyledPanel)
        detail = QVBoxLayout(self.detail_panel)
        detail.setContentsMargins(16, 14, 16, 14)
        detail.setSpacing(14)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.title_label = QLabel()
        title_font = QFont(self.title_label.font())
        title_font.setBold(True)
        if title_font.pointSizeF() > 0:
            title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self.title_label.setFont(title_font)
        heading.addWidget(self.title_label)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_dot = QLabel()
        self.status_label = QLabel()
        self.status_label.setFont(_smaller_font(self.status_label.font()))
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label, 1)
        heading.addLayout(status_row)
        header.addLayout(heading, 1)
        self.duplicate_btn = QPushButton("Dupl&icate")
        describe(self.duplicate_btn, "Duplicate", "Add a copy of the selected server below it")
        self.duplicate_btn.clicked.connect(self.duplicate_server)
        self.remove_btn = QPushButton("&Remove")
        describe(self.remove_btn, "Remove", "Remove the selected server from the list")
        self.remove_btn.clicked.connect(self.remove_server)
        header.addWidget(self.duplicate_btn)
        header.addWidget(self.remove_btn)
        detail.addLayout(header)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        detail.addWidget(separator)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._remote_page())
        self.pages.addWidget(self._builtin_page())
        detail.addWidget(self.pages)
        detail.addStretch(1)

        footer = QHBoxLayout()
        self.open_web_btn = QPushButton("Open W&eb Interface")
        describe(
            self.open_web_btn,
            "Open Web Interface",
            "Open the selected server's web interface in the default browser",
        )
        self.open_web_btn.clicked.connect(self._open_web)
        self.log_btn = QPushButton("Server &Log")
        describe(self.log_btn, "Server log", "Show the selected server's log")
        self.log_btn.clicked.connect(self._show_log)
        footer.addWidget(self.open_web_btn)
        footer.addWidget(self.log_btn)
        footer.addStretch(1)
        detail.addLayout(footer)
        columns.addWidget(self.detail_panel, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setText("&Close")
        close_btn.setDefault(True)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Enter and double-click both move to the selected server's settings.
        self.server_list.itemActivated.connect(lambda _item: self._edit_selected())
        self.server_list.currentRowChanged.connect(lambda _row: self._show_selected())
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.server_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.remove_server)
        if self._supervisor is not None:
            self._supervisor.status_changed.connect(self._on_builtin_status)
        self._show_selected()

    def _remote_page(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("My Server")
        form.addRow(buddy_label("&Name:", self.name_input), self.name_input)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://127.0.0.1:9981")
        describe(self.url_input, description=URL_HINT)
        form.addRow(buddy_label("Server a&ddress:", self.url_input), self.url_input)
        self.url_hint = QLabel(URL_HINT)
        self.url_hint.setWordWrap(True)
        self.url_hint.setFont(_smaller_font(self.url_hint.font()))
        form.addRow("", self.url_hint)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItem("HTTP JSON API", PROTOCOL_HTTP)
        self.protocol_combo.addItem("HTSP", PROTOCOL_HTSP)
        self.htsp_port_input = QSpinBox()
        self.htsp_port_input.setRange(1, 65535)
        self.htsp_port_input.setValue(9982)
        describe(self.htsp_port_input, "HTSP port", "Port for the HTSP protocol, usually 9982.")
        self.port_label = buddy_label("P&ort:", self.htsp_port_input)
        protocol_row = QHBoxLayout()
        protocol_row.addWidget(self.protocol_combo)
        protocol_row.addWidget(self.port_label)
        protocol_row.addWidget(self.htsp_port_input)
        protocol_row.addStretch(1)
        form.addRow(buddy_label("&Protocol:", self.protocol_combo), protocol_row)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Optional")
        form.addRow(buddy_label("&Username:", self.username_input), self.username_input)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Optional")
        describe(self.password_input, description="Password is hidden while you type.")
        form.addRow(buddy_label("Pass&word:", self.password_input), self.password_input)

        self.test_btn = QPushButton("&Test Connection")
        describe(self.test_btn, "Test connection", "Check that TVHplayer can reach this server")
        self.test_btn.clicked.connect(self.test_connection)
        self.test_label = QLabel()
        self.test_label.setWordWrap(True)
        self.test_label.setFont(_smaller_font(self.test_label.font()))
        self.test_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_label, 1)
        form.addRow("", test_row)

        self.name_input.textChanged.connect(lambda text: self._edit('name', text))
        self.url_input.textChanged.connect(lambda text: self._edit('url', text))
        self.protocol_combo.currentIndexChanged.connect(
            lambda _index: self._edit('protocol', self.protocol_combo.currentData() or PROTOCOL_HTTP)
        )
        self.htsp_port_input.valueChanged.connect(lambda value: self._edit('htsp_port', value))
        self.username_input.textChanged.connect(lambda text: self._edit('username', text))
        self.password_input.textChanged.connect(lambda text: self._edit('password', text))
        return page

    def _builtin_page(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.run_btn = QPushButton("S&tart Server")
        describe(self.run_btn, "Start or stop the built-in server")
        self.run_btn.clicked.connect(self._toggle_builtin)
        run_row = QHBoxLayout()
        run_row.addWidget(self.run_btn)
        run_row.addStretch(1)
        form.addRow("Server:", run_row)
        self.builtin_address = QLabel()
        self.builtin_address.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.builtin_address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Address:", self.builtin_address)
        self.autostart = QCheckBox("Start &with TVHplayer")
        describe(
            self.autostart,
            "Start with TVHplayer",
            "Start the built-in server when TVHplayer opens",
        )
        parent = self.parent()
        if self._supervisor is not None:
            self.autostart.setChecked(bool(parent.config.get('builtin_autostart')))
            self.autostart.toggled.connect(parent._set_builtin_autostart)
        else:
            self.autostart.setEnabled(False)
        form.addRow("", self.autostart)
        note = QLabel("Managed by TVHplayer. Its address can’t be edited and it can’t be removed.")
        note.setWordWrap(True)
        note.setFont(_smaller_font(note.font()))
        form.addRow("", note)
        return page

    def load_servers(self, servers):
        # A copy, so the main window's list changes only when the dialog closes.
        self.servers = [dict(server) for server in servers]
        self.test_results.clear()
        self.server_list.blockSignals(True)
        self.server_list.clear()
        for row in range(len(self.servers)):
            self.server_list.addItem(QListWidgetItem())
            self._sync_item(row)
        if self.servers:
            self.server_list.setCurrentRow(0)
        self.server_list.blockSignals(False)
        self._show_selected()

    def _selected_server(self):
        row = self.server_list.currentRow()
        return self.servers[row] if 0 <= row < len(self.servers) else None

    def _builtin_state(self):
        if self._supervisor is None:
            return 'stopped'
        if self._supervisor.status == 'running' and not self._supervisor.is_running():
            return 'stopped'
        return self._supervisor.status

    def _builtin_url(self, server):
        if self._supervisor is not None and self._supervisor.is_running():
            return f"http://127.0.0.1:{self._supervisor.http_port}"
        return server.get('url') or ''

    def _status(self, server):
        """Dot colour and words for a server's state."""
        if server.get('builtin'):
            return {
                'running': (STATUS_CONNECTED, "Running on this computer"),
                'starting': (STATUS_TESTING, "Starting…"),
                'failed': (STATUS_UNREACHABLE, "Could not start"),
            }.get(self._builtin_state(), (STATUS_STOPPED, "Stopped"))
        if validate_server_url(server.get('url') or ''):
            return STATUS_INVALID, "Address needs fixing"
        result = self.test_results.get(id(server))
        if result is None:
            return STATUS_UNKNOWN, "Not checked"
        if result['phase'] == 'testing':
            return STATUS_TESTING, "Testing…"
        if result['ok']:
            return STATUS_CONNECTED, "Connected"
        return STATUS_UNREACHABLE, "Unreachable"

    def _sync_item(self, row):
        item = self.server_list.item(row)
        if item is None:
            return
        server = self.servers[row]
        name = server.get('name') or UNTITLED_SERVER
        color, text = self._status(server)
        item.setText(name)
        item.setData(SERVER_STATUS_ROLE, text)
        item.setIcon(QIcon(status_dot(color)))
        set_item_access(item, f"{name}, {text}")

    def _sync_server(self, server):
        for row, entry in enumerate(self.servers):
            if entry is server:
                self._sync_item(row)

    def _show_selected(self):
        """Fill the right side from the selected server."""
        server = self._selected_server()
        builtin = bool(server and server.get('builtin'))
        self.pages.setCurrentIndex(1 if builtin else 0)
        self.pages.setVisible(server is not None)
        self.duplicate_btn.setVisible(server is not None and not builtin)
        self.remove_btn.setVisible(server is not None and not builtin)
        if server is not None and not builtin:
            self._loading = True
            try:
                self.name_input.setText(server.get('name') or '')
                self.url_input.setText(server.get('url') or '')
                index = self.protocol_combo.findData((server.get('protocol') or PROTOCOL_HTTP).lower())
                self.protocol_combo.setCurrentIndex(index if index >= 0 else 0)
                try:
                    self.htsp_port_input.setValue(int(server.get('htsp_port') or 9982))
                except (TypeError, ValueError):
                    self.htsp_port_input.setValue(9982)
                self.username_input.setText(server.get('username') or '')
                self.password_input.setText(server.get('password') or '')
            finally:
                self._loading = False
        self._refresh_selected()

    def _refresh_selected(self):
        """Update the status, hints, and buttons for the selected server."""
        server = self._selected_server()
        if server is None:
            self.title_label.setText("No server selected")
            self.status_dot.clear()
            self.status_label.clear()
            self.open_web_btn.setEnabled(False)
            self.log_btn.setEnabled(False)
            return
        self._sync_item(self.server_list.currentRow())
        color, text = self._status(server)
        self.title_label.setText(server.get('name') or UNTITLED_SERVER)
        self.status_dot.setPixmap(status_dot(color))
        self.status_label.setText(text)
        if server.get('builtin'):
            state = self._builtin_state()
            active = state in ('starting', 'running')
            self.run_btn.setText("S&top Server" if active else "S&tart Server")
            self.run_btn.setEnabled(self._supervisor is not None)
            self.builtin_address.setText(self._builtin_url(server) or "Chosen when the server starts")
            self.open_web_btn.setEnabled(state == 'running')
            self.log_btn.setEnabled(self._supervisor is not None)
            return
        error = validate_server_url(server.get('url') or '')
        self.url_hint.setText(error or URL_HINT)
        describe(self.url_input, description=error or URL_HINT)
        _text_color(self.url_hint, NEGATIVE_TEXT if error else self.palette().placeholderText().color().name())
        if error and not prefers_high_contrast():
            self.url_input.setStyleSheet(
                f"QLineEdit {{ border: 1px solid {NEGATIVE_TEXT}; border-radius: 3px; padding: 2px 4px; }}"
            )
        else:
            self.url_input.setStyleSheet("")
        htsp = (server.get('protocol') or PROTOCOL_HTTP).lower() == PROTOCOL_HTSP
        self.port_label.setVisible(htsp)
        self.htsp_port_input.setVisible(htsp)
        result = self.test_results.get(id(server))
        testing = bool(result and result['phase'] == 'testing')
        self._show_test_result(server, error, result)
        self.test_btn.setEnabled(not error and not testing)
        self.open_web_btn.setEnabled(not error)
        self.log_btn.setEnabled(not error)

    def _show_test_result(self, server, error, result):
        color = None
        if error:
            text = "Fix the address to test this server."
        elif result is None:
            text = "Not tested yet."
        elif result['phase'] == 'testing':
            text = f"Connecting to {server.get('url')}…"
        elif result['ok']:
            text = f"Connected to Tvheadend in {result['ms']} ms."
            color = POSITIVE_TEXT
        else:
            text = f"Could not connect: {result['error'].rstrip('.')}."
            color = NEGATIVE_TEXT
        _text_color(self.test_label, color)
        if self.test_label.text() != text:
            announce_label(self.test_label, text)

    def _edit(self, key, value):
        if self._loading:
            return
        server = self._selected_server()
        if server is None or server.get('builtin'):
            return
        server[key] = value
        self.test_results.pop(id(server), None)
        self._refresh_selected()

    def _edit_selected(self):
        server = self._selected_server()
        if server is None:
            return
        if server.get('builtin'):
            self.run_btn.setFocus()
        else:
            self.name_input.setFocus()

    def _insert_server(self, row, server):
        self.servers.insert(row, server)
        self.server_list.insertItem(row, QListWidgetItem())
        self._sync_item(row)
        self.server_list.setCurrentRow(row)

    def add_server(self):
        self._insert_server(len(self.servers), {
            'name': 'New server',
            'url': '',
            'username': '',
            'password': '',
            'protocol': PROTOCOL_HTTP,
            'htsp_port': 9982,
        })
        self.name_input.setFocus()
        self.name_input.selectAll()

    def duplicate_server(self):
        row = self.server_list.currentRow()
        server = self._selected_server()
        if server is None or server.get('builtin'):
            return
        copy = dict(server)
        copy['name'] = f"{server.get('name') or UNTITLED_SERVER} (copy)"
        self._insert_server(row + 1, copy)

    def remove_server(self):
        row = self.server_list.currentRow()
        server = self._selected_server()
        if server is None or server.get('builtin'):
            return
        self.test_results.pop(id(server), None)
        self.servers.pop(row)
        self.server_list.takeItem(row)
        if self.servers:
            self.server_list.setCurrentRow(min(row, len(self.servers) - 1))
        self._show_selected()

    def test_connection(self):
        server = self._selected_server()
        if server is None or server.get('builtin') or validate_server_url(server.get('url') or ''):
            return
        self._test_token += 1
        token = self._test_token
        self.test_results[id(server)] = {'phase': 'testing', 'token': token}
        test = ConnectionTest(server, token)
        test.done.connect(
            lambda done_token, ok, ms, error, test=test, server=server:
            self._tested(test, server, done_token, ok, ms, error)
        )
        self._tests.add(test)
        test.start()
        self._refresh_selected()

    def _tested(self, test, server, token, ok, ms, error):
        self._tests.discard(test)
        current = self.test_results.get(id(server))
        # Ignore a result for a server that was edited or removed meanwhile.
        if not current or current.get('token') != token or not any(s is server for s in self.servers):
            return
        self.test_results[id(server)] = {'phase': 'done', 'ok': ok, 'ms': ms, 'error': error}
        self._sync_server(server)
        if self._selected_server() is server:
            self._refresh_selected()

    def _on_builtin_status(self, _status):
        for row, server in enumerate(self.servers):
            if server.get('builtin'):
                self._sync_item(row)
        server = self._selected_server()
        if server is not None and server.get('builtin'):
            self._refresh_selected()

    def _toggle_builtin(self):
        if self._supervisor is None:
            return
        if self._builtin_state() in ('starting', 'running'):
            self._supervisor.stop()
        else:
            self._supervisor.start()
        self._refresh_selected()

    def accept(self):
        for row, server in enumerate(self.servers):
            if server.get('builtin'):
                continue
            field = None
            if not (server.get('name') or '').strip():
                problem, field = "Give this server a name.", self.name_input
            else:
                error = validate_server_url(server.get('url') or '')
                if error:
                    problem, field = f"Fix the server address: {error}.", self.url_input
            if field is not None:
                self.server_list.setCurrentRow(row)
                QMessageBox.warning(
                    self,
                    "Check Server Settings",
                    f"{server.get('name') or UNTITLED_SERVER}: {problem}",
                )
                field.setFocus()
                return
        super().accept()

    def reject(self):
        # Edits apply as they are typed, so every way of closing keeps them.
        self.accept()

    def done(self, result):
        for test in self._tests:
            try:
                test.done.disconnect()
            except TypeError:
                pass
        self._tests.clear()
        if self._supervisor is not None:
            try:
                self._supervisor.status_changed.disconnect(self._on_builtin_status)
            except TypeError:
                pass
        super().done(result)

    def _show_log(self):
        server = self._selected_server()
        if server is None:
            return
        if server.get('builtin'):
            self.parent().show_builtin_log()
        else:
            self.parent().show_server_log(server)

    def _open_web(self):
        server = self._selected_server()
        if server is None:
            return
        if server.get('builtin'):
            self.parent().open_builtin_web()
        else:
            QDesktopServices.openUrl(QUrl(server['url']))

class ServerStatusDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.server = backend.server.to_dict()
        self.parent = parent
        self.setWindowTitle("Server Status")
        self.resize(800, 600)
        self.setup_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(5000)  # Update every 5 seconds
        
        # Initial update
        self.update_status()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setAccessibleName("Server Status")
        self.setAccessibleDescription(
            "Active streams, signal quality, and server information. "
            "Signal quality is written as good, fair, weak, or poor."
        )
        
        # Create tab widget
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Server status categories")
        layout.addWidget(self.tabs)
        
        # Active streams/subscriptions tab
        self.subscriptions_table = QTableWidget()
        self.subscriptions_table.setColumnCount(5)
        self.subscriptions_table.setHorizontalHeaderLabels([
            'Channel/Peer', 
            'User', 
            'Start Time', 
            'Duration',
            'Type/Status'
        ])
        fit_table_columns(self.subscriptions_table, (0, 4))
        describe(self.subscriptions_table, "Active streams", "Connections and subscriptions, with type or status in the last column.")
        self.tabs.addTab(self.subscriptions_table, "Active Streams")
        
        # Signal Status tab (new)
        self.signal_table = QTableWidget()
        self.signal_table.setColumnCount(5)
        self.signal_table.setHorizontalHeaderLabels([
            'Input', 
            'Signal Strength', 
            'SNR',
            'Stream',
            'Weight'
        ])
        fit_table_columns(self.signal_table, (0, 3))
        describe(
            self.signal_table,
            "Signal status",
            "Signal and SNR values include a quality word: good, fair, weak, or poor.",
        )
        self.tabs.addTab(self.signal_table, "Signal Status")
        
        # Server info tab
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        describe(self.info_text, "Server information", "Name, address, protocol, and version.")
        self.tabs.addTab(self.info_text, "Server Info")
        
        # Close button
        close_btn = QPushButton("&Close")
        close_btn.setAutoDefault(True)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
    def update_status(self):
        try:
            # 1. Update Server Info Tab
            protocol = self.server.get('protocol', PROTOCOL_HTTP)
            server_info = "Server Information:\n\n"
            server_info += f"Name: {self.server.get('name', 'Unknown')}\n"
            server_info += f"URL: {self.server.get('url', 'Unknown')}\n"
            server_info += f"Protocol: {protocol.upper()}\n"
            if protocol == PROTOCOL_HTSP:
                server_info += f"HTSP port: {self.server.get('htsp_port', 9982)}\n"
            try:
                info = self.backend.get_server_info()
                server_info += f"\nServer Version: {info.version or 'Unknown'}\n"
                server_info += f"API Version: {info.api_version or 'Unknown'}\n"
                server_info += f"Server Name: {info.name or 'Unknown'}\n"
                if info.capabilities:
                    server_info += "\nCapabilities:\n"
                    for cap in info.capabilities:
                        server_info += f"- {cap}\n"
            except Exception as e:
                server_info += f"\nError fetching server info: {str(e)}\n"
            
            self.info_text.setText(server_info)

            # 2. Update Signal Status Tab
            try:
                inputs = self.backend.get_inputs() or []
                if inputs is not None:
                    
                    # Set up table with double the rows (signal and SNR on separate rows)
                    self.signal_table.setRowCount(len(inputs) * 2)
                    
                    for i, input in enumerate(inputs):
                        # Base row for this input (multiply by 2 since we're using 2 rows per input)
                        base_row = i * 2
                        
                        # Input name spans both rows
                        input_item = QTableWidgetItem(str(input.get('input', 'Unknown')))
                        self.signal_table.setItem(base_row, 0, input_item)
                        self.signal_table.setSpan(base_row, 0, 2, 1)  # Span 2 rows
                        
                        # Signal row
                        signal = input.get('signal')
                        signal_scale = input.get('signal_scale', 0)
                        if signal is not None and signal_scale > 0:
                            if signal_scale == 1:  # Relative (65535 = 100%)
                                signal_value = f"{(signal * 100 / 65535):.1f}%"
                            elif signal_scale == 2:  # Absolute (1000 = 1dB)
                                signal_value = f"{(signal / 1000):.1f} dB"
                            else:
                                signal_value = "N/A"
                        else:
                            signal_value = "N/A"
                        
                        signal_item = QTableWidgetItem(signal_value)
                        self.signal_table.setItem(base_row, 1, signal_item)
                        self.signal_table.setItem(base_row, 2, QTableWidgetItem("Signal"))
                        
                        # SNR row
                        snr = input.get('snr')
                        snr_scale = input.get('snr_scale', 0)
                        if snr is not None and snr_scale > 0:
                            if snr_scale == 1:  # Relative (65535 = 100%)
                                snr_value = f"{(snr * 100 / 65535):.1f}%"
                            elif snr_scale == 2:  # Absolute (1000 = 1dB)
                                snr_value = f"{(snr / 1000):.1f} dB"
                            else:
                                snr_value = "N/A"
                        else:
                            snr_value = "N/A"
                        
                        snr_item = QTableWidgetItem(snr_value)
                        self.signal_table.setItem(base_row + 1, 1, snr_item)
                        self.signal_table.setItem(base_row + 1, 2, QTableWidgetItem("SNR"))
                        
                        # Stream and Weight info (spans both rows)
                        self.signal_table.setItem(base_row, 3, QTableWidgetItem(str(input.get('stream', 'N/A'))))
                        self.signal_table.setItem(base_row, 4, QTableWidgetItem(str(input.get('weight', 'N/A'))))
                        self.signal_table.setSpan(base_row, 3, 2, 1)  # Span 2 rows for stream
                        self.signal_table.setSpan(base_row, 4, 2, 1)  # Span 2 rows for weight
                        
                        # Color coding for signal and SNR
                        self.color_code_cell(signal_item, signal, signal_scale, 'signal')
                        self.color_code_cell(snr_item, snr, snr_scale, 'snr')
            except Exception as e:
                print(f"Debug: Error updating signal status: {str(e)}")

            # 3. Update Active Streams Tab
            try:
                connections = self.backend.get_connections() or []
                subscriptions = self.backend.get_subscriptions() or []
                if connections is not None:
                    
                    # Calculate total rows needed (connections + subscriptions)
                    total_rows = len(connections) + len(subscriptions)
                    self.subscriptions_table.setRowCount(total_rows)
                    
                    # Add connections
                    row = 0
                    for conn in connections:
                        # Peer (IP address/hostname)
                        peer = conn.get('peer', 'Unknown')
                        self.subscriptions_table.setItem(row, 0, QTableWidgetItem(str(peer)))
                        self.subscriptions_table.setItem(row, 1, QTableWidgetItem(str(conn.get('user', 'N/A'))))
                        
                        # Start time
                        start = datetime.fromtimestamp(conn.get('started', 0)).strftime('%H:%M:%S')
                        self.subscriptions_table.setItem(row, 2, QTableWidgetItem(start))
                        
                        # Duration
                        duration = int(time.time() - conn.get('started', 0))
                        hours = duration // 3600
                        minutes = (duration % 3600) // 60
                        seconds = duration % 60
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        self.subscriptions_table.setItem(row, 3, QTableWidgetItem(duration_str))
                        
                        # Type/Status
                        self.subscriptions_table.setItem(row, 4, QTableWidgetItem("Connection"))
                        
                        row += 1
                    
                    # Add subscriptions
                    for sub in subscriptions:
                        # Channel/Service name
                        channel = sub.get('channel', 'Unknown')
                        if isinstance(channel, dict):
                            channel = channel.get('name', 'Unknown')
                        self.subscriptions_table.setItem(row, 0, QTableWidgetItem(str(channel)))
                        self.subscriptions_table.setItem(row, 1, QTableWidgetItem(str(sub.get('username', 'N/A'))))
                        
                        # Start time
                        start = datetime.fromtimestamp(sub.get('start', 0)).strftime('%H:%M:%S')
                        self.subscriptions_table.setItem(row, 2, QTableWidgetItem(start))
                        
                        # Duration
                        duration = int(time.time() - sub.get('start', 0))
                        hours = duration // 3600
                        minutes = (duration % 3600) // 60
                        seconds = duration % 60
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        self.subscriptions_table.setItem(row, 3, QTableWidgetItem(duration_str))
                        
                        # Type/Status
                        status = f"Subscription ({sub.get('state', 'Unknown')})"
                        self.subscriptions_table.setItem(row, 4, QTableWidgetItem(status))
                        
                        row += 1

            except Exception as e:
                print(f"Debug: Error fetching connections/subscriptions: {str(e)}")

        except Exception as e:
            print(f"Debug: Error in update_status: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")

    def color_code_cell(self, item, value, scale, type='signal'):
        """Color a signal cell and add a quality word so color is not the only cue."""
        if value is None or scale <= 0:
            return
        if scale == 1:
            quality = (value * 100 / 65535)
        elif type == 'signal':
            quality = min(100, max(0, (value / 1000 + 15) * 6.67))
        else:
            quality = min(100, max(0, (value / 1000 - 10) * 10))

        phrase = quality_phrase(quality)
        reading = f"{item.text()} ({phrase})"
        item.setText(reading)
        kind = "Signal" if type == "signal" else "SNR"
        set_item_access(item, reading, f"{kind} quality is {phrase}")
        if prefers_high_contrast():
            return
        background, foreground = quality_colors(quality)
        item.setBackground(background)
        item.setForeground(foreground)
    
    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)

class PlaybackSpinner(QWidget):
    """Ring drawn over the player until the first picture arrives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self._caption = STARTING
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # The video surface is a native window; a plain widget would be drawn underneath it.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background-color: black;")
        self.hide()

    def set_caption(self, text):
        self._caption = text or STARTING
        self.setAccessibleName(self._caption)
        self.update()

    def set_running(self, running):
        if running:
            if not self._timer.isActive():
                self._timer.start()
            self.show()
            self.raise_()
        else:
            self._timer.stop()
            self.hide()

    def _advance(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        span = min(self.width(), self.height())
        diameter = max(36, min(72, span // 6 if span else 36))
        thickness = max(4, diameter // 10)
        rect = QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter,
            diameter,
        )
        track = QPen(QColor(255, 255, 255, 50), thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)
        arc = QPen(QColor(255, 255, 255, 235), thickness)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        painter.drawArc(rect, int(-self._angle * 16), int(110 * 16))
        painter.setPen(QColor(255, 255, 255, 230))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        caption = QRectF(16, rect.bottom() + 12, max(0, self.width() - 32), 48)
        painter.drawText(
            caption,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self._caption,
        )
        painter.end()


class BusyRing(QWidget):
    """Small spinning ring in the theme's text color. It only turns while shown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(36, 36)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        thickness = 4
        rect = QRectF(self.rect()).adjusted(thickness, thickness, -thickness, -thickness)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        track = QColor(color)
        track.setAlpha(50)
        pen = QPen(track, thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        pen.setColor(color)
        painter.setPen(pen)
        painter.drawArc(rect, int(-self._angle * 16), int(110 * 16))
        painter.end()


class ChannelListState(QWidget):
    """Shown in place of the channel list while it loads, when it is empty, or when loading failed."""

    retry = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addStretch(1)
        self.ring = BusyRing(self)
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        self.retry_btn = QPushButton("&Retry", self)
        self.retry_btn.clicked.connect(self.retry)
        describe(self.retry_btn, description="Try to load the channel list again")
        layout.addWidget(self.retry_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)

    def show_state(self, text, busy=False, retry=False):
        self.ring.setVisible(busy)
        self.retry_btn.setVisible(retry)
        announce_label(self.message, text)


class ChannelFetch(QObject):
    """Fetch a server's channels and what is shown beside them, off the UI thread.

    It uses its own backend connection, so it never shares one with the window.
    Exactly one of loaded or failed is emitted.
    """

    loaded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, server, kinds, now_next, open_backend=create_backend, parent=None):
        super().__init__(parent)
        self.server = dict(server)
        self.key = server_key(self.server)
        self._kinds = kinds
        self._now_next = now_next
        self._open_backend = open_backend
        self._thread = threading.Thread(target=self._run, name='channel-fetch', daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        backend = None
        try:
            backend = self._open_backend(self.server)
            channels = backend.get_channels()
            # Everything after the channels is optional. A server that refuses
            # one (the service grid needs admin rights) leaves that part empty.
            result = {'channels': channels, 'tags': [], 'services': [], 'now_next': {}}
            try:
                result['tags'] = [tag for tag in backend.list_channel_tags() if tag.enabled]
            except Exception as e:
                print(f"Debug: Could not load channel tags: {e}")
            if self._kinds:
                try:
                    result['services'] = backend.list_channel_services()
                except Exception as e:
                    print(f"Debug: Could not load channel services: {e}")
            if self._now_next and channels:
                try:
                    result['now_next'] = backend.get_now_next(channels)
                except Exception as e:
                    # None keeps what was shown before.
                    result['now_next'] = None
                    print(f"Debug: Could not load now and next: {e}")
        except Exception as e:
            print(f"Debug: Could not fetch channels: {e}")
            self.failed.emit(str(e) or type(e).__name__)
            return
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
        self.loaded.emit(result)


class StartWatch(QObject):
    """Follow the server's status for a channel that is starting, off the UI thread.

    It uses its own backend connection, so it never shares one with the window.
    """

    caption = pyqtSignal(str)
    give_up = pyqtSignal()

    def __init__(self, server, channel_name, parent=None):
        super().__init__(parent)
        self._server = dict(server)
        self._name = channel_name
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name='start-watch', daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stopped.set()

    def _run(self):
        backend = None
        started = time.monotonic()
        retried = False
        last = None
        try:
            backend = create_backend(self._server)
            while not self._stopped.is_set():
                try:
                    subscription = find_subscription(backend.get_subscriptions(), self._name)
                except Exception:
                    subscription = None
                retried = retried or (subscription is not None and subscription.state == 'Bad')
                text, done = starting_caption(subscription, time.monotonic() - started, retried)
                if self._stopped.is_set():
                    break
                if text != last:
                    last = text
                    self.caption.emit(text)
                if done:
                    self.give_up.emit()
                    break
                self._stopped.wait(1.0)
        except Exception as exc:
            print(f"Debug: Start status unavailable: {exc}")
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass


class ServerLogWatch(QObject):
    """Read a remote server's live log off the UI thread."""

    lines = pyqtSignal(list)
    # Text for the note above the log; empty when there is nothing to say.
    note = pyqtSignal(str)

    RETRY_SECONDS = 5

    def __init__(self, server):
        super().__init__()
        self._server = dict(server)
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name='server-log', daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stopped.set()

    def _run(self):
        feed = None
        try:
            feed = ServerLogFeed(self._server)
            failing = False
            while not self._stopped.is_set():
                try:
                    poll = feed.poll()
                except TvhAuthError:
                    self.note.emit(
                        "The server did not accept this sign-in. "
                        "Check the username and password in the server settings."
                    )
                    break
                except Exception as exc:
                    if not failing:
                        print(f"Debug: Server log unavailable: {exc}")
                    failing = True
                    self.note.emit("Cannot reach the server. Trying again every few seconds.")
                    self._stopped.wait(self.RETRY_SECONDS)
                    continue
                if self._stopped.is_set():
                    break
                if poll.admin is False:
                    self.note.emit(
                        "This account is not an administrator on the server, and "
                        "Tvheadend only sends its log to administrators. "
                        "Sign in with an admin account in the server settings to see it."
                    )
                    break
                if poll.admin or failing:
                    failing = False
                    self.note.emit("")
                if poll.lines:
                    self.lines.emit(poll.lines)
        except Exception as exc:
            self.note.emit(f"Cannot show this server's log: {exc}")
        finally:
            if feed is not None:
                feed.close()


class ServerLogDialog(QDialog):
    """A remote server's live log, from when the window opens until it closes."""

    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Server log: {server.get('name') or server.get('url')}")
        layout = QVBoxLayout(self)
        about = QLabel(
            "Messages appear here as the server logs them, starting when this window opened."
        )
        about.setWordWrap(True)
        layout.addWidget(about)
        self.note = QLabel("Connecting…")
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.note)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        describe(self.view, "Server log", "Log messages from the server, newest at the bottom")
        layout.addWidget(self.view)
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        self.resize(760, 420)

        self._watch = ServerLogWatch(server)
        self._watch.note.connect(self.show_note)
        self._watch.lines.connect(self.add_lines)
        self.finished.connect(self._stop_watch)
        self._watch.start()

    def show_note(self, text):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def add_lines(self, lines):
        bar = self.view.verticalScrollBar()
        at_end = bar.value() == bar.maximum()
        for line in lines:
            self.view.appendPlainText(line)
        if at_end:
            bar.setValue(bar.maximum())

    def _stop_watch(self):
        self._watch.stop()
        self._watch.note.disconnect(self.show_note)
        self._watch.lines.disconnect(self.add_lines)


class TVHeadendClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setup_paths()
        self.config_store = ConfigStore()
        self.config_file = str(self.config_store.path)
        self.config_dir = str(self.config_store.path.parent)
        self.config = self.config_store.data
        print(f"Debug: Config file location: {self.config_file}")
        print(
            f"Debug: Config has {len(self.config.get('servers') or [])} servers and "
            f"{len(self.config.get('playlists') or [])} playlists"
        )
        print("Debug: Initializing TVHeadendClient")
        
        # Initialize fullscreen state        
        # Rest of initialization code...


        # Set window title and geometry from config
        self.setWindowTitle("TVHplayer")
        app = QApplication.instance()
        if app is not None:
            app.setApplicationName("TVHplayer")
            app.setApplicationDisplayName("TVHplayer")
            if not app.desktopFileName():
                app.setDesktopFileName("io.github.mfat.tvhplayer")
        geometry = self.config.get('window_geometry', {'x': 100, 'y': 100, 'width': 1200, 'height': 700})
        self.setGeometry(
            geometry['x'],
            geometry['y'],
            geometry['width'],
            geometry['height']
        )
        
        # Initialize servers from config
        self.servers = ensure_builtin_server(
            self.config_store.servers,
            self.config.get('builtin_http_port') or 0,
            self.config.get('builtin_htsp_port') or 0,
        )
        self._backend = None
        self._backend_key = None
        self._busy_playlists = set()
        self._builtin_playlists_refreshed = False
        self._playlist_jobs = []
        self._closing = False
        # A playlist check shows and hides channels for hours; reload the list at most this often.
        self._channel_reload_timer = QTimer(self)
        self._channel_reload_timer.setSingleShot(True)
        self._channel_reload_timer.timeout.connect(self._reload_changed_channels)
        self._last_channel_reload = 0.0
        # Extras shown beside each channel, keyed by channel_key().
        self._channels = []
        # server_key() of the server _channels came from, and the fetch still running.
        self._channels_server = None
        self._channel_fetch = None
        self._channel_tags = []
        self._now_next = {}
        self._now_next_fetched = 0.0
        self._channel_kinds = {}
        self._recording_keys = set()
        self._logo_pixmaps = {}
        self._logo_server = None
        self.logo_loader = LogoLoader(self)
        self.logo_loader.loaded.connect(self._on_logo_loaded)
        self._now_next_timer = QTimer(self)
        self._now_next_timer.timeout.connect(self._tick_now_next)
        self._now_next_timer.start(NOW_NEXT_TICK_MS)
        self.local_recorder = LocalRecorder()
        self.builtin = None
        if platform_supports_builtin():
            self.builtin = BuiltinSupervisor(
                find_bundled_binary(),
                builtin_config_dir(self.config_dir),
                self.config.get('builtin_http_port') or 0,
                self.config.get('builtin_htsp_port') or 0,
            )
            self.builtin.ready.connect(self._on_builtin_ready)
            self.builtin.failed.connect(self._on_builtin_failed)
        print(f"Debug: Loaded {len(self.servers)} servers")
        
        # Initialize channels list
        self.channels = []
        
        self.is_fullscreen = False
        self._pre_fullscreen_state = None
        self._playback_active = False
        self._awaiting_playback = False
        self._playback_channel = None
        self._video_menu = None

        
        # Add recording indicator variables
        self.recording_indicator_timer = None
        self.recording_indicator_visible = False
        self.is_recording = False
        self.recording_animation = None
        self.opacity_effect = None
        
        print("Debug: Initializing VLC instance")
        try:
            self.player = VlcPlayer()
            print("Debug: VLC media player created successfully")
        except Exception as e:
            print(f"Error initializing VLC: {str(e)}")
            raise RuntimeError(f"Failed to initialize VLC: {str(e)}")

        # Then setup UI
        self.setup_ui()
        self._bind_playback_splash()

        # Update to use config for last server
        last_server = self.config.get('last_server', 0)
        if self.servers and 0 <= last_server < len(self.servers):
            self.server_combo.setCurrentIndex(last_server)
        if self.builtin is not None and self.config.get('builtin_autostart'):
            self.builtin.start()

        try:
            self.player.attach(self.video_frame.winId().__int__())
            self.hw_check_timer = QTimer()
            self.hw_check_timer.setSingleShot(True)
            self.hw_check_timer.timeout.connect(self.player.log_stats)
            self.hw_check_timer.start(5000)
            print("Debug: Hardware acceleration configured for VLC")
        except Exception as e:
            print(f"Warning: Could not configure hardware acceleration: {str(e)}")
            print("Continuing without hardware acceleration")
    
    def setup_paths(self):
        """Setup application paths for resources"""
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle
            self.app_dir = Path(sys._MEIPASS)
        else:
            # Running in development
            self.app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
            
        # Ensure icons directory exists
        self.icons_dir = self.app_dir / 'icons'
        if not self.icons_dir.exists():
            print(f"Warning: Icons directory not found at {self.icons_dir}")
            # Try looking up one directory (in case we're in src/)
            self.icons_dir = self.app_dir.parent / 'icons'
            if not self.icons_dir.exists():
                # Try system icon directories
                system_icon_dirs = []
                if sys.platform.startswith('linux'):
                    system_icon_dirs = [
                        Path('/usr/share/icons/tvhplayer'),
                        Path('/usr/local/share/icons/tvhplayer'),
                        Path(os.path.expanduser('~/.local/share/icons/tvhplayer'))
                    ]
                elif sys.platform == 'darwin':
                    system_icon_dirs = [
                        Path('/System/Library/Icons'),
                        Path('/Library/Icons'),
                        Path(os.path.expanduser('~/Library/Icons'))
                    ]
                elif sys.platform == 'win32':
                    system_icon_dirs = [
                        Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'Icons',
                        Path(os.environ['SYSTEMROOT']) / 'System32' / 'icons'
                    ]
                
                for dir in system_icon_dirs:
                    if dir.exists():
                        self.icons_dir = dir
                        print(f"Using system icons directory: {self.icons_dir}")
                        break
                else:
                    raise RuntimeError(f"Icons directory not found in {self.app_dir}, parent directory, or system locations")
        
        print(f"Debug: Using icons directory: {self.icons_dir}")
        
    def get_icon(self, icon_name):
        """Get icon path and verify it exists"""
        # setup_paths found the folder: next to the code in packages, one up in a checkout.
        icon_path = Path(self.icons_dir) / icon_name
        if not icon_path.exists():
            print(f"Warning: Icon not found: {icon_path}")
            return None
        return str(icon_path)
    
    def setup_ui(self):
        """Setup the UI elements"""

        
        

        
        self.setAccessibleName("TVHplayer")
        self.setAccessibleDescription(
            "Watch and record TVHeadend channels. "
            "Press F11 or F for fullscreen, Ctrl+F to search, and F1 for keyboard shortcuts."
        )

        # Create menu bar
        menubar = self.menuBar()
        menubar.setAccessibleName("Main menu")
        file_menu = menubar.addMenu("&File")
        view_menu = menubar.addMenu("&View")
        help_menu = menubar.addMenu("&Help")

        # Add User Guide action to Help menu
        user_guide_action = QAction("User &Guide", self)
        user_guide_action.setStatusTip("Open the TVHplayer user guide in a browser")
        user_guide_action.triggered.connect(self.show_user_guide)
        help_menu.addAction(user_guide_action)

        shortcuts_action = QAction("Keyboard &Shortcuts", self)
        shortcuts_action.setShortcut("F1")
        shortcuts_action.triggered.connect(self.show_keyboard_shortcuts)
        help_menu.addAction(shortcuts_action)
        
        log_folder_action = QAction("Open &Log Folder", self)
        log_folder_action.triggered.connect(self.open_log_folder)
        help_menu.addAction(log_folder_action)

        # Add About action to Help menu
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        # F11 is the menu shortcut. Plain F is handled when it will not interrupt typing.
        self.fullscreen_action = QAction("Fullscreen", self)
        self.fullscreen_action.setShortcut("F11")
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(self.fullscreen_action)

        import_playlist_action = QAction("&Import Playlist…", self)
        import_playlist_action.setShortcut("Ctrl+I")
        import_playlist_action.triggered.connect(self.import_playlist)
        file_menu.addAction(import_playlist_action)
        playlists_action = QAction("&Playlists…", self)
        playlists_action.triggered.connect(self.show_playlists)
        file_menu.addAction(playlists_action)
        file_menu.addSeparator()
        settings_action = QAction("&Settings…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()

        # Create actions
        exit_action = QAction("E&xit", self)
        if sys.platform == "darwin":  # macOS
            exit_action.setShortcut("Cmd+Q")
        else:  # Windows/Linux
            exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create splitter for resizable panes
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left pane
        self.left_pane = QFrame()
        self.left_pane.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Raised)
        self.left_pane.setAccessibleName("Channels")
        left_layout = QVBoxLayout(self.left_pane)
        
        # Server selection with add/remove buttons
        server_layout = QHBoxLayout()
        self.server_combo = QComboBox()
        self.server_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for server in self.servers:
            self.server_combo.addItem(server['name'])
        
        # Connect server combo box change signal
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        describe(self.server_combo, description="TVHeadend server used for the channel list")
        
        self.manage_servers_btn = QToolButton()
        self.manage_servers_btn.clicked.connect(self.manage_servers)
        
        server_layout.addWidget(buddy_label("&Server:", self.server_combo))
        server_layout.addWidget(self.server_combo)
        self.manage_servers_btn.setText("⚙️")  # Unicode settings icon
        if not prefers_high_contrast():
            self.manage_servers_btn.setStyleSheet(
                "QToolButton { font-size: 18px; } "
                "QToolButton:focus { border: 2px solid palette(highlight); }"
            )
        describe(
            self.manage_servers_btn,
            "Manage servers",
            "Add, edit, or remove TVHeadend servers",
        )
        self.manage_servers_btn.setToolTip("Manage servers")
        server_layout.addWidget(self.manage_servers_btn)
        left_layout.addLayout(server_layout)
        
    

        # Channel list. Which columns show, their order, logos, and the group
        # filter are user settings kept under channel_list in the config.
        self.channel_options = channel_list_options(self.config.get('channel_list'))
        self.channel_list = QTableWidget()
        self.channel_list.setColumnCount(len(COLUMN_TITLES))
        self.channel_list.setHorizontalHeaderLabels(
            [COLUMN_TITLES[column] for column in range(len(COLUMN_TITLES))]
        )
        describe(
            self.channel_list,
            "Channels",
            "Channel numbers, names, what is on now, and playing status. Type to jump to a channel. "
            "Press Enter to play. Press Shift+F10 for more actions.",
        )
        header = self.channel_list.horizontalHeader()
        for column in (COL_NUMBER, COL_STATUS, COL_TYPE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (COL_NAME, COL_NOW, COL_NEXT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        header.setSectionsMovable(True)
        header.sectionMoved.connect(self._channel_columns_moved)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_channel_column_menu)
        header.setToolTip("Drag a column to move it. Right-click to choose columns.")
        self.channel_list.setWordWrap(False)
        self.channel_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.channel_list.setIconSize(LOGO_SIZE)
        self._progress_delegate = ProgressDelegate(self.channel_list)
        self.channel_list.setItemDelegateForColumn(COL_NOW, self._progress_delegate)
        self.channel_list.verticalHeader().setVisible(False)
        self.channel_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Stop recording follows the highlighted channel.
        self.channel_list.currentCellChanged.connect(lambda *_: self._sync_record_controls())
        self.channel_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.channel_list.setSortingEnabled(True)
        self.channel_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        # Connect double-click to play
        self.channel_list.itemDoubleClicked.connect(self.play_channel_from_table)
        
        # Connect context menu
        self.channel_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_list.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.channel_list.installEventFilter(self)
        
        # A thin bar shows a reload while the old list stays usable. A first
        # load, an empty list, or a failure shows a page in place of the list.
        self.channel_busy = QProgressBar()
        self.channel_busy.setRange(0, 0)
        self.channel_busy.setTextVisible(False)
        self.channel_busy.setFixedHeight(4)
        describe(self.channel_busy, "Refreshing channels")
        self.channel_busy.hide()
        left_layout.addWidget(self.channel_busy)
        self.channel_state = ChannelListState()
        self.channel_state.retry.connect(lambda: self.fetch_channels())
        self.channel_stack = QStackedWidget()
        self.channel_stack.addWidget(self.channel_list)
        self.channel_stack.addWidget(self.channel_state)
        left_layout.addWidget(self.channel_stack)
        self._build_channel_list_menu(view_menu)

        # Channel group (Tvheadend channel tag) filter. Built here because the
        # first channel load runs before the rest of the pane; it sits under
        # the search box.
        self.tag_row = QWidget(self.left_pane)
        tag_layout = QHBoxLayout(self.tag_row)
        tag_layout.setContentsMargins(0, 0, 0, 5)
        tag_layout.setSpacing(5)
        self.tag_combo = QComboBox()
        self.tag_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tag_combo.addItem("All channels", "")
        self.tag_combo.currentIndexChanged.connect(self._on_channel_tag_changed)
        describe(
            self.tag_combo,
            description="Show only the channels in one group. Groups are the channel tags set on the server.",
        )
        tag_layout.addWidget(buddy_label("&Group:", self.tag_combo))
        tag_layout.addWidget(self.tag_combo, 1)
        self.tag_row.setVisible(False)
        
        # Right pane
        self.right_pane = QFrame()
        self.right_pane.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Raised)
        self.right_pane.setAccessibleName("Player")
        self.right_layout = QVBoxLayout(self.right_pane)
        self.right_layout.setObjectName("right_layout")
        
        # VLC draws into video_frame. Keep that surface free of the splash
        # image so Qt repaints do not flash the logo over live video.
        self.player_container = QWidget()
        self.player_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.player_container.setStyleSheet("background-color: black;")
        player_layout = QVBoxLayout(self.player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(0)

        self.video_frame = QWidget()
        self.video_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_frame.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Pointer movement brings back the floating bar in fullscreen.
        self.video_frame.setMouseTracking(True)
        describe(
            self.video_frame,
            "Video player",
            "Playback picture. F or F11 toggles fullscreen, Escape leaves fullscreen, "
            "M mutes, P plays, and Ctrl+. stops. Shift+F10 opens the playback menu.",
        )
        self.video_frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_frame.customContextMenuRequested.connect(self.show_video_context_menu)
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        splash_path = Path(self.icons_dir) / 'playerbg.svg'
        self.idle_splash = QLabel(self.player_container)
        self.idle_splash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.idle_splash.setStyleSheet(
            f"background-color: black; "
            f"background-image: url({splash_path.as_posix()}); "
            "background-position: center; "
            "background-repeat: no-repeat;"
        )
        self.idle_splash.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.idle_splash.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        describe(self.idle_splash, "Nothing playing", "TVHplayer logo, shown when nothing is playing")

        self.playback_spinner = PlaybackSpinner(self.player_container)
        describe(
            self.playback_spinner,
            "Starting playback",
            "Shown from the moment a channel is opened until the picture starts",
        )

        player_layout.addWidget(self.video_frame)
        self.player_container.installEventFilter(self)
        self.right_layout.addWidget(self.player_container, 1)
        self._set_idle_splash(True)
        
        # Player controls, joined to the bottom of the picture.
        self.right_layout.setSpacing(0)
        self.controls_bar = PlayerBar()
        bar = self.controls_bar
        self.play_btn = bar.play_btn
        self.play_btn.clicked.connect(self.toggle_playback)
        self.record_btn = bar.record_btn
        self.stop_record_btn = bar.stop_record_btn
        self.stop_record_btn.clicked.connect(self.stop_any_recording)
        self.record_more_btn = bar.record_more_btn
        bar.record_server_action.triggered.connect(self.start_recording)
        bar.record_local_action.triggered.connect(
            lambda: self.start_local_recording(self.selected_channel())
        )
        bar.stop_server_action.triggered.connect(self.stop_recording)
        bar.stop_local_action.triggered.connect(self.stop_local_recording)
        bar.stop_both_action.triggered.connect(self.stop_both_recordings)

        self.mute_btn = bar.mute_btn
        self.mute_btn.clicked.connect(self.toggle_mute)
        describe(self.mute_btn, "Mute", "Turn sound off. Keyboard: M. The button stays pressed while muted.")
        self.mute_btn.setToolTip("Mute (M)")

        self.volume_slider = bar.volume_slider
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        describe(self.volume_slider, "Volume", "Playback volume from 0 to 100. Keyboard: Ctrl+Up and Ctrl+Down.")
        self.volume_slider.setToolTip("Volume")

        self.fullscreen_btn = bar.fullscreen_btn
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        describe(self.fullscreen_btn, "Fullscreen", "Fill the screen with the picture. Keyboard: F11 or F. Escape leaves fullscreen.")
        self.fullscreen_btn.setToolTip("Fullscreen (F11)")
        self.right_layout.addWidget(self.controls_bar)
        # In fullscreen the bar moves into this window, over the picture.
        self.floating_bar = FloatingBar(self)
        
        # Add panes to splitter instead of layout
        self.tasks_pane = TasksPanel(self)
        self.splitter.addWidget(self.left_pane)
        self.splitter.addWidget(self.right_pane)
        self.splitter.addWidget(self.tasks_pane)
        self.splitter.setAccessibleName("Channels, player, and tasks")
        self._name_splitter_handles()

        self.tasks_action = QAction("&Tasks", self)
        self.tasks_action.setCheckable(True)
        self.tasks_action.setChecked(True)
        self.tasks_action.setStatusTip("Show or hide ongoing and scheduled recordings")
        self.tasks_action.triggered.connect(self._toggle_tasks_pane)
        view_menu.addAction(self.tasks_action)
        self.tasks_pane.close_requested.connect(self._close_tasks_pane)
        
        # Set initial sizes (optional)
        self.splitter.setSizes([300, 640, 260])
        
        # Add splitter to main layout
        layout.addWidget(self.splitter)
        self.main_layout = layout
        
        
        # Buttons removed
        
        # Status bar setup
        self.statusbar = QStatusBar()
        self.statusbar.setAccessibleName("Status bar")
        self.setStatusBar(self.statusbar)
        
        # Create a container widget for status bar items
        status_container = QWidget()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(10)  # Space between indicator and text
        
        # Text plus a dark-red badge, so recording state is not color alone.
        self.recording_indicator = QLabel("")
        self.recording_indicator.setVisible(False)
        self.recording_indicator.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if not prefers_high_contrast():
            self.recording_indicator.setStyleSheet(
                "QLabel { background-color: #7f1d1d; color: #ffffff; "
                "font-weight: bold; padding: 1px 6px; border-radius: 8px; }"
            )
        describe(self.recording_indicator, "Not recording", "Shown only while a recording is in progress")
        
        # Create status message label
        self.status_label = QLabel("Ready")
        describe(self.status_label, "Ready", "Application status")
        
        # Add widgets to horizontal layout
        status_layout.addWidget(self.recording_indicator)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()  # This pushes everything to the left
        
        # Add the container to the status bar
        self.statusbar.addWidget(status_container)
        
        # Override showMessage to update our custom label
        def custom_show_message(message, timeout=0):
            announce_label(self.status_label, message)
        self.statusbar.showMessage = custom_show_message
        
        # Initialize
        self.fetch_channels()
        
        # Connect channel list double click to play
        
        # Add event filter to video frame for double-click
        self.video_frame.installEventFilter(self)
        
        # Add Server Status to View menu
        server_status_action = view_menu.addAction("Server &Status")
        server_status_action.setStatusTip("Show connections, signal quality, and server information")
        server_status_action.triggered.connect(self.show_server_status)
        
        # Add DVR Status to View menu
        dvr_status_action = view_menu.addAction("&DVR Status")
        dvr_status_action.setStatusTip("Show scheduled, finished, and failed recordings")
        dvr_status_action.triggered.connect(self.show_dvr_status)
        
        # Add search box before styling it
        search_layout = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Channel name")
        self.search_box.textChanged.connect(self.filter_channels)
        self.search_box.setClearButtonEnabled(True)
        describe(
            self.search_box,
            description="Filter the channel list. Ctrl+F moves here, and so does S when the list is not focused.",
        )
        
        search_shortcut = QShortcut(find_shortcut(), self)
        search_shortcut.setObjectName("focus-search")
        search_shortcut.activated.connect(self._focus_search)
        
        search_layout.addWidget(buddy_label("&Search:", self.search_box))
        search_layout.addWidget(self.search_box)
        left_layout.addLayout(search_layout)  # Add to left pane layout
        
        # Add margins to search layout
        search_layout.setContentsMargins(0, 5, 0, 5)
        search_layout.setSpacing(5)

        left_layout.addWidget(self.tag_row)
        self._apply_channel_columns()
        self._apply_tab_order()
        self.tasks_pane.refresh()

    def _apply_tab_order(self):
        """Follow the visual order: server, channels, search, picture, then controls."""
        order = [
            self.server_combo,
            self.manage_servers_btn,
            self.channel_list,
            self.channel_state.retry_btn,
            self.search_box,
            self.tag_combo,
            self.video_frame,
            self.play_btn,
            self.record_btn,
            self.stop_record_btn,
            self.record_more_btn,
            self.mute_btn,
            self.volume_slider,
            self.fullscreen_btn,
            self.tasks_pane.search_box,
            self.tasks_pane.status_combo,
            self.tasks_pane.task_table,
            self.tasks_pane.action_btn,
            self.tasks_pane.reveal_btn,
            self.tasks_pane.close_btn,
        ]
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)

    def _focus_search(self):
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()

    def show_keyboard_shortcuts(self):
        ShortcutHelpDialog(self).exec()

    def _blocks_plain_keys(self):
        """Letter keys belong to text fields and to channel type-ahead."""
        widget = QApplication.focusWidget()
        if widget is None:
            return False
        if isinstance(widget, (QLineEdit, QTextEdit, QSpinBox, QComboBox)):
            return True
        return widget is self.channel_list or self.channel_list.isAncestorOf(widget)

    def _is_context_menu_key(self, event):
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ):
            return False
        if event.key() == Qt.Key.Key_Menu:
            return True
        return (
            event.key() == Qt.Key.Key_F10
            and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        )

    def _adjust_volume(self, delta):
        value = max(0, min(100, self.volume_slider.value() + delta))
        self.volume_slider.setValue(value)
        self.statusbar.showMessage(f"Volume {value}")

    def _channel_menu_position(self):
        row = self.channel_list.currentRow()
        if row < 0:
            return QPoint(0, 0)
        rect = self.channel_list.visualRect(self.channel_list.model().index(row, 1))
        return rect.center()

    def current_server(self):
        if not self.servers:
            return None
        index = self.server_combo.currentIndex()
        if index < 0 or index >= len(self.servers):
            return None
        return self.servers[index]

    def close_backend(self):
        backend = getattr(self, '_backend', None)
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass
        self._backend = None
        self._backend_key = None

    def _server_requests_ready(self):
        server = self.current_server()
        supervisor = getattr(self, 'builtin', None)
        running = supervisor is not None and supervisor.is_running()
        return builtin_requests_ready(server, running)

    def get_backend(self):
        server = self.current_server()
        if not server:
            raise TvhError('No server selected')
        if is_builtin_server(server) and not self._server_requests_ready():
            raise TvhError('Built-in server is not running yet')
        key = (
            server.get('url'),
            (server.get('protocol') or PROTOCOL_HTTP).lower(),
            server.get('username') or '',
            server.get('password') or '',
            int(server.get('htsp_port') or 9982),
        )
        if self._backend is None or self._backend_key != key:
            self.close_backend()
            self._backend = create_backend(server)
            self._backend_key = key
        return self._backend

    def channel_from_row(self, row):
        if row is None or row < 0:
            return None
        item = self.channel_list.item(row, 1)
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return None
        if isinstance(data, Channel):
            return data
        return Channel.from_raw(data)

    def selected_channel(self):
        channel = self.channel_from_row(self.channel_list.currentRow())
        if channel:
            return channel
        if self.channel_list.rowCount() > 0:
            return self.channel_from_row(0)
        return None

    def active_channel(self):
        """Channel the record controls apply to.

        The highlighted row wins. With no highlight, use the channel that is playing.
        """
        row = self.channel_list.currentRow()
        if row >= 0:
            channel = self.channel_from_row(row)
            if channel:
                return channel
        return getattr(self, '_playback_channel', None)

    def _channels_match(self, left, right):
        if left is None or right is None:
            return False
        if left.uuid and right.uuid and str(left.uuid) == str(right.uuid):
            return True
        return left.htsp_id is not None and left.htsp_id == right.htsp_id

    def _playing_channel(self):
        """Channel that should show as playing, or None when playback is idle."""
        channel = getattr(self, '_playback_channel', None)
        if channel is None:
            return None
        if getattr(self, '_playback_active', False) or getattr(self, '_awaiting_playback', False):
            return channel
        return None

    def _channel_description(self, channel, is_playing=False, is_recording=False):
        description = f"Channel {channel.number}, {channel.name}."
        if is_playing:
            description += " Playing."
        if is_recording:
            description += " Recording."
        now_next = self._now_next.get(channel_key(channel))
        if now_next is not None and now_next.now is not None:
            description += f" Now: {now_next.now.title}."
        description += " Press Enter to play."
        return description

    def _set_channel_row_playing(self, row, channel, is_playing, colors, is_recording=False):
        table = self.channel_list
        status_item = table.item(row, COL_STATUS)
        if status_item is None:
            status_item = QTableWidgetItem()
            table.setItem(row, COL_STATUS, status_item)
        parts = []
        if is_playing:
            parts.append("Playing")
        if is_recording:
            parts.append("Recording")
        status = ", ".join(parts)
        if status_item.text() != status:
            status_item.setText(status)
        if status and channel is not None:
            set_item_access(status_item, status, f"{channel.name}: {status.lower()}")
        else:
            status_item.setData(Qt.ItemDataRole.AccessibleTextRole, None)
            status_item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, None)
            status_item.setToolTip("")
        if not is_playing and is_recording:
            colors = row_emphasis('recording')
        emphasize = (is_playing or is_recording) and colors is not None
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is None:
                continue
            if emphasize:
                item.setBackground(colors[0])
                item.setForeground(colors[1])
            else:
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
        name_item = table.item(row, COL_NAME)
        if name_item is None or channel is None:
            return
        set_item_access(
            name_item,
            channel.name,
            self._channel_description(channel, is_playing, is_recording),
        )

    def _mark_playing_channel(self, scroll=False):
        """Highlight the channel that is on, and write Playing in its status cell.

        Selection can move to another row. The playing row keeps its own color
        and status so the list still shows what is on. Channels the server is
        recording say so too, unless the user turned that off.
        """
        table = getattr(self, 'channel_list', None)
        if table is None:
            return
        playing = self._playing_channel()
        colors = row_emphasis('playing' if playing is not None else None)
        recording = self._recording_keys if self.channel_options['recording_status'] else set()
        sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)
        playing_item = None
        try:
            for row in range(table.rowCount()):
                channel = self.channel_from_row(row)
                is_playing = playing is not None and self._channels_match(channel, playing)
                is_recording = channel is not None and channel_key(channel) in recording
                self._set_channel_row_playing(row, channel, is_playing, colors, is_recording)
                if is_playing:
                    playing_item = table.item(row, COL_NAME)
        finally:
            table.setSortingEnabled(sorting)
        if scroll and playing_item is not None:
            table.scrollToItem(playing_item)
            table.setCurrentItem(playing_item)

    def _visible_channel_column(self, key):
        return bool(self.channel_options['columns'].get(key))

    def _wants_now_next(self):
        return self._visible_channel_column('now') or self._visible_channel_column('next')

    def _load_channel_kinds(self, backend):
        services = []
        if self._visible_channel_column('type'):
            try:
                services = backend.list_channel_services()
            except Exception as e:
                print(f"Debug: Could not load channel services: {e}")
        self._channel_kinds = channel_kinds(self._channels, services, self._channel_tags)

    def _fetch_now_next(self, backend):
        if not self._wants_now_next() or not self._channels:
            self._now_next = {}
            return
        try:
            self._now_next = backend.get_now_next(self._channels)
        except Exception as e:
            print(f"Debug: Could not load now and next: {e}")
        self._now_next_fetched = time.monotonic()

    def _tick_now_next(self):
        """Move the progress bars on, and fetch now/next again when a programme ends."""
        if not self._channels or not self._wants_now_next():
            return
        now = int(time.time())
        since = time.monotonic() - self._now_next_fetched
        ended = any(
            entry.now is not None and entry.now.stop and entry.now.stop <= now
            for entry in self._now_next.values()
        )
        if since >= NOW_NEXT_REFRESH_SECONDS or (ended and since >= 60):
            try:
                if self.current_server() and self._server_requests_ready():
                    self._fetch_now_next(self.get_backend())
            except Exception as e:
                print(f"Debug: Could not refresh now and next: {e}")
        self._update_channel_extras()

    def _row_key(self, row):
        item = self.channel_list.item(row, COL_NAME)
        return item.data(CHANNEL_KEY_ROLE) if item is not None else None

    def _fill_channel_rows(self):
        """Rebuild the table from the fetched channels and the current settings."""
        table = self.channel_list
        options = self.channel_options
        shown = self._channels
        if options['hide_disabled']:
            shown = [channel for channel in shown if channel.enabled]
        backend = None
        # Blank space keeps names lined up, but only when some channel has a logo.
        logos = options['logos'] and any(channel_icon_reference(channel) for channel in shown)
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for channel in shown:
            row = table.rowCount()
            table.insertRow(row)
            number_item = QTableWidgetItem()
            number_item.setData(Qt.ItemDataRole.DisplayRole, channel.number)
            set_item_access(number_item, f"Channel {channel.number}", "Channel number")
            table.setItem(row, COL_NUMBER, number_item)
            name_item = QTableWidgetItem(channel.name)
            name_item.setData(Qt.ItemDataRole.UserRole, channel.to_raw())
            name_item.setData(CHANNEL_KEY_ROLE, channel_key(channel))
            set_item_access(name_item, channel.name, self._channel_description(channel))
            if logos:
                reference = channel_icon_reference(channel)
                name_item.setData(LOGO_ROLE, reference)
                if reference and backend is None:
                    backend = self._logo_backend()
                pixmap = self._logo_for(reference, backend) if reference else None
                name_item.setIcon(QIcon(pixmap if pixmap is not None else padded_pixmap()))
            table.setItem(row, COL_NAME, name_item)
            for column in (COL_STATUS, COL_NOW, COL_NEXT, COL_TYPE):
                table.setItem(row, column, QTableWidgetItem(""))
        self._update_channel_extras(sort=False)
        table.setSortingEnabled(True)
        self._apply_channel_filter()

    def _update_channel_extras(self, sort=True):
        """Write now, next, and type into each row from what was last fetched."""
        table = self.channel_list
        now = int(time.time())
        show_progress = self.channel_options['now_progress']
        sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)
        try:
            for row in range(table.rowCount()):
                key = self._row_key(row)
                now_next = self._now_next.get(key)
                current = now_next.now if now_next is not None else None
                following = now_next.next if now_next is not None else None
                now_item = table.item(row, COL_NOW)
                if now_item is not None:
                    if current is not None and current.stop and current.stop <= now:
                        current = None
                    self._set_programme_cell(now_item, current, now, show_progress)
                next_item = table.item(row, COL_NEXT)
                if next_item is not None:
                    self._set_programme_cell(next_item, following, now, False, with_start=True)
                type_item = table.item(row, COL_TYPE)
                if type_item is not None:
                    kind = self._channel_kinds.get(key)
                    label = kind.label() if kind is not None else ""
                    if type_item.text() != label:
                        type_item.setText(label)
                    type_item.setToolTip(f"Provider: {kind.provider}" if kind is not None and kind.provider else "")
        finally:
            table.setSortingEnabled(sorting and sort)
        table.viewport().update()

    def _set_programme_cell(self, item, event, now, show_progress, with_start=False):
        if event is None:
            item.setText("")
            item.setToolTip("")
            item.setData(PROGRESS_ROLE, None)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, None)
            return
        start = datetime.fromtimestamp(event.start).strftime('%H:%M') if event.start else ""
        stop = datetime.fromtimestamp(event.stop).strftime('%H:%M') if event.stop else ""
        text = f"{start} {event.title}" if with_start and start else event.title
        if item.text() != text:
            item.setText(text)
        lines = [event.title]
        if event.subtitle:
            lines.append(event.subtitle)
        when = f"{start}–{stop}" if start and stop else start
        if not with_start and event.stop and event.stop > now:
            minutes = max(1, (event.stop - now + 59) // 60)
            when = f"{when}, {minutes} min left" if when else f"{minutes} min left"
        if when:
            lines.append(when)
        if event.summary and event.summary != event.subtitle:
            lines.append(event.summary)
        item.setToolTip("\n".join(lines))
        item.setData(Qt.ItemDataRole.AccessibleTextRole, ", ".join(lines[:3]))
        item.setData(PROGRESS_ROLE, progress(event, now) if show_progress else None)

    def _logo_backend(self):
        try:
            if self.current_server() and self._server_requests_ready():
                return self.get_backend()
        except Exception as e:
            print(f"Debug: Could not reach the server for logos: {e}")
        return None

    def _logo_for(self, reference, backend):
        """Pixmap for a logo reference, or None while it loads in the background."""
        pixmap = self._logo_pixmaps.get(reference)
        if pixmap is not None:
            return pixmap
        server = self.current_server() or {}
        pixmap = logo_pixmap(self.logo_loader.cached(server.get('url') or '', reference))
        if pixmap is not None:
            self._logo_pixmaps[reference] = pixmap
            return pixmap
        if backend is not None:
            try:
                url = backend.image_url(reference)
            except Exception as e:
                print(f"Debug: No URL for logo {reference}: {e}")
                url = ''
            if url.startswith(('http://', 'https://')):
                self.logo_loader.request(server, reference, url)
        return None

    def _on_logo_loaded(self, reference, data):
        pixmap = logo_pixmap(data)
        if pixmap is None:
            return
        self._logo_pixmaps[reference] = pixmap
        if not self.channel_options['logos']:
            return
        icon = QIcon(pixmap)
        table = self.channel_list
        for row in range(table.rowCount()):
            item = table.item(row, COL_NAME)
            if item is not None and item.data(LOGO_ROLE) == reference:
                item.setIcon(icon)

    def channel_recordings_changed(self, entries):
        """The tasks pane read the server's recordings; mark channels being recorded."""
        self._dvr_entries = list(entries or [])
        keys = recording_channel_keys(self._channels, self._dvr_entries)
        if keys != self._recording_keys:
            self._recording_keys = keys
            self._mark_playing_channel()
        self._sync_record_controls()

    def _selected_channel_tag(self):
        if not self.channel_options['tag_filter']:
            return None
        uuid = self.tag_combo.currentData() or ''
        if not uuid:
            return None
        for tag in self._channel_tags:
            if tag.uuid == uuid:
                return tag
        return None

    def _refresh_tag_combo(self):
        combo = self.tag_combo
        wanted = self.channel_options['tag']
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("All channels", "")
            for tag in self._channel_tags:
                count = len(channels_in_tag(self._channels, tag))
                if count:
                    combo.addItem(f"{tag.name or 'Unnamed'} ({count})", tag.uuid)
            index = combo.findData(wanted) if wanted else 0
            combo.setCurrentIndex(max(index, 0))
        finally:
            combo.blockSignals(False)
        self.tag_row.setVisible(self.channel_options['tag_filter'] and combo.count() > 1)

    def _on_channel_tag_changed(self, index):
        self.channel_options['tag'] = self.tag_combo.itemData(index) or ''
        self._save_channel_options()
        self._apply_channel_filter()

    def filter_channels(self, search_text):
        """Filter channel list based on search text"""
        self._apply_channel_filter()

    def _apply_channel_filter(self):
        """Hide rows that miss the search text or the selected group."""
        table = self.channel_list
        search_text = self.search_box.text().lower() if hasattr(self, 'search_box') else ""
        tag = self._selected_channel_tag()
        members = None
        if tag is not None:
            members = {channel_key(channel) for channel in channels_in_tag(self._channels, tag)}
        for row in range(table.rowCount()):
            item = table.item(row, COL_NAME)
            number_item = table.item(row, COL_NUMBER)
            if item is None:
                continue
            channel_name = item.text().lower()
            number = number_item.text().lower() if number_item else ""
            hidden = search_text not in channel_name and search_text not in number
            if members is not None and item.data(CHANNEL_KEY_ROLE) not in members:
                hidden = True
            table.setRowHidden(row, hidden)

    def _build_channel_list_menu(self, view_menu):
        """View > Channel List: columns, logos, progress, recording marks, groups."""
        menu = view_menu.addMenu("&Channel List")
        menu.setToolTipsVisible(True)
        self.channel_columns_menu = menu.addMenu("C&olumns")
        self.channel_columns_menu.setAccessibleName("Channel list columns")
        self._channel_column_actions = {}
        for key, label in COLUMN_MENU:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self._visible_channel_column(key))
            action.toggled.connect(lambda checked, key=key: self._set_channel_column(key, checked))
            self.channel_columns_menu.addAction(action)
            self._channel_column_actions[key] = action
        menu.addSeparator()
        self._channel_option_actions = {}
        for key, label, tip in (
            ('logos', "Channel &Logos", "Show each channel's logo next to its name"),
            ('now_progress', "&Progress Bar Under Now Playing", "Show how far the current programme has got"),
            ('recording_status', "Mark &Recording Channels", "Show Recording on channels the server is recording"),
            ('tag_filter', "&Group Filter", "Show a list for picking one channel group"),
            ('hide_disabled', "&Hide Disabled Channels", "Leave out channels that are turned off on the server"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(bool(self.channel_options[key]))
            action.setToolTip(tip)
            action.setStatusTip(tip)
            action.toggled.connect(lambda checked, key=key: self._set_channel_option(key, checked))
            menu.addAction(action)
            self._channel_option_actions[key] = action
        menu.addSeparator()
        reset = menu.addAction("Reset Channel List &Layout")
        reset.setStatusTip("Bring back the default columns, column order, and channel list options")
        reset.triggered.connect(self._reset_channel_list_layout)

    def _show_channel_column_menu(self, position):
        header = self.channel_list.horizontalHeader()
        self.channel_columns_menu.exec(header.mapToGlobal(position))

    def _save_channel_options(self):
        self.config['channel_list'] = channel_list_options(self.channel_options)
        self.save_config()

    def _apply_channel_columns(self):
        """Show the chosen columns in the chosen order."""
        header = self.channel_list.horizontalHeader()
        header.blockSignals(True)
        try:
            for position, key in enumerate(self.channel_options['order']):
                logical = COLUMN_INDEX[key]
                current = header.visualIndex(logical)
                if current != position:
                    header.moveSection(current, position)
            for key, visible in self.channel_options['columns'].items():
                header.setSectionHidden(COLUMN_INDEX[key], not visible)
        finally:
            header.blockSignals(False)
        self._progress_delegate.enabled = self.channel_options['now_progress']

    def _channel_columns_moved(self, logical, old_visual, new_visual):
        header = self.channel_list.horizontalHeader()
        self.channel_options['order'] = [
            COLUMN_KEYS[header.logicalIndex(visual)] for visual in range(header.count())
        ]
        self._save_channel_options()

    def _set_channel_column(self, key, visible):
        had_now_next = self._wants_now_next()
        self.channel_options['columns'][key] = bool(visible)
        self._save_channel_options()
        self._apply_channel_columns()
        if not visible or not self._channels:
            return
        backend = self._logo_backend()
        if backend is None:
            return
        if key == 'type':
            self._load_channel_kinds(backend)
        elif key in ('now', 'next') and not had_now_next:
            self._fetch_now_next(backend)
        self._update_channel_extras()
        self._mark_playing_channel()

    def _set_channel_option(self, key, value):
        self.channel_options[key] = bool(value)
        self._save_channel_options()
        if key in ('logos', 'hide_disabled'):
            self._reload_channel_rows()
        elif key == 'now_progress':
            self._progress_delegate.enabled = bool(value)
            self._update_channel_extras()
        elif key == 'recording_status':
            self._mark_playing_channel()
        elif key == 'tag_filter':
            self.tag_row.setVisible(bool(value) and self.tag_combo.count() > 1)
            self._apply_channel_filter()

    def _reload_channel_rows(self):
        """Rebuild the rows from fetched data, keeping the selection and scroll place."""
        table = self.channel_list
        selected = self.channel_from_row(table.currentRow())
        scroll = table.verticalScrollBar().value()
        self._fill_channel_rows()
        self._mark_playing_channel()
        if selected is not None:
            for row in range(table.rowCount()):
                if self._channels_match(self.channel_from_row(row), selected):
                    table.setCurrentCell(row, COL_NAME)
                    break
        table.verticalScrollBar().setValue(scroll)

    def _reset_channel_list_layout(self):
        had_type = self._visible_channel_column('type')
        had_now_next = self._wants_now_next()
        self.channel_options = channel_list_options(None)
        for key, action in self._channel_column_actions.items():
            action.blockSignals(True)
            action.setChecked(self._visible_channel_column(key))
            action.blockSignals(False)
        for key, action in self._channel_option_actions.items():
            action.blockSignals(True)
            action.setChecked(bool(self.channel_options[key]))
            action.blockSignals(False)
        self._save_channel_options()
        self._apply_channel_columns()
        backend = self._logo_backend() if self._channels else None
        if backend is not None:
            if self._visible_channel_column('type') and not had_type:
                self._load_channel_kinds(backend)
            if self._wants_now_next() and not had_now_next:
                self._fetch_now_next(backend)
        self._refresh_tag_combo()
        self._reload_channel_rows()

    def fetch_channels(self, keep_place=False):
        """Load the channel list from the current server in the background.

        With keep_place, a reload of the same server keeps the selected row and
        the scroll position instead of moving to the playing channel.
        """
        # A fetch still running for an earlier request is ignored when it ends.
        self._channel_fetch = None
        self.channel_busy.hide()
        server = self.current_server()
        if not server:
            self._clear_channels()
            self._show_channel_state("No servers yet. Add one with the ⚙️ button above.")
            self.statusbar.showMessage("No servers configured")
            return
        if is_builtin_server(server) and not self._server_requests_ready():
            self._clear_channels()
            supervisor = getattr(self, 'builtin', None)
            if supervisor is None:
                message = "Built-in server is not available in this build."
                self._show_channel_state(message)
                self.statusbar.showMessage(message)
                return
            if supervisor.binary is None:
                message = "Built-in Tvheadend is not packaged in this build."
                self._show_channel_state(message)
                self.statusbar.showMessage(message)
                print("Debug: Built-in Tvheadend binary was not found in this build.")
                return
            self._show_channel_state("Starting built-in server…", busy=True)
            self.statusbar.showMessage("Starting built-in server...")
            supervisor.start()
            return
        print(f"Debug: Fetching channels from server: {server['url']}")
        fetch = ChannelFetch(
            server,
            kinds=self._visible_channel_column('type'),
            now_next=self._wants_now_next(),
            open_backend=self._open_channel_backend,
            parent=self,
        )
        fetch.keep_place = keep_place
        fetch.loaded.connect(lambda result, fetch=fetch: self._on_channels_loaded(fetch, result))
        fetch.failed.connect(lambda message, fetch=fetch: self._on_channels_failed(fetch, message))
        self._channel_fetch = fetch
        if self._channels and self._channels_server == fetch.key:
            self.channel_busy.show()
        else:
            self._clear_channels()
            self._show_channel_state(f"Loading channels from {server.get('name') or 'the server'}…", busy=True)
        self.statusbar.showMessage("Connecting to server...")
        fetch.start()

    def _open_channel_backend(self, server):
        return create_backend(server)

    def _on_channels_loaded(self, fetch, result):
        fetch.deleteLater()
        if fetch is not self._channel_fetch:
            return
        self._channel_fetch = None
        self.channel_busy.hide()
        reload = bool(self._channels) and self._channels_server == fetch.key
        url = fetch.server.get('url')
        if url != self._logo_server:
            self.logo_loader.forget()
            self._logo_pixmaps.clear()
            self._logo_server = url
        self._channels = result['channels']
        self._channels_server = fetch.key
        self._channel_tags = result['tags']
        self._channel_kinds = channel_kinds(self._channels, result['services'], self._channel_tags)
        if result['now_next'] is not None:
            self._now_next = result['now_next']
        self._now_next_fetched = time.monotonic()
        self._recording_keys = recording_channel_keys(self._channels, getattr(self, '_dvr_entries', []))
        self._refresh_tag_combo()
        if reload and fetch.keep_place:
            self._reload_channel_rows()
        else:
            self._fill_channel_rows()
            self._mark_playing_channel(scroll=True)
        if self._channels:
            self._show_channel_list()
        else:
            self._show_channel_state("This server has no channels yet.")
        self.statusbar.showMessage("Channels loaded successfully")

    def _on_channels_failed(self, fetch, message):
        fetch.deleteLater()
        if fetch is not self._channel_fetch:
            return
        self._channel_fetch = None
        self.channel_busy.hide()
        name = fetch.server.get('name') or 'the server'
        if self._channels and self._channels_server == fetch.key:
            # Keep the list from the last load; it is still useful.
            self.statusbar.showMessage(f"Could not refresh channels from {name}: {message}")
            return
        self._clear_channels()
        self._show_channel_state(f"Could not connect to {name}.\n{message}", retry=True)
        self.statusbar.showMessage(f"Could not connect to {name}")

    def _clear_channels(self):
        self._channels = []
        self._channels_server = None
        self._channel_tags = []
        self._channel_kinds = {}
        self._now_next = {}
        self.channel_list.setRowCount(0)
        self._refresh_tag_combo()

    def _show_channel_state(self, text, busy=False, retry=False):
        """Put a message, and a spinner or Retry button, where the channel list is."""
        stack = self.channel_stack
        focus = QApplication.focusWidget()
        had_focus = focus is not None and (focus is stack or stack.isAncestorOf(focus))
        self.channel_state.show_state(text, busy=busy, retry=retry)
        stack.setCurrentWidget(self.channel_state)
        if had_focus and retry:
            self.channel_state.retry_btn.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show_channel_list(self):
        stack = self.channel_stack
        if stack.currentWidget() is self.channel_list:
            return
        focus = QApplication.focusWidget()
        had_focus = focus is not None and (focus is stack or stack.isAncestorOf(focus))
        stack.setCurrentWidget(self.channel_list)
        if had_focus:
            self.channel_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _programme_on_now(self, channel):
        """The channel's programme on now, from the list's guide data or the server."""
        now_next = self._now_next.get(channel_key(channel))
        if now_next is None:
            try:
                now_next = self.get_backend().get_now_next([channel]).get(channel_key(channel))
            except Exception as e:
                print(f"Debug: No programme information for {channel.name}: {e}")
                return None
        event = now_next.now if now_next is not None else None
        now = time.time()
        if event is None or not event.event_id or not event.start <= now < event.stop:
            return None
        return event

    def start_recording(self):
        print("Debug: Starting recording")
        try:
            channel = self.selected_channel()
            if not channel:
                print("Debug: No channel selected for recording")
                self.statusbar.showMessage("Please select a channel to record")
                return

            duration_dialog = RecordingDurationDialog(self, channel, self._programme_on_now(channel))
            if duration_dialog.exec() != QDialog.DialogCode.Accepted:
                print("Debug: Recording cancelled by user")
                return
            
            event = duration_dialog.programme_event()
            if event is not None:
                # The server records the programme and stops when it ends.
                self.get_backend().create_dvr_entry_by_event(event.event_id)
                until = datetime.fromtimestamp(event.stop).strftime('%H:%M')
                self.statusbar.showMessage(
                    f"Recording started for: {channel.name} ({event.title}, until {until})"
                )
                self._show_on_picture(f"Recording {event.title} (until {until})")
            else:
                duration = duration_dialog.get_duration()
                now = int(datetime.now().timestamp())
                self.get_backend().create_dvr_entry(
                    channel,
                    now,
                    now + duration,
                    title=instant_recording_title(channel.name, datetime.fromtimestamp(now)),
                    description='Recorded via TVHplayer',
                    comment='Instant recording via TVHplayer',
                )
                duration_minutes = duration // 60
                self.statusbar.showMessage(
                    f"Recording started for: {channel.name} ({duration_minutes} minutes)"
                )
                self._show_on_picture(f"Recording {channel.name} ({duration_minutes} min)")
            self.start_recording_indicator()
            self._refresh_tasks()
        except Exception as e:
            print(f"Debug: Recording error: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Recording error: {str(e)}")
            
    def toggle_playback(self):
        """The Play/Stop button and P: stop what plays, or play the selected channel."""
        if self._playback_active or self._awaiting_playback:
            self.stop_playback()
        else:
            self.play_channel_by_data(self.selected_channel())

    def _sync_play_button(self):
        bar = getattr(self, 'controls_bar', None)
        if bar is not None:
            bar.set_playing(
                bool(getattr(self, '_playback_active', False) or getattr(self, '_awaiting_playback', False))
            )

    def _server_recordings_to_stop(self):
        return recordings_to_stop(getattr(self, '_dvr_entries', None) or [], self.active_channel())

    def _sync_record_controls(self):
        """Show Stop recording while the server records the active channel or this computer records."""
        bar = getattr(self, 'controls_bar', None)
        if bar is None:
            return
        server = bool(self._server_recordings_to_stop())
        recorder = getattr(self, 'local_recorder', None)
        local = bool(recorder is not None and recorder.is_running)
        channel = self.active_channel()
        bar.set_recording(server, local, channel.name if channel is not None else '')

    def stop_any_recording(self):
        """Stop recording ends whichever recording runs, and asks only when both do."""
        server = bool(self._server_recordings_to_stop())
        recorder = getattr(self, 'local_recorder', None)
        local = bool(recorder is not None and recorder.is_running)
        if server and local:
            bar = self.controls_bar
            bar.popup_above(bar.stop_menu, bar.recording_group)
        elif local:
            self.stop_local_recording()
        else:
            self.stop_recording()

    def stop_both_recordings(self):
        self.stop_recording()
        self.stop_local_recording()

    def stop_playback(self):
        """Stop current playback"""
        print("Debug: Stopping playback")
        self._stop_start_watch()
        self._awaiting_playback = False
        self._playback_active = False
        self._playback_channel = None
        self._mark_playing_channel()
        self._set_playback_spinner(False)
        self._sync_play_button()
        self.player.stop()
        self._protect_video_surface(False)
        self.statusbar.showMessage("Playback stopped")

    def _set_idle_splash(self, visible):
        """Show the logo overlay only when VLC is not drawing video."""
        if not hasattr(self, 'idle_splash'):
            return
        if visible:
            self.idle_splash.setGeometry(self.player_container.rect())
            self.idle_splash.setAccessibleName("Nothing playing")
            self.idle_splash.show()
            self.idle_splash.raise_()
            spinner = getattr(self, 'playback_spinner', None)
            if spinner is not None and spinner.isVisible():
                spinner.raise_()
        else:
            self.idle_splash.setAccessibleName("")
            self.idle_splash.hide()

    def _set_playback_spinner(self, visible):
        """Show a spinner from the play request until the picture starts."""
        spinner = getattr(self, 'playback_spinner', None)
        if spinner is None:
            return
        if visible:
            already = spinner.isVisible()
            spinner.setGeometry(self.player_container.rect())
            spinner.set_running(True)
            if not already:
                announce(spinner, "Starting playback")
        else:
            spinner.set_running(False)
            spinner.setAccessibleName("")

    def _show_playback_wait(self):
        """Cover the player until VLC reports that playback has started."""
        self._awaiting_playback = True
        if hasattr(self, '_splash_idle_timer'):
            self._splash_idle_timer.stop()
        self._set_idle_splash(True)
        spinner = getattr(self, 'playback_spinner', None)
        if spinner is not None:
            spinner.set_caption(STARTING)
        self._set_playback_spinner(True)
        self._sync_play_button()
        self._watch_start()
        if hasattr(self, 'video_frame'):
            self.video_frame.setUpdatesEnabled(False)

    def _watch_start(self):
        """Show what the server says about the channel while it starts."""
        self._stop_start_watch()
        channel = getattr(self, '_playback_channel', None)
        server = self.current_server()
        if channel is None or not server:
            return
        watch = StartWatch(server, channel.name, self)
        watch.caption.connect(lambda text, watch=watch: self._on_start_caption(watch, text))
        watch.give_up.connect(lambda watch=watch: self._on_start_given_up(watch))
        self._start_watch = watch
        watch.start()

    def _stop_start_watch(self):
        watch = getattr(self, '_start_watch', None)
        if watch is not None:
            watch.stop()
        self._start_watch = None

    def _on_start_caption(self, watch, text):
        if watch is not getattr(self, '_start_watch', None) or not self._awaiting_playback:
            return
        spinner = getattr(self, 'playback_spinner', None)
        if spinner is not None:
            spinner.set_caption(text)
        channel = getattr(self, '_playback_channel', None)
        if channel is not None:
            self.statusbar.showMessage(f"{channel.name}: {text}")

    def _on_start_given_up(self, watch):
        if watch is not getattr(self, '_start_watch', None) or not self._awaiting_playback:
            return
        channel = getattr(self, '_playback_channel', None)
        name = channel.name if channel is not None else 'This channel'
        self.stop_playback()
        self.statusbar.showMessage(f"{name} is not working right now. Try another channel.")

    def _protect_video_surface(self, playing):
        """While a channel is on, do not let Qt paint or flash the splash."""
        self._playback_active = playing
        self._sync_play_button()
        if hasattr(self, '_splash_idle_timer'):
            self._splash_idle_timer.stop()
        waiting = bool(getattr(self, '_awaiting_playback', False))
        self._set_idle_splash((not playing) or waiting)
        if waiting:
            self._set_playback_spinner(True)
        if hasattr(self, 'video_frame'):
            self.video_frame.setUpdatesEnabled(not playing and not waiting)

    def _show_on_picture(self, text):
        """Repeat a status message over the video, where it shows in fullscreen too.

        Only while a picture is on screen; the status bar keeps the message for screen readers.
        """
        if getattr(self, '_playback_active', False) and getattr(self, 'player', None) is not None:
            self.player.show_message(text)

    def _on_playback_started(self):
        self._stop_start_watch()
        self._awaiting_playback = False
        self._set_playback_spinner(False)
        self._protect_video_surface(True)
        self._mark_playing_channel()
        channel = getattr(self, '_playback_channel', None)
        if channel is not None:
            self.statusbar.showMessage(f"Playing: {channel.name}")
            self._show_on_picture(f"{channel.number}  {channel.name}" if channel.number else channel.name)

    def _on_playback_failed(self):
        self._stop_start_watch()
        self._awaiting_playback = False
        self._playback_active = False
        self._sync_play_button()
        self._playback_channel = None
        self._mark_playing_channel()
        self._set_playback_spinner(False)
        self._protect_video_surface(False)
        self.statusbar.showMessage("Playback failed")

    def _on_playback_stopped(self):
        # A menu or resize can make the engine tear down its output for a moment.
        # Do not treat that as a real stop or the splash will flash.
        if self._playback_active or self._awaiting_playback:
            return
        if not hasattr(self, '_splash_idle_timer'):
            return
        self._splash_idle_timer.start(400)

    def _show_splash_if_idle(self):
        if self._playback_active or self._awaiting_playback:
            return
        if self.player and self.player.is_playing():
            return
        self._protect_video_surface(False)

    def _bind_playback_splash(self):
        """Keep the splash in sync if playback starts or stops on its own."""
        self._splash_idle_timer = QTimer(self)
        self._splash_idle_timer.setSingleShot(True)
        self._splash_idle_timer.timeout.connect(self._show_splash_if_idle)
        try:
            self.player.set_handlers(
                self._on_playback_started,
                self._on_playback_stopped,
                lambda fn: QTimer.singleShot(0, fn),
                on_error=self._on_playback_failed,
            )
        except Exception as e:
            print(f"Debug: Could not attach playback events: {e}")

    def toggle_fullscreen(self, checked=None):
        """Fill the screen with the current window; hide list, controls, and bars."""
        print(f"Debug: Toggling fullscreen. Current state: {self.is_fullscreen}")
        try:
            if self.is_fullscreen:
                self._exit_fullscreen()
            else:
                self._enter_fullscreen()
            self._sync_fullscreen_ui()
            print(f"Debug: New fullscreen state: {self.is_fullscreen}")
        except Exception as e:
            print(f"Debug: Error in toggle_fullscreen: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")

    def _name_splitter_handles(self):
        names = [
            (
                "Resize channels and player",
                "Drag left or right, or use the arrow keys, to resize the channel list and the player.",
            ),
            (
                "Resize player and tasks",
                "Drag left or right, or use the arrow keys, to resize the player and the task list.",
            ),
        ]
        for index, (name, description) in enumerate(names, start=1):
            handle = self.splitter.handle(index)
            if handle is None:
                continue
            handle.setAccessibleName(name)
            handle.setAccessibleDescription(description)

    def _splitter_handles(self):
        handles = []
        splitter = getattr(self, 'splitter', None)
        if splitter is None:
            return handles
        for index in range(1, splitter.count()):
            handle = splitter.handle(index)
            if handle is not None:
                handles.append(handle)
        return handles

    def _toggle_tasks_pane(self, checked):
        self.tasks_pane.setVisible(bool(checked))

    def _close_tasks_pane(self):
        self.tasks_action.setChecked(False)
        self.tasks_pane.hide()

    def _refresh_tasks(self, server=True):
        pane = getattr(self, 'tasks_pane', None)
        if pane is not None:
            pane.refresh(server=server)

    def _recording_in_progress(self):
        """True while a server recording or the local job is running."""
        recorder = getattr(self, 'local_recorder', None)
        if recorder is not None and getattr(recorder, 'is_running', False):
            return True
        try:
            if not self.current_server() or not self._server_requests_ready():
                return False
            entries = self.get_backend().list_dvr_entries()
        except Exception:
            return bool(getattr(self, 'is_recording', False))
        return any(entry.category() == 'recording' for entry in entries)

    def sync_recording_indicator(self):
        """Show REC while a server recording or the local job is running."""
        if self._recording_in_progress():
            if not self.is_recording:
                self.start_recording_indicator()
            return
        if self.is_recording:
            self.stop_recording_indicator()

    def _enter_fullscreen(self):
        handles = self._splitter_handles()
        self._pre_fullscreen_state = {
            'geometry': self.saveGeometry(),
            'splitter': self.splitter.saveState(),
            'right_margins': self.right_layout.contentsMargins(),
            'main_margins': self.main_layout.contentsMargins(),
            'window_margins': self.contentsMargins(),
            'right_frame': self.right_pane.frameStyle(),
            'right_line': self.right_pane.lineWidth(),
            'splitter_frame': self.splitter.frameStyle(),
            'splitter_handle_width': self.splitter.handleWidth(),
            'splitter_handles_visible': [handle.isVisible() for handle in handles],
            'tasks_visible': self.tasks_pane.isVisible(),
        }
        self.setUpdatesEnabled(False)
        try:
            self.menuBar().hide()
            self.statusbar.hide()
            self.left_pane.hide()
            self.tasks_pane.hide()
            self.right_layout.removeWidget(self.controls_bar)
            self.floating_bar.hold(self.controls_bar)
            self.right_pane.setFrameStyle(QFrame.Shape.NoFrame)
            self.right_pane.setLineWidth(0)
            self.splitter.setFrameStyle(QFrame.Shape.NoFrame)
            self.splitter.setHandleWidth(0)
            for handle in handles:
                handle.hide()
            self.right_layout.setContentsMargins(0, 0, 0, 0)
            self.main_layout.setContentsMargins(0, 0, 0, 0)
            self.setContentsMargins(0, 0, 0, 0)
            self.showFullScreen()
        finally:
            self.setUpdatesEnabled(True)
            self._protect_video_surface(self._playback_active)
        self.is_fullscreen = True
        # Show the bar once so it is clear where the controls went.
        QTimer.singleShot(300, lambda: self.is_fullscreen and self.floating_bar.poke())

    def _exit_fullscreen(self):
        state = self._pre_fullscreen_state or {}
        self.setUpdatesEnabled(False)
        try:
            geometry = state.get('geometry')
            if geometry:
                self.restoreGeometry(geometry)
            else:
                self.showNormal()
            self.menuBar().show()
            self.statusbar.show()
            self.left_pane.show()
            bar = self.floating_bar.release()
            if bar is not None:
                self.right_layout.addWidget(bar)
                bar.show()
            self.right_pane.setFrameStyle(
                state.get('right_frame', QFrame.Shape.Panel | QFrame.Shadow.Raised)
            )
            self.right_pane.setLineWidth(state.get('right_line', 1))
            self.splitter.setFrameStyle(state.get('splitter_frame', QFrame.Shape.NoFrame))
            self.splitter.setHandleWidth(state.get('splitter_handle_width', 5))
            visibilities = state.get('splitter_handles_visible')
            handles = self._splitter_handles()
            if visibilities is None:
                for handle in handles:
                    handle.show()
            else:
                for handle, visible in zip(handles, visibilities):
                    handle.setVisible(bool(visible))
            margins = state.get('right_margins')
            if margins is not None:
                self.right_layout.setContentsMargins(margins)
            main_margins = state.get('main_margins')
            if main_margins is not None:
                self.main_layout.setContentsMargins(main_margins)
            window_margins = state.get('window_margins')
            if window_margins is not None:
                self.setContentsMargins(window_margins)
            splitter_state = state.get('splitter')
            if splitter_state:
                self.splitter.restoreState(splitter_state)
            tasks_visible = state.get('tasks_visible', True)
            self.tasks_pane.setVisible(tasks_visible)
            if hasattr(self, 'tasks_action'):
                self.tasks_action.blockSignals(True)
                self.tasks_action.setChecked(tasks_visible)
                self.tasks_action.blockSignals(False)
        finally:
            self.setUpdatesEnabled(True)
            self._protect_video_surface(self._playback_active)
        self.is_fullscreen = False
        self._pre_fullscreen_state = None

    def _sync_fullscreen_ui(self):
        if hasattr(self, 'fullscreen_action'):
            self.fullscreen_action.blockSignals(True)
            self.fullscreen_action.setChecked(self.is_fullscreen)
            self.fullscreen_action.setText('Exit Fullscreen' if self.is_fullscreen else 'Fullscreen')
            self.fullscreen_action.blockSignals(False)
        if hasattr(self, 'fullscreen_btn'):
            if self.is_fullscreen:
                self.fullscreen_btn.setToolTip("Exit fullscreen (Esc)")
                describe(self.fullscreen_btn, "Exit fullscreen", "Return to the window. Keyboard: Escape, F11, or F.")
            else:
                self.fullscreen_btn.setToolTip("Fullscreen (F11)")
                describe(self.fullscreen_btn, "Fullscreen", "Fill the screen with the picture. Keyboard: F11 or F.")
            self.controls_bar.set_fullscreen(self.is_fullscreen)
        if hasattr(self, 'video_frame'):
            announce(
                self.video_frame,
                "Fullscreen video player" if self.is_fullscreen else "Video player",
            )

    def _video_context_menu(self):
        """Build the right-click menu for the video surface."""
        menu = QMenu(self)
        menu.setAccessibleName("Playback")
        channel = self.selected_channel()
        playing = bool(self.player and self.player.is_playing())
        muted = bool(self.player and self.player.is_muted())

        play_action = menu.addAction(QIcon(f"{self.icons_dir}/play.svg"), "Play")
        play_action.setEnabled(channel is not None)
        play_action.triggered.connect(lambda: self.play_channel_by_data(channel))

        stop_action = menu.addAction(QIcon(f"{self.icons_dir}/stop.svg"), "Stop")
        stop_action.setEnabled(playing)
        stop_action.triggered.connect(self.stop_playback)

        menu.addSeparator()

        mute_action = menu.addAction(
            QIcon(f"{self.icons_dir}/unmute.svg" if muted else f"{self.icons_dir}/mute.svg"),
            "Unmute" if muted else "Mute",
        )
        mute_action.triggered.connect(self.toggle_mute)

        fullscreen_action = menu.addAction(
            QIcon(f"{self.icons_dir}/fullscreen.svg"),
            "Exit Fullscreen" if self.is_fullscreen else "Fullscreen",
        )
        fullscreen_action.triggered.connect(self.toggle_fullscreen)

        menu.addSeparator()

        record_action = menu.addAction(QIcon(f"{self.icons_dir}/record.svg"), "Record")
        record_action.setEnabled(channel is not None)
        record_action.triggered.connect(self.start_recording)

        local_action = menu.addAction(QIcon(f"{self.icons_dir}/reclocal.svg"), "Record Locally")
        local_action.setEnabled(channel is not None)
        local_action.triggered.connect(lambda: self.start_local_recording(channel))

        epg_action = menu.addAction(QIcon(f"{self.icons_dir}/epg.svg"), "Show EPG")
        epg_action.setEnabled(channel is not None)
        epg_action.triggered.connect(lambda: self.show_channel_epg(channel))
        return menu

    def show_video_context_menu(self, position):
        """Right-click menu on the video surface."""
        menu = self._video_context_menu()
        menu.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        menu.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if hasattr(Qt.WidgetAttribute, 'WA_X11DoNotAcceptFocus'):
            menu.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus, True)
        self._video_menu = menu
        # popup() avoids exec()'s modal loop, which deactivates the window
        # and can make VLC tear down its output.
        menu.popup(self.video_frame.mapToGlobal(position))

    def manage_servers(self):
        print("Debug: Opening server management dialog")
        dialog = ServerDialog(self)
        dialog.load_servers(self.servers)
        dialog.server_list.setCurrentRow(self.server_combo.currentIndex())
        print(f"Debug: Loaded {len(self.servers)} servers into dialog")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.servers = ensure_builtin_server(
                dialog.servers,
                self.config.get('builtin_http_port') or 0,
                self.config.get('builtin_htsp_port') or 0,
                *self._builtin_credentials(),
            )
            self.config_store.servers = self.servers
            print(f"Debug: Updated servers list, now has {len(self.servers)} servers")
            self.save_config()
            self.close_backend()

            previous = self.server_combo.currentIndex()
            self.server_combo.blockSignals(True)
            self.server_combo.clear()
            for server in self.servers:
                print(f"Debug: Adding server to combo: {server['name']}")
                self.server_combo.addItem(server['name'])
            if self.servers:
                self.server_combo.setCurrentIndex(min(max(previous, 0), len(self.servers) - 1))
            self.server_combo.blockSignals(False)
            
            # Refresh channels
            self.fetch_channels()
    
    def save_config(self):
        """Save current configuration"""
        try:
            if not self.is_fullscreen:
                self.config['window_geometry'] = {
                    'x': self.x(),
                    'y': self.y(),
                    'width': self.width(),
                    'height': self.height()
                }
            self.config_store.servers = self.servers
            self.config['last_server'] = self.server_combo.currentIndex()
            self.config_store.data = self.config
            self.config_store.save()
            self.config = self.config_store.data
            self.servers = self.config_store.servers
            print("Debug: Configuration saved successfully")
        except Exception as e:
            print(f"Debug: Error saving config: {str(e)}")

    def play_channel(self, item):
        """Play the selected channel"""
        try:
            # Get the current row
            current_row = self.channel_list.currentRow()
            if current_row < 0:
                print("Debug: No channel selected")
                self.statusbar.showMessage("Please select a channel to play")
                return
            
            # Get channel data directly from the table
            name_item = self.channel_list.item(current_row, 1)  # Get the name column item
            if not name_item:
                print("Debug: No channel item found")
                return
            
            # Get the channel data stored in UserRole
            channel_data = name_item.data(Qt.ItemDataRole.UserRole)
            if not channel_data:
                print("Debug: No channel data found in item")
                return
            
            print(f"Debug: Playing channel: {channel_data.get('name', 'Unknown')}")
            
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            
            # Construct proper URL
            base_url = server['url']
            if not base_url.startswith(('http://', 'https://')):
                base_url = f"http://{base_url}"
            
            url = f"{base_url}/stream/channel/{channel_data['uuid']}"
            print(f"Debug: Playing URL: {url}")
            
            # Rest of the play logic...
        except Exception as e:
            print(f"Debug: Error in play_channel: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")

    def on_server_changed(self, index):
        """
        Handle when user switches to a different TVHeadend server in the dropdown.
        Updates the config file with the newly selected server index and refreshes channel list.
        
        Args:
            index (int): Index of the newly selected server in self.servers list
        """
        print(f"Debug: Server changed to index {index}")
        if index >= 0:  # Valid index selected
            print(f"Debug: Switching to server: {self.servers[index]['name']}")
            
            self.config['last_server'] = index
            self.save_config()
                
            self.close_backend()
            self._dvr_entries = []
            self._recording_keys = set()
            self.fetch_channels()
            pane = getattr(self, 'tasks_pane', None)
            if pane is not None:
                pane.clear_server_tasks()
                pane.refresh()

    def on_volume_changed(self, value):
        print(f"Debug: Volume changed to {value}")
        self.player.set_volume(value)
        self._show_on_picture(f"Volume {value}")

    def eventFilter(self, obj, event):
        """Keep the video surface stable and handle player gestures."""
        channel_list = getattr(self, 'channel_list', None)
        if obj is channel_list and channel_list is not None and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
                self.play_channel_by_data(self.selected_channel())
                return True
            if self._is_context_menu_key(event):
                self.show_channel_context_menu(None)
                return True
        player_container = getattr(self, 'player_container', None)
        if (
            player_container is not None
            and obj is player_container
            and event.type() == QEvent.Type.Resize
        ):
            # Resize the overlays even while the window is not shown yet:
            # isVisible() is False then, and skipping them left the logo
            # sized to the container's first, smaller rect (off-centre).
            idle_splash = getattr(self, 'idle_splash', None)
            if idle_splash is not None:
                idle_splash.setGeometry(player_container.rect())
            spinner = getattr(self, 'playback_spinner', None)
            if spinner is not None:
                spinner.setGeometry(player_container.rect())
                if spinner.isVisible():
                    spinner.raise_()
            return False
        video_frame = getattr(self, 'video_frame', None)
        if video_frame is not None and obj is video_frame:
            if event.type() == QEvent.Type.MouseMove and self.is_fullscreen:
                self.floating_bar.poke()
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self.toggle_fullscreen()
                return True
            if self._playback_active and event.type() in (
                QEvent.Type.Paint,
                QEvent.Type.UpdateRequest,
            ):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen:
            self.toggle_fullscreen()
            event.accept()
            return
        if self.is_fullscreen:
            self.floating_bar.poke()

        modifiers = event.modifiers()
        key = event.key()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if modifiers & Qt.KeyboardModifier.AltModifier:
            super().keyPressEvent(event)
            return

        if ctrl and shift and key == Qt.Key.Key_R:
            self.start_local_recording(self.selected_channel())
            event.accept()
            return
        if ctrl and shift and key == Qt.Key.Key_E:
            self.stop_local_recording()
            event.accept()
            return
        if ctrl and not shift and key == Qt.Key.Key_R:
            self.start_recording()
            event.accept()
            return
        if ctrl and not shift and key == Qt.Key.Key_E:
            self.stop_recording()
            event.accept()
            return
        if ctrl and not shift and key == Qt.Key.Key_G:
            self.show_channel_epg(self.selected_channel())
            event.accept()
            return
        if ctrl and not shift and key == Qt.Key.Key_Period:
            self.stop_playback()
            event.accept()
            return
        if key in (Qt.Key.Key_VolumeUp, Qt.Key.Key_VolumeDown) or (
            ctrl and not shift and key in (Qt.Key.Key_Up, Qt.Key.Key_Down)
        ):
            self._adjust_volume(5 if key in (Qt.Key.Key_VolumeUp, Qt.Key.Key_Up) else -5)
            event.accept()
            return
        if key in (Qt.Key.Key_VolumeMute, Qt.Key.Key_MediaTogglePlayPause):
            if key == Qt.Key.Key_MediaTogglePlayPause:
                self.toggle_playback()
            else:
                self.toggle_mute()
            event.accept()
            return
        if key == Qt.Key.Key_MediaPlay:
            self.play_channel_by_data(self.selected_channel())
            event.accept()
            return
        if key == Qt.Key.Key_MediaStop:
            self.stop_playback()
            event.accept()
            return

        if self._is_context_menu_key(event):
            focus = QApplication.focusWidget()
            if focus is self.channel_list or (
                focus is not None and self.channel_list.isAncestorOf(focus)
            ):
                self.show_channel_context_menu(None)
            else:
                self.show_video_context_menu(self.video_frame.rect().center())
            event.accept()
            return

        if not self._blocks_plain_keys():
            if key == Qt.Key.Key_F and not ctrl and not shift:
                self.toggle_fullscreen()
                event.accept()
                return
            if key == Qt.Key.Key_M and not ctrl and not shift:
                self.toggle_mute()
                event.accept()
                return
            if key == Qt.Key.Key_P and not ctrl and not shift:
                self.toggle_playback()
                event.accept()
                return
            if key == Qt.Key.Key_S and not ctrl and not shift:
                self._focus_search()
                event.accept()
                return

        super().keyPressEvent(event)

    def toggle_mute(self):
        """Toggle audio mute state"""
        print("Debug: Toggling mute")
        is_muted = self.player.is_muted()
        self.player.set_muted(not is_muted)
        
        self.controls_bar.set_muted(not is_muted)
        if not is_muted:  # Switching to muted
            describe(self.mute_btn, "Unmute", "Turn sound on. Keyboard: M. The button stays pressed while muted.")
            self.mute_btn.setToolTip("Unmute (M)")
            self.statusbar.showMessage("Muted")
            self._show_on_picture("Muted")
            print("Debug: Audio muted")
        else:  # Switching to unmuted
            describe(self.mute_btn, "Mute", "Turn sound off. Keyboard: M. The button stays pressed while muted.")
            self.mute_btn.setToolTip("Mute (M)")
            self.statusbar.showMessage("Sound on")
            self._show_on_picture("Sound on")
            print("Debug: Audio unmuted")

    def show_about(self):
        """Show the about dialog"""
        print("Debug: Showing about dialog")
        about_text = (
            "<div style='text-align: center;'>"
            "<h2>TVHplayer</h2>"
            "<p>Version 3.5.5</p>"
            "<p>A powerful and user-friendly TVHeadend client application.</p>"
            "<p style='margin-top: 20px;'><b>Created by:</b><br>mFat</p>"
            "<p style='margin-top: 20px;'><b>Built with:</b><br>"
            "Python, PyQt6, and VLC</p>"
            "<p style='margin-top: 20px;'>"
            "<a href='https://github.com/mfat/tvhplayer'>Project Website</a>"
            "</p>"
            "<p style='margin-top: 20px; font-size: 11px;'>"
            "This program is free software: you can redistribute it and/or modify "
            "it under the terms of the GNU General Public License as published by "
            "the Free Software Foundation, either version 3 of the License, or "
            "(at your option) any later version.<br><br>"
            "This program is distributed in the hope that it will be useful, "
            "but WITHOUT ANY WARRANTY; without even the implied warranty of "
            "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the "
            "GNU General Public License for more details.<br><br>"
            "You should have received a copy of the GNU General Public License "
            "along with this program. If not, see "
            "<a href='https://www.gnu.org/licenses/'>https://www.gnu.org/licenses/</a>."
            "</p>"
            "</div>"
        )
        msg = QMessageBox()
        msg.setWindowTitle("About TVHplayer")
        msg.setAccessibleName("About TVHplayer")
        msg.setAccessibleDescription("TVHplayer version 3.5.5, created by mFat.")
        msg.setText(about_text)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setMinimumWidth(400)  # Make dialog wider to prevent text wrapping
        msg.exec()

    def show_user_guide(self):
        """Open the user guide documentation"""
        print("Debug: Opening user guide")
        try:
            # Open the GitHub wiki URL in the default web browser
            url = "https://github.com/mfat/tvhplayer/wiki/User-Guide"
            
            # Open URL in the default web browser based on platform
            if platform.system() == "Linux":
                subprocess.Popen(["xdg-open", url])
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", url])
            elif platform.system() == "Windows":
                os.startfile(url)
            else:
                # Fallback using webbrowser module
                import webbrowser
                webbrowser.open(url)
                
            print(f"Opened user guide URL: {url}")
            
        except Exception as e:
            print(f"Error opening user guide URL: {str(e)}")
            QMessageBox.critical(
                self, 
                "Error",
                f"Failed to open user guide: {str(e)}",
                QMessageBox.StandardButton.Ok
            )

    def stop_recording(self):
        """Stop the running recording for the active channel.

        A lone running job is stopped even when no channel is highlighted.
        When several jobs are running, only the active channel is stopped.
        """
        print("Debug: Attempting to stop recordings")
        running = []
        try:
            backend = self.get_backend()
            entries = backend.list_dvr_entries()
            running = [entry for entry in entries if entry.category() == 'recording']
            channel = self.active_channel()
            targets = recordings_to_stop(entries, channel)
            if not targets:
                if len(running) > 1 and channel is not None:
                    self.statusbar.showMessage(f"No recording in progress for {channel.name}")
                elif len(running) > 1:
                    self.statusbar.showMessage("Select a channel to stop its recording")
                else:
                    print("Debug: No active recordings found")
                    self.statusbar.showMessage("No active recordings to stop")
                    self.sync_recording_indicator()
                return
            for entry in targets:
                print(f"Debug: Stopping recording: {entry.title} ({entry.uuid}) on {entry.channel_name}")
                backend.stop_dvr_entry(entry)
            self.channel_recordings_changed([entry for entry in entries if entry not in targets])
            if len(targets) >= len(running):
                self.sync_recording_indicator()
            channel_name = targets[0].channel_name or (channel.name if channel else 'channel')
            if len(targets) == 1:
                self.statusbar.showMessage(f"Stopped recording for {channel_name}")
            else:
                self.statusbar.showMessage(f"Stopped {len(targets)} recordings for {channel_name}")
            self._show_on_picture("Recording stopped")
        except Exception as e:
            print(f"Debug: Error stopping recordings: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Error stopping recordings: {str(e)}")
            if len(running) <= 1:
                self.sync_recording_indicator()
        finally:
            self._refresh_tasks()

    def start_recording_indicator(self):
        """Start the recording indicator with smooth pulsing animation"""
        print("Debug: Starting recording indicator")
        self.is_recording = True
        self.recording_indicator.setText("REC")
        self.recording_indicator.setVisible(True)
        describe(self.recording_indicator, "Recording in progress", "A recording is in progress")
        self.recording_indicator.setProperty("recording", True)
        self.recording_indicator.style().polish(self.recording_indicator)
        
        # Create opacity effect
        self.opacity_effect = QGraphicsOpacityEffect(self.recording_indicator)
        self.recording_indicator.setGraphicsEffect(self.opacity_effect)
        
        # Create and configure the animation
        self.recording_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.recording_animation.setDuration(1000)  # 1 second per pulse
        self.recording_animation.setStartValue(1.0)
        self.recording_animation.setEndValue(0.3)
        self.recording_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.recording_animation.setLoopCount(-1)  # Infinite loop
        
        # Start the animation
        self.recording_animation.start()
        self._sync_record_controls()

    def stop_recording_indicator(self):
        """Stop the recording indicator and its animation"""
        print("Debug: Stopping recording indicator")
        self.is_recording = False
        if self.recording_animation:
            self.recording_animation.stop()
            self.recording_animation = None
        if hasattr(self, 'opacity_effect'):
            self.recording_indicator.setGraphicsEffect(None)
            self.opacity_effect = None
        self.recording_indicator.setText("")
        self.recording_indicator.setVisible(False)
        describe(self.recording_indicator, "Not recording", "Shown only while a recording is in progress")
        self.recording_indicator.setProperty("recording", False)
        self.recording_indicator.style().polish(self.recording_indicator)
        self._sync_record_controls()

    def show_dvr_status(self):
        """Show DVR status dialog"""
        try:
            print("\nDebug: Opening DVR Status Dialog")
            dialog = DVRStatusDialog(self.get_backend(), self)
            dialog.show()
        except Exception as e:
            print(f"Debug: Error showing DVR status: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage("Error showing DVR status")

    def play_url(self, url):
        """Play media from URL"""
        try:
            self._playback_channel = None
            self._show_playback_wait()
            self.player.play(url)
            self.statusbar.showMessage("Starting playback")
        except Exception as e:
            if self._awaiting_playback:
                self._awaiting_playback = False
                self._playback_active = False
                self._set_playback_spinner(False)
                self._protect_video_surface(False)
            QMessageBox.critical(self, "Error", f"Failed to play media: {str(e)}")

    def start_local_recording(self, channel):
        """Record channel stream to local disk using ffmpeg"""
        try:
            if isinstance(channel, dict):
                channel = Channel.from_raw(channel)
            elif isinstance(channel, str):
                selected = self.selected_channel()
                channel = selected if selected and selected.name == channel else None
            if not channel:
                print("Debug: No channel selected for recording")
                self.statusbar.showMessage("Please select a channel to record")
                return

            channel_name = channel.name
            print(f"Debug: Starting local recording for channel: {channel_name}")
            
            # Show file save dialog
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"recording_{channel_name}_{timestamp}.ts"  # Using .ts format initially
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Recording As",
                default_filename,
                "TS Files (*.ts);;MP4 Files (*.mp4);;All Files (*.*)"
            )
            
            if not file_path:  # User cancelled
                print("Debug: Recording cancelled - no file selected")
                return

            stream_url = self.get_backend().stream_url(channel)
            server = self.current_server() or {}
            self.local_recorder.start(
                stream_url,
                file_path,
                server.get('username') or '',
                server.get('password') or '',
            )
            self._recording_channel = channel
            self._recording_stall_noted = False
            self.recording_monitor = QTimer()
            self.recording_monitor.timeout.connect(self.check_recording_status)
            self.recording_monitor.start(2000)
            self.statusbar.showMessage(f"Local recording started: {file_path}")
            self._show_on_picture("Recording to this computer")
            self.start_recording_indicator()
            self._refresh_tasks(server=False)
            
        except Exception as e:
            print(f"Debug: Local recording error: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Local recording error: {str(e)}")

    def check_recording_status(self):
        """Check if the recording is actually working"""
        try:
            status = self.local_recorder.status()
            if not status.exists:
                if status.elapsed > 10:
                    self.stop_local_recording()
                    QMessageBox.warning(self, "Local Recording Status", "Recording file does not exist")
                else:
                    self._refresh_tasks(server=False)
                return
            self._refresh_tasks(server=False)
            if status.return_code is not None:
                if status.size == 0 or status.return_code != 0:
                    self.stop_local_recording()
                    QMessageBox.critical(self, "Recording Error", "Recording failed - check console for errors")
                return
            if status.stalled:
                # Keep the ffmpeg process. Restarting opens a save dialog and
                # would discard the file already being written.
                if not getattr(self, '_recording_stall_noted', False):
                    self._recording_stall_noted = True
                    self.statusbar.showMessage("Local recording stalled")
                return
            self._recording_stall_noted = False
        except Exception as e:
            print(f"Debug: Error checking recording status: {str(e)}")
            QMessageBox.critical(self, "Recording Error", str(e))

    def stop_local_recording(self):
        """Stop local recording"""
        try:
            if hasattr(self, 'recording_monitor') and self.recording_monitor is not None:
                self.recording_monitor.stop()
                self.recording_monitor = None
            self.local_recorder.stop()
            self.statusbar.showMessage("Local recording stopped")
            self._show_on_picture("Recording to this computer stopped")
            self.sync_recording_indicator()
            self._sync_record_controls()
        except Exception as e:
            print(f"Debug: Error stopping local recording: {str(e)}")
            self.statusbar.showMessage(f"Error stopping local recording: {str(e)}")
            self.sync_recording_indicator()
        self._refresh_tasks()

    def closeEvent(self, event):
        """Save configuration when closing the application"""
        if not self._confirm_quit():
            event.ignore()
            return
        self._closing = True
        self.save_config()
        for job in self._playlist_jobs:
            job.cancel()
        if self.builtin is not None:
            self.builtin.shut_down()
        # With the server gone, a running stream test notices within seconds.
        for job in self._playlist_jobs:
            if not job.shutdown(10000):
                print("Debug: A playlist refresh did not stop in time")
        self.local_recorder.stop()
        self._now_next_timer.stop()
        self.logo_loader.shutdown()
        self.close_backend()
        if getattr(self, 'player', None) is not None:
            self.player.close()
        super().closeEvent(event)

    def _builtin_credentials(self):
        supervisor = getattr(self, 'builtin', None)
        if supervisor is None:
            return '', ''
        return supervisor.username, supervisor.password

    def _confirm_quit(self):
        """Ask before quitting would lose a recording."""
        local_recording = ''
        recorder = getattr(self, 'local_recorder', None)
        if recorder is not None and recorder.is_running:
            channel = getattr(self, '_recording_channel', None)
            name = getattr(channel, 'name', '') or 'Unknown channel'
            local_recording = f'{name} ({os.path.basename(recorder.file_path or "")})'
        titles = []
        upcoming = []
        lookup_failed = False
        supervisor = getattr(self, 'builtin', None)
        if supervisor is not None and supervisor.is_running():
            # Ask the built-in server itself, whichever server is selected.
            backend = None
            try:
                server = find_builtin_server(self.servers)
                if server is None:
                    raise TvhError('Built-in server entry is missing')
                backend = create_backend(server)
                entries = backend.list_dvr_entries()
                titles = recording_titles(entries)
                upcoming = upcoming_recordings(entries)
            except Exception:
                lookup_failed = True
            finally:
                if backend is not None:
                    try:
                        backend.close()
                    except Exception:
                        pass
        playlist_updates = [
            job.source.name for job in getattr(self, '_playlist_jobs', []) if job.is_writing()
        ]
        message = quit_confirmation(titles, lookup_failed, upcoming, local_recording, playlist_updates)
        if not message:
            return True
        answer = QMessageBox.question(
            self,
            "Quit TVHplayer?",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_builtin_ready(self, http_port, htsp_port):
        self.servers = apply_builtin_endpoint(
            self.servers, http_port, htsp_port, *self._builtin_credentials()
        )
        self.config['builtin_http_port'] = http_port
        self.config['builtin_htsp_port'] = htsp_port
        self.close_backend()
        if is_builtin_server(self.current_server()):
            self.fetch_channels()
        self._refresh_builtin_playlists()

    def _on_builtin_failed(self, message):
        print(f"Debug: Built-in server failed: {message}")
        self.statusbar.showMessage(message)
        if is_builtin_server(self.current_server()) and not self._channels:
            self._show_channel_state(message, retry=True)

    def _set_builtin_autostart(self, checked):
        self.config['builtin_autostart'] = bool(checked)

    def open_builtin_web(self):
        supervisor = getattr(self, 'builtin', None)
        if supervisor is None or not supervisor.is_running():
            self.statusbar.showMessage("The built-in server is not running.")
            return
        # The page asks for a login. Hand over the password without putting it in the URL.
        QApplication.clipboard().setText(supervisor.password)
        QDesktopServices.openUrl(QUrl(f"http://127.0.0.1:{supervisor.http_port}/"))
        self.statusbar.showMessage(
            f"Log in as \"{supervisor.username}\". The password is on the clipboard."
        )

    def import_playlist(self):
        ImportPlaylistDialog(self, self).exec()

    def show_playlists(self):
        PlaylistsDialog(self, self).exec()

    def server_for_playlist(self, source):
        """The server entry a playlist source was imported to, or None when it is gone."""
        for server in self.import_targets():
            if server_key(server) == source.server:
                return server
        return None

    def claim_playlist(self, source):
        key = (source.server, source.location)
        if key in self._busy_playlists:
            return False
        self._busy_playlists.add(key)
        return True

    def release_playlist(self, source):
        self._busy_playlists.discard((source.server, source.location))

    def is_playlist_busy(self, source):
        return (source.server, source.location) in self._busy_playlists

    def stop_playlist_job(self, source):
        """Stop the update of ``source`` running here. Returns its job, or None."""
        for job in self._playlist_jobs:
            if job.is_running() and (job.source.server, job.source.location) == (source.server, source.location):
                job.cancel()
                return job
        return None

    def forget_playlist_source(self, data):
        gone = PlaylistSource.from_dict(data)
        self.config['playlists'] = [
            source.to_dict() for source in self.playlist_sources()
            if (source.server, source.location) != (gone.server, gone.location)
        ]
        self.save_config()

    def _refresh_builtin_playlists(self):
        """Refresh playlists on the built-in server once per session.

        Playlists are written one at a time. Each one's stream test can take
        hours, so the next playlist starts as soon as only its test is left.
        """
        if self._builtin_playlists_refreshed:
            return
        self._builtin_playlists_refreshed = True
        server = find_builtin_server(self.servers)
        queue = [source for source in self.playlist_sources() if source.server == server_key(server or {})]

        def next_job():
            if not queue or self._closing:
                return
            # Read again: the playlist may have been removed or updated meanwhile.
            source = find_source(self.playlist_sources(), queue.pop(0).location, server_key(server or {}))
            if source is None:
                next_job()
                return
            job = PlaylistJob(self, source, server, parent=self)
            self._playlist_jobs.append(job)
            moved_on = []

            def move_on(*_args):
                if not moved_on:
                    moved_on.append(True)
                    next_job()

            job.finished.connect(lambda message, _skipped: self._playlist_refreshed(message, job.server))
            job.failed.connect(lambda message: self._playlist_refresh_failed(source, message))
            job.checking.connect(move_on)
            job.finished.connect(move_on)
            job.failed.connect(move_on)
            job.start()

        next_job()

    def keep_playlist_job(self, job):
        """Let a playlist's stream test go on after its window closes."""
        job.setParent(self)
        if job not in self._playlist_jobs:
            self._playlist_jobs.append(job)
        job.finished.connect(lambda message, _skipped: self._playlist_refreshed(message, job.server))
        job.failed.connect(self.statusbar.showMessage)

    def show_settings(self):
        SettingsDialog(self, self).exec()

    def hides_dead_channels(self):
        return self.config.get('hide_dead_channels', True)

    def set_hides_dead_channels(self, on):
        self.config['hide_dead_channels'] = bool(on)
        self.save_config()
        if not on:
            self._start_playlist_jobs(PlaylistJob.SHOW)

    def check_playlist_channels(self):
        """Test every imported playlist's streams now and hide those that fail."""
        return self._start_playlist_jobs(PlaylistJob.CHECK)

    def playlist_checks(self):
        return [job for job in self._playlist_jobs if job.action == PlaylistJob.CHECK]

    def _start_playlist_jobs(self, action):
        jobs = []
        for source in self.playlist_sources():
            server = self.server_for_playlist(source)
            if server is None:
                continue
            job = PlaylistJob(self, source, server, action=action, parent=self)
            self.keep_playlist_job(job)
            jobs.append(job)
        # Started after all are listed, so a job that fails at once is still counted.
        for job in jobs:
            job.start()
        return jobs

    def _playlist_refresh_failed(self, source, message):
        # An import the user started is already updating this playlist.
        if message != PLAYLIST_BUSY:
            self.statusbar.showMessage(f"Could not refresh {source.name}. {message}")

    def _playlist_refreshed(self, message, server):
        self.playlist_imported(server)
        self.statusbar.showMessage(message)

    def import_targets(self):
        """Servers a playlist can go to: the built-in server first, then the user's."""
        targets = []
        builtin = find_builtin_server(self.servers)
        if builtin is not None and self.builtin is not None and self.builtin.binary is not None:
            targets.append(builtin)
        targets.extend(server for server in self.servers if not is_builtin_server(server))
        return targets

    def playlist_sources(self):
        return [PlaylistSource.from_dict(raw) for raw in self.config.get('playlists') or []]

    def store_playlist_source(self, data):
        source = PlaylistSource.from_dict(data)
        sources = self.playlist_sources()
        for index, existing in enumerate(sources):
            if existing.server == source.server and existing.location == source.location:
                sources[index] = source
                break
        else:
            sources.append(source)
        self.config['playlists'] = [item.to_dict() for item in sources]
        self.save_config()

    def ensure_server_ready(self, server, on_ready, on_failed):
        """Call ``on_ready`` with a usable server entry, starting the built-in server if needed."""
        if not is_builtin_server(server):
            on_ready(server)
            return
        supervisor = self.builtin
        if supervisor is None or supervisor.binary is None:
            on_failed("The built-in server is not part of this version of TVHplayer.")
            return
        current = find_builtin_server(self.servers)
        if builtin_requests_ready(current, supervisor.is_running()):
            on_ready(current)
            return

        def disconnect():
            for signal, slot in ((supervisor.ready, ready), (supervisor.failed, failed)):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    pass

        def ready(_http_port, _htsp_port):
            disconnect()
            on_ready(find_builtin_server(self.servers))

        def failed(message):
            disconnect()
            on_failed(message)

        supervisor.ready.connect(ready)
        supervisor.failed.connect(failed)
        self.statusbar.showMessage("Starting built-in server...")
        supervisor.start()

    def _same_server(self, first, second):
        if not first or not second:
            return False
        return server_key(first) == server_key(second)

    def is_current_server(self, server):
        return self._same_server(self.current_server(), server)

    def playlist_imported(self, server):
        if self.is_current_server(server):
            self.close_backend()
            self.fetch_channels()

    def playlist_channels_changed(self, server):
        """A running import showed or hid channels on ``server``."""
        if not self.is_current_server(server) or self._channel_reload_timer.isActive():
            return
        wait = self._last_channel_reload + CHANNEL_RELOAD_SECONDS - time.monotonic()
        self._channel_reload_timer.start(max(0, int(wait * 1000)))

    def _reload_changed_channels(self):
        self._last_channel_reload = time.monotonic()
        self.close_backend()
        self.fetch_channels(keep_place=True)

    def show_server(self, server):
        for index, candidate in enumerate(self.servers):
            if self._same_server(candidate, server):
                self.server_combo.setCurrentIndex(index)
                return

    def open_log_folder(self):
        folder = log_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.statusbar.showMessage(f"Logs are in {folder}")

    def show_builtin_log(self):
        supervisor = getattr(self, 'builtin', None)
        text = supervisor.log_text() if supervisor is not None else ''
        dialog = QDialog(self)
        dialog.setWindowTitle("Built-in server log")
        layout = QVBoxLayout(dialog)
        where = QLabel(f"The full log is saved in {log_dir() / SERVER_LOG}")
        where.setWordWrap(True)
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(where)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text or "No log yet.")
        layout.addWidget(view)
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.resize(640, 360)
        dialog.exec()

    def show_server_log(self, server):
        dialog = ServerLogDialog(server, self)
        dialog.exec()
        dialog.deleteLater()

    def show_channel_context_menu(self, position):
        """Show context menu for channel list items"""
        menu = QMenu()
        menu.setAccessibleName("Channel actions")
        
        # Get the item at the position. Keyboard callers pass None and use the selection.
        if position is None:
            row = self.channel_list.currentRow()
            position = self._channel_menu_position()
        else:
            row = self.channel_list.rowAt(position.y())
        if row >= 0:
            channel_item = self.channel_list.item(row, 1)  # Get name column item
            if channel_item is None:
                return
            channel_data = channel_item.data(Qt.ItemDataRole.UserRole)
            
            # Add menu actions
            play_action = menu.addAction("Play")
            play_action.triggered.connect(lambda: self.play_channel_by_data(channel_data))
            record_action = menu.addAction("Record")
            record_action.triggered.connect(lambda: self.start_recording())
            local_record_action = menu.addAction("Record Locally")
            local_record_action.triggered.connect(
                lambda: self.start_local_recording(channel_data))
            
            # Add EPG action
            epg_action = menu.addAction("Show EPG")
            epg_action.triggered.connect(lambda: self.show_channel_epg(channel_data))
            
            # Show the menu at the cursor position
            menu.exec(self.channel_list.viewport().mapToGlobal(position))

    def show_channel_epg(self, channel):
        """Fetch and show EPG data for the selected channel"""
        try:
            if isinstance(channel, dict):
                channel = Channel.from_raw(channel)
            elif isinstance(channel, str):
                selected = self.selected_channel()
                channel = selected if selected and selected.name == channel else None
            if not channel:
                self.statusbar.showMessage("Channel not found")
                return
            print(f"Debug: Fetching EPG for channel: {channel.name}")
            events = self.get_backend().get_epg(channel, limit=24)
            if events:
                dialog = EPGDialog(channel, events, self.get_backend(), self)
                dialog.show()
            else:
                self.statusbar.showMessage("No EPG data available")
        except Exception as e:
            print(f"Debug: Error fetching EPG: {str(e)}")
            self.statusbar.showMessage(f"Error fetching EPG: {str(e)}")

    def play_channel_from_table(self, item):
        """Play channel from table selection"""
        row = item.row()
        channel_item = self.channel_list.item(row, 1)  # Get name column item
        channel_data = channel_item.data(Qt.ItemDataRole.UserRole)  # Original data is stored here
        self.play_channel_by_data(channel_data)

    def play_channel_by_data(self, channel_data):
        """Play channel using channel data"""
        try:
            if channel_data is None:
                self.statusbar.showMessage("Please select a channel to play")
                return
            if not self._server_requests_ready():
                self.statusbar.showMessage("Built-in server is not running yet")
                return
            if isinstance(channel_data, Channel):
                channel = channel_data
            else:
                channel = Channel.from_raw(channel_data)
            self._playback_channel = channel
            stream_url = self.get_backend().stream_url(channel)
            print(f"Debug: Stream URL: {stream_url}")
            self._show_playback_wait()
            self._mark_playing_channel(scroll=True)
            self.player.play(stream_url)
            self.statusbar.showMessage(f"Starting: {channel.name}")
        except Exception as e:
            print(f"Debug: Error in play_channel: {str(e)}")
            if self._awaiting_playback:
                self._awaiting_playback = False
                self._playback_active = False
                self._set_playback_spinner(False)
                self._protect_video_surface(False)
            self._playback_channel = None
            self._mark_playing_channel()
            self.statusbar.showMessage(f"Playback error: {str(e)}")

    def show_server_status(self):
        """Show server status dialog"""
        try:
            dialog = ServerStatusDialog(self.get_backend(), self)
            dialog.show()
        except Exception as e:
            print(f"Debug: Error showing server status: {str(e)}")
            self.statusbar.showMessage("Error showing server status")



class EPGDialog(QDialog):
    def __init__(self, channel, epg_data, backend, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.backend = backend
        self.channel_name = channel.name
        self.setWindowTitle(f"EPG Guide - {self.channel_name}")
        self.setModal(False)
        self.resize(800, 500)
        self.setup_ui(epg_data)
        
    def setup_ui(self, epg_data):
        layout = QVBoxLayout(self)
        self.setAccessibleName(f"Program guide for {self.channel_name}")
        self.setAccessibleDescription("Programs and a button to schedule each one.")
        
        # Create list widget for EPG entries
        self.epg_list = QListWidget()
        describe(
            self.epg_list,
            f"Programs on {self.channel_name}",
            "Each row is a program. Use the Record button to schedule it.",
        )
        layout.addWidget(self.epg_list)
        
        # Add EPG entries to list with record buttons
        for entry in epg_data:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 2, 5, 2)
            start_time = datetime.fromtimestamp(entry.start).strftime('%H:%M')
            stop_time = datetime.fromtimestamp(entry.stop).strftime('%H:%M')
            title = entry.title or 'No title'
            description = entry.description or 'No description'
            summary = f"{start_time} - {stop_time}: {title}"
            info_label = QLabel(summary)
            info_label.setToolTip(description)
            info_label.setAccessibleDescription(description)
            item_layout.addWidget(info_label, stretch=1)
            # The same dark pill with a red dot as Record in the player bar.
            record_btn = QPushButton(" Record")
            record_btn.setIcon(svg_icon(DOT_SVG, RECORD_RED, 12))
            record_btn.setIconSize(QSize(12, 12))
            record_btn.setFixedHeight(32)
            record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            record_btn.setStyleSheet(button_stylesheet(
                f"background: {PILL_DARK}; color: #ededed; font-weight: 500; border: none;"
                " border-radius: 16px; padding: 0 12px; }"
                f" QPushButton:hover {{ background: {PILL_DARK_HOVER};",
                radius=16,
            ))
            record_btn.setToolTip("Schedule Recording")
            describe(record_btn, f"Schedule recording for {title}", description)
            record_btn.clicked.connect(lambda checked, e=entry: self.schedule_recording(e))
            item_layout.addWidget(record_btn)
            list_item = QListWidgetItem(self.epg_list)
            list_item.setSizeHint(item_widget.sizeHint())
            set_item_access(list_item, summary, description)
            self.epg_list.addItem(list_item)
            self.epg_list.setItemWidget(list_item, item_widget)

        # Close button
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setAutoDefault(True)
        layout.addWidget(close_btn)
        
    def schedule_recording(self, entry):
        """Schedule a recording for the selected EPG entry"""
        try:
            print(f"Debug: Scheduling recording for: {entry.title}")
            self.backend.create_dvr_entry(
                self.channel,
                entry.start,
                entry.stop,
                title=entry.title or 'Scheduled Recording',
                description=entry.description or '',
                comment='Scheduled via TVHplayer',
                event_id=entry.event_id,
            )
            QMessageBox.information(
                self,
                "Success",
                f"Recording scheduled successfully for {entry.title or 'Unknown'}"
            )
            parent = self.parent()
            if parent is not None and hasattr(parent, '_refresh_tasks'):
                parent._refresh_tasks()
        except Exception as e:
            print(f"Debug: Error scheduling recording: {str(e)}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to schedule recording: {str(e)}"
            )

def main():
    """Main entry point for the application"""
    configure_logging()
    try:
        # VLC's window embedding is still more reliable on X11 than on Wayland.
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        app = QApplication(sys.argv)
        app.setApplicationName("TVHplayer")
        app.setApplicationDisplayName("TVHplayer")
        app.setDesktopFileName("io.github.mfat.tvhplayer")
        app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
        player = TVHeadendClient()
        player.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"Error starting application: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == '__main__':
    main()
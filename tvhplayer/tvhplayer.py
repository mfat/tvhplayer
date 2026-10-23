from datetime import datetime, timedelta
import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QSplitter, QFrame,
    QListWidget, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox, QApplication,
    QPushButton, QLabel, QSlider, QStatusBar, QSpinBox, QGraphicsOpacityEffect, QFileDialog,
    QMenu, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QSizePolicy, QToolButton,
    QAbstractItemView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QCheckBox,
)
from PyQt6.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, QUrl
from PyQt6.QtGui import QIcon, QAction, QShortcut, QPainter, QPen, QColor, QPixmap, QDesktopServices
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
    )
    from .core.config import ConfigStore
    from .core.dvr import instant_recording_title
    from .core.errors import TvhError
    from .core.models import PROTOCOL_HTTP, PROTOCOL_HTSP, Channel, recordings_to_stop
    from .core.recorder import STALL_LIMIT, LocalRecorder
    from .core.vlc_player import VlcPlayer
    from .core.playlist_sync import PlaylistSource, server_key
    from .builtin_supervisor import BuiltinSupervisor
    from .file_manager import show_in_file_manager
    from .playlist_dialogs import BUSY as PLAYLIST_BUSY, ImportPlaylistDialog, PlaylistJob, PlaylistsDialog
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
    )
    from core.config import ConfigStore
    from core.dvr import instant_recording_title
    from core.errors import TvhError
    from core.models import PROTOCOL_HTTP, PROTOCOL_HTSP, Channel, recordings_to_stop
    from core.recorder import STALL_LIMIT, LocalRecorder
    from core.vlc_player import VlcPlayer
    from core.playlist_sync import PlaylistSource, server_key
    from builtin_supervisor import BuiltinSupervisor
    from file_manager import show_in_file_manager
    from playlist_dialogs import BUSY as PLAYLIST_BUSY, ImportPlaylistDialog, PlaylistJob, PlaylistsDialog
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
import traceback
from pathlib import Path
import logging
import platform




class Logger:
    def __init__(self, name="TVHplayer"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Create logs directory
        log_dir = Path.home() / '.tvhplayer' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create timestamped log file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = log_dir / f'tvhplayer_{timestamp}.log'
        
        # File handler with detailed formatting
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        
        # Console handler with simpler formatting
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Store log file path
        self.log_file = log_file
        
        # Log system info at startup
        self.log_system_info()
    
    def log_system_info(self):
        """Log detailed system information"""
        import platform
        import sys
        try:
            import psutil
        except ImportError:
            psutil = None
        
        self.logger.info("=== System Information ===")
        self.logger.info(f"OS: {platform.platform()}")
        self.logger.info(f"Python: {sys.version}")
        self.logger.info(f"CPU: {platform.processor()}")
        
        if psutil:
            self.logger.info(f"Memory: {psutil.virtual_memory().total / (1024**3):.2f} GB")
            self.logger.info(f"Disk Space: {psutil.disk_usage('/').free / (1024**3):.2f} GB free")
        
        # Log environment variables
        self.logger.info("=== Environment Variables ===")
        for key, value in os.environ.items():
            if any(sensitive in key.lower() for sensitive in ['password', 'secret', 'key', 'token']):
                self.logger.info(f"{key}=<REDACTED>")
            else:
                self.logger.info(f"{key}={value}")
        
        self.logger.info("=== Dependencies ===")
        try:
            import PyQt6
            self.logger.info(f"PyQt6 version: {PyQt6.QtCore.QT_VERSION_STR}")
        except ImportError:
            self.logger.error("PyQt6 not found")
        
        try:
            import vlc
            self.logger.info(f"python-vlc version: {vlc.__version__}")
        except ImportError:
            self.logger.error("python-vlc not found")
        
        try:
            import requests
            self.logger.info(f"requests version: {requests.__version__}")
        except ImportError:
            self.logger.error("requests not found")
    
    def debug(self, msg):
        self.logger.debug(msg)
    
    def info(self, msg):
        self.logger.info(msg)
    
    def warning(self, msg):
        self.logger.warning(msg)
    
    def error(self, msg):
        self.logger.error(msg)
    
    def critical(self, msg):
        self.logger.critical(msg)
    
    def exception(self, msg):
        self.logger.exception(msg)

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

    def __init__(self, parent=None):
        super().__init__(parent)
        # The splitter reparents this pane, so keep the window that owns the backend.
        self._host = parent
        self._server_tasks = []
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
        layout.addWidget(heading)

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

    def refresh(self, server=True):
        """Reload tasks. A failed server fetch keeps the rows already shown."""
        if server:
            fetched, error = self._fetch_server_tasks()
            if error is None:
                self._server_tasks = fetched
                self._set_error("")
            else:
                print(f"Debug: Error refreshing tasks: {error}")
                self._set_error("Couldn't refresh server recordings")
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
        if host is None or not hasattr(host, 'get_backend'):
            return [], None
        try:
            if hasattr(host, 'current_server') and not host.current_server():
                return [], None
            if hasattr(host, '_server_requests_ready') and not host._server_requests_ready():
                return [], None
            entries = host.get_backend().list_dvr_entries()
        except Exception as exc:
            return None, exc
        return self._tasks_from_entries(entries), None

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


class RecordingDurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recording Duration")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setAccessibleName("Recording Duration")
        self.setAccessibleDescription("Choose how long to record the selected channel.")
        
        # Quick duration buttons
        quick_duration_layout = QHBoxLayout()
        
        btn_30min = QPushButton("30 minutes")
        btn_1hr = QPushButton("1 hour") 
        btn_2hr = QPushButton("2 hours")
        btn_4hr = QPushButton("4 hours")
        describe(btn_30min, "30 minutes", "Set the recording length to 30 minutes")
        describe(btn_1hr, "1 hour", "Set the recording length to 1 hour")
        describe(btn_2hr, "2 hours", "Set the recording length to 2 hours")
        describe(btn_4hr, "4 hours", "Set the recording length to 4 hours")
        
        btn_30min.clicked.connect(lambda: self.set_duration(0, 30))
        btn_1hr.clicked.connect(lambda: self.set_duration(1, 0))
        btn_2hr.clicked.connect(lambda: self.set_duration(2, 0))
        btn_4hr.clicked.connect(lambda: self.set_duration(4, 0))
        
        quick_duration_layout.addWidget(btn_30min)
        quick_duration_layout.addWidget(btn_1hr)
        quick_duration_layout.addWidget(btn_2hr)
        quick_duration_layout.addWidget(btn_4hr)
        
        layout.addLayout(quick_duration_layout)

        # Duration spinboxes
        duration_layout = QHBoxLayout()
        
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(0, 24)
        self.hours_spin.setSuffix(" hours")
        describe(self.hours_spin, "Hours", "Recording length in hours, from 0 to 24")
        
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 59)
        self.minutes_spin.setSuffix(" minutes")
        describe(self.minutes_spin, "Minutes", "Additional minutes, from 0 to 59")
        
        duration_layout.addWidget(buddy_label("&Hours:", self.hours_spin))
        duration_layout.addWidget(self.hours_spin)
        duration_layout.addWidget(buddy_label("&Minutes:", self.minutes_spin))
        duration_layout.addWidget(self.minutes_spin)
        
        heading = QLabel("Set a custom recording duration:")
        heading.setAccessibleName("Set a custom recording duration")
        layout.addWidget(heading)
        layout.addLayout(duration_layout)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def set_duration(self, hours, minutes):
        self.hours_spin.setValue(hours)
        self.minutes_spin.setValue(minutes)
    def get_duration(self):
        """Return duration in seconds"""
        hours = self.hours_spin.value()
        minutes = self.minutes_spin.value()
        return (hours * 3600) + (minutes * 60)

class ServerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Server Management")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.setAccessibleName("Server Management")
        self.setAccessibleDescription("Add, edit, or remove TVHeadend servers.")
        # Server list
        self.server_list = QListWidget()
        describe(self.server_list, "Configured servers", "Double-click or press Enter to edit the selected server.")
        layout.addWidget(buddy_label("&Configured servers:", self.server_list))
        layout.addWidget(self.server_list)
        
        # Enter and double-click both activate the selected server.
        self.server_list.itemActivated.connect(lambda _item: self.edit_server())
        
        # Buttons
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("&Add Server")
        edit_btn = QPushButton("&Edit Server")
        remove_btn = QPushButton("&Remove Server")
        
        add_btn.clicked.connect(self.add_server)
        edit_btn.clicked.connect(self.edit_server)
        remove_btn.clicked.connect(self.remove_server)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(remove_btn)
        open_web_btn = QPushButton("Open Web Interface")
        open_web_btn.clicked.connect(self._open_builtin_web)
        describe(
            open_web_btn,
            "Open Web Interface",
            "Open the built-in server web interface in the default browser",
        )
        btn_layout.addWidget(open_web_btn)
        layout.addLayout(btn_layout)
        
        # Close button
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setAutoDefault(True)
        layout.addWidget(close_btn)
        
    def load_servers(self, servers):
        self.servers = servers
        self.server_list.clear()
        for server in self.servers:
            self.server_list.addItem(server['name'])
            
    def add_server(self):
        print("Debug: Opening add server dialog")
        dialog = ServerConfigDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            server = dialog.get_server_config()
            print(f"Debug: Adding new server: {server['name']}")
            self.servers.append(server)
            self.server_list.addItem(server['name'])
            
    def edit_server(self):
        current_row = self.server_list.currentRow()
        if current_row >= 0 and self.servers[current_row].get('builtin'):
            QMessageBox.information(
                self,
                "Built-in Server",
                "The built-in server is managed by TVHplayer. Its address cannot be edited.",
            )
            return
        if current_row >= 0:
            print(f"Debug: Editing server at index {current_row}")
            dialog = ServerConfigDialog(self)
            dialog.set_server_config(self.servers[current_row])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.servers[current_row] = dialog.get_server_config()
                print(f"Debug: Updated server: {self.servers[current_row]['name']}")
                self.server_list.item(current_row).setText(self.servers[current_row]['name'])
                
    def remove_server(self):
        current_row = self.server_list.currentRow()
        if current_row >= 0 and self.servers[current_row].get('builtin'):
            QMessageBox.information(
                self,
                "Built-in Server",
                "The built-in server stays in the server list.",
            )
            return
        if current_row >= 0:
            server_name = self.servers[current_row]['name']
            print(f"Debug: Removing server: {server_name}")
            self.servers.pop(current_row)
            self.server_list.takeItem(current_row)
        else:
            print("Debug: No server selected for removal")

    def _open_builtin_web(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, 'open_builtin_web'):
            parent.open_builtin_web()
            
class ServerConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Server Configuration")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QFormLayout(self)
        self.setAccessibleName("Server Configuration")
        self.setAccessibleDescription("Name, address, protocol, and optional sign-in for a TVHeadend server.")
        
        self.name_input = QLineEdit()
        self.url_input = QLineEdit()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        describe(self.password_input, description="Password is hidden while you type.")
        
        self.name_input.setPlaceholderText("My Server")
        self.url_input.setPlaceholderText("http://127.0.0.1:9981")
        self.username_input.setPlaceholderText("Optional")
        self.password_input.setPlaceholderText("Optional")
        layout.addRow(buddy_label("&Name:", self.name_input), self.name_input)
        layout.addRow(buddy_label("Server &address:", self.url_input), self.url_input)
        describe(self.url_input, description="Include http:// or https:// and the port.")
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItem("HTTP JSON API", PROTOCOL_HTTP)
        self.protocol_combo.addItem("HTSP", PROTOCOL_HTSP)
        layout.addRow(buddy_label("&Protocol:", self.protocol_combo), self.protocol_combo)
        self.htsp_port_input = QSpinBox()
        self.htsp_port_input.setRange(1, 65535)
        self.htsp_port_input.setValue(9982)
        describe(self.htsp_port_input, "HTSP port", "Port for the HTSP protocol, usually 9982.")
        layout.addRow(buddy_label("&HTSP port:", self.htsp_port_input), self.htsp_port_input)
        layout.addRow(buddy_label("&Username:", self.username_input), self.username_input)
        layout.addRow(buddy_label("Pass&word:", self.password_input), self.password_input)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_server_config(self):
        protocol = self.protocol_combo.currentData() or PROTOCOL_HTTP
        return {
            'name': self.name_input.text(),
            'url': self.url_input.text(),
            'username': self.username_input.text(),
            'password': self.password_input.text(),
            'protocol': protocol,
            'htsp_port': self.htsp_port_input.value(),
        }
        
    def set_server_config(self, config):
        self.name_input.setText(config.get('name', ''))
        self.url_input.setText(config.get('url', ''))
        self.username_input.setText(config.get('username', ''))
        self.password_input.setText(config.get('password', ''))
        protocol = (config.get('protocol') or PROTOCOL_HTTP).lower()
        index = self.protocol_combo.findData(protocol)
        self.protocol_combo.setCurrentIndex(index if index >= 0 else 0)
        try:
            self.htsp_port_input.setValue(int(config.get('htsp_port') or 9982))
        except (TypeError, ValueError):
            self.htsp_port_input.setValue(9982)

    def validate_url(self, url):
        """Validate server URL format"""
        if not url.startswith('http://') and not url.startswith('https://'):
            return False, "URL must start with http:// or https://"
            
        # Remove http:// or https:// for validation
        if url.startswith('http://'):
            url = url[7:]
        else:  # https://
            url = url[8:]
            
        # Split URL into host:port and path parts
        url_parts = url.split('/', 1)
        host_port = url_parts[0]
            
        # Split host and port
        if ':' in host_port:
            host, port = host_port.split(':')
            # Validate port
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return False, "Port must be between 1 and 65535"
            except ValueError:
                return False, "Invalid port number"
        else:
            host = host_port
            
        # Validate IP address format if it looks like an IP
        if all(c.isdigit() or c == '.' for c in host):
            parts = host.split('.')
            if len(parts) != 4:
                return False, "Invalid IP address format"
            for part in parts:
                try:
                    num = int(part)
                    if num < 0 or num > 255:
                        return False, "IP numbers must be between 0 and 255"
                except ValueError:
                    return False, "Invalid IP address format"
                    
        return True, ""

    def accept(self):
        print("Debug: Validating server configuration")
        config = self.get_server_config()
        print(f"Debug: Server config: {config['name']} @ {config['url']}")
        
        if not config['name']:
            QMessageBox.warning(self, "Invalid Configuration",
                              "Please provide a server name")
            return
            
        if not config['url']:
            QMessageBox.warning(self, "Invalid Configuration",
                              "Please provide a server URL")
            return
            
        # Validate URL format
        is_valid, error_msg = self.validate_url(config['url'])
        if not is_valid:
            QMessageBox.warning(self, "Invalid Configuration",
                              f"Invalid server URL: {error_msg}")
            return
            
        super().accept()
class ConnectionErrorDialog(QDialog):
    def __init__(self, server_name, error_msg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connection Error")
        self.setup_ui(server_name, error_msg)
        
    def setup_ui(self, server_name, error_msg):
        layout = QVBoxLayout(self)
        message = (
            f"Failed to connect to server: {server_name}\n"
            f"Error: {error_msg}\n\n"
            "Would you like to retry the connection?"
        )
        self.setAccessibleName("Connection Error")
        self.setAccessibleDescription(message)
        
        # Error icon and message
        message_layout = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(QMessageBox.standardIcon(QMessageBox.Icon.Critical))
        icon_label.setAccessibleName("Error")
        icon_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        message_layout.addWidget(icon_label)
        
        error_text = QLabel(message)
        error_text.setWordWrap(True)
        error_text.setAccessibleName(message)
        message_layout.addWidget(error_text)
        layout.addLayout(message_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        retry_btn = QPushButton("&Retry")
        abort_btn = QPushButton("&Abort")
        retry_btn.setDefault(True)
        retry_btn.setAutoDefault(True)
        
        retry_btn.clicked.connect(self.accept)
        abort_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(retry_btn)
        button_layout.addWidget(abort_btn)
        layout.addLayout(button_layout)

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
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background-color: black;")
        self.hide()

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
        caption = QRectF(0, rect.bottom() + 12, self.width(), 24)
        painter.drawText(caption, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Starting…")
        painter.end()


class TVHeadendClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setup_paths()
        self.config_store = ConfigStore()
        self.config_file = str(self.config_store.path)
        self.config_dir = str(self.config_store.path.parent)
        self.config = self.config_store.data
        print(f"Debug: Config file location: {self.config_file}")
        print(f"Debug: Current config: {json.dumps(self.config, indent=2)}")
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
            self.builtin.status_changed.connect(lambda _status: self._sync_builtin_controls())
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
        self._sync_builtin_controls()

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
        # Always use app_dir/icons path
        icon_path = self.app_dir / 'icons' / icon_name
        if not icon_path.exists():
            print(f"Warning: Icon not found: {icon_path}")
            return None
        return str(icon_path)
    
    def setup_ui(self):
        """Setup the UI elements"""

        
        # Create buttons with icons
        self.play_btn = QAction(QIcon(self.get_icon('play.svg')), 'Play', self)
        self.stop_btn = QAction(QIcon(self.get_icon('stop.svg')), 'Stop', self)
        self.record_btn = QAction(QIcon(self.get_icon('record.svg')), 'Record', self)
        self.stop_record_btn = QAction(QIcon(self.get_icon('stoprec.svg')), 'Stop Recording', self)
        

        
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

        # Add Settings action to View menu
        #settings_action = QAction("Settings", self)
        ##view_menu.addAction(settings_action)
        
        import_playlist_action = QAction("&Import Playlist…", self)
        import_playlist_action.setShortcut("Ctrl+I")
        import_playlist_action.triggered.connect(self.import_playlist)
        file_menu.addAction(import_playlist_action)
        playlists_action = QAction("&Playlists…", self)
        playlists_action.triggered.connect(self.show_playlists)
        file_menu.addAction(playlists_action)
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
        self.open_web_btn = QPushButton("Open Web Interface")
        self.open_web_btn.setVisible(False)
        self.open_web_btn.clicked.connect(self.open_builtin_web)
        describe(
            self.open_web_btn,
            "Open Web Interface",
            "Open the built-in server web interface in the default browser",
        )
        self.builtin_log_btn = QPushButton("Server log")
        self.builtin_log_btn.setVisible(False)
        self.builtin_log_btn.clicked.connect(self.show_builtin_log)
        describe(self.builtin_log_btn, "Server log", "Show the built-in server log")
        self.builtin_autostart = QCheckBox("Start with TVHplayer")
        self.builtin_autostart.setVisible(False)
        self.builtin_autostart.setChecked(bool(self.config.get('builtin_autostart')))
        self.builtin_autostart.toggled.connect(self._set_builtin_autostart)
        describe(
            self.builtin_autostart,
            "Start with TVHplayer",
            "Start the built-in server when TVHplayer opens",
        )
        server_layout.addWidget(self.open_web_btn)
        server_layout.addWidget(self.builtin_log_btn)
        server_layout.addWidget(self.builtin_autostart)
        left_layout.addLayout(server_layout)
        
    

        # Channel list
        self.channel_list = QTableWidget()
        self.channel_list.setColumnCount(3)
        self.channel_list.setHorizontalHeaderLabels(['Number', 'Channel Name', 'Status'])
        describe(
            self.channel_list,
            "Channels",
            "Channel numbers, names, and playing status. Type to jump to a channel. "
            "Press Enter to play. Press Shift+F10 for more actions.",
        )
        self.channel_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.channel_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.channel_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.channel_list.verticalHeader().setVisible(False)
        self.channel_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.channel_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.channel_list.setSortingEnabled(True)
        self.channel_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        # Connect double-click to play
        self.channel_list.itemDoubleClicked.connect(self.play_channel_from_table)
        
        # Connect context menu
        self.channel_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_list.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.channel_list.installEventFilter(self)
        
        left_layout.addWidget(self.channel_list)
        
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
        
        # Player controls
        self.controls_bar = QWidget()
        controls_layout = QHBoxLayout(self.controls_bar)
        controls_layout.setContentsMargins(0, 0, 0, 0)
       # Create frame for play/stop buttons
        playback_frame = QFrame()
        if not prefers_high_contrast():
            playback_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}")
        playback_frame.setAccessibleName("Playback")
        playback_frame.setWindowTitle("Playback")
        playback_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        playback_frame.setLineWidth(5)  # Make frame thicker
        playback_layout = QHBoxLayout(playback_frame)
        
        # Play button
        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setIcon(QIcon(f"{self.icons_dir}/play.svg"))
        self.play_btn.setIconSize(QSize(48, 48))
        self.play_btn.setStyleSheet(button_stylesheet("border-radius: 24px;", radius=24))
        self.play_btn.clicked.connect(lambda: self.play_channel_by_data(self.selected_channel()))
        describe(self.play_btn, "Play", "Play the selected channel. Keyboard: P, or Enter on the channel list.")
        self.play_btn.setToolTip("Play the selected channel (P)")
        playback_layout.addWidget(self.play_btn)
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setFixedSize(48, 48)
        self.stop_btn.setIcon(QIcon(f"{self.icons_dir}/stop.svg"))
        self.stop_btn.setIconSize(QSize(48, 48))
        self.stop_btn.setStyleSheet(button_stylesheet("border-radius: 24px;", radius=24))
        self.stop_btn.clicked.connect(self.stop_playback)
        describe(self.stop_btn, "Stop", "Stop playback. Keyboard: Ctrl+.")
        self.stop_btn.setToolTip("Stop playback (Ctrl+.)")
        playback_layout.addWidget(self.stop_btn)
        
        controls_layout.addWidget(playback_frame)
        
        # Create frame for record buttons
        record_frame = QFrame()
        if not prefers_high_contrast():
            record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}")
        record_frame.setAccessibleName("Server recording")
        record_frame.setWindowTitle("Recording")
        record_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        record_frame.setLineWidth(5)  # Make frame thicker
        record_layout = QHBoxLayout(record_frame)
        
        # Start Record button
        self.start_record_btn = QPushButton()
        self.start_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.start_record_btn.setIcon(QIcon(f"{self.icons_dir}/record.svg"))
        self.start_record_btn.setIconSize(QSize(48, 48))
        self.start_record_btn.setStyleSheet(button_stylesheet("border-radius: 24px;", radius=24))
        describe(self.start_record_btn, "Record on server", "Record the selected channel on the TVHeadend server. Keyboard: Ctrl+R.")
        self.start_record_btn.setToolTip("Record on the server (Ctrl+R)")
        self.start_record_btn.clicked.connect(self.start_recording)
        record_layout.addWidget(self.start_record_btn)

        # Stop Record button 
        self.stop_record_btn = QPushButton()
        self.stop_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.stop_record_btn.setIcon(QIcon(f"{self.icons_dir}/stoprec.svg"))
        self.stop_record_btn.setIconSize(QSize(48, 48))
        self.stop_record_btn.setStyleSheet(button_stylesheet("border-radius: 24px;", radius=24))
        describe(self.stop_record_btn, "Stop server recording", "Stop the recording on the TVHeadend server. Keyboard: Ctrl+E.")
        self.stop_record_btn.setToolTip("Stop the server recording (Ctrl+E)")
        self.stop_record_btn.clicked.connect(self.stop_recording)
        record_layout.addWidget(self.stop_record_btn)
        
        controls_layout.addWidget(record_frame)
        
        # Create frame for local record buttons
        local_record_frame = QFrame()
        if not prefers_high_contrast():
            local_record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}")
        local_record_frame.setAccessibleName("Local recording")
        local_record_frame.setWindowTitle("Local Recording")
        local_record_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        local_record_layout = QHBoxLayout(local_record_frame)

        # Start Local Record button
        self.start_local_record_btn = QPushButton()
        self.start_local_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.start_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/reclocal.svg"))
        self.start_local_record_btn.setIconSize(QSize(48, 48))
        self.start_local_record_btn.setStyleSheet(button_stylesheet("border-radius: 24px;", radius=24))
        describe(
            self.start_local_record_btn,
            "Record locally",
            "Save the selected channel on this computer. Keyboard: Ctrl+Shift+R.",
        )
        self.start_local_record_btn.setToolTip("Record on this computer (Ctrl+Shift+R)")
        self.start_local_record_btn.clicked.connect(
            lambda: self.start_local_recording(self.selected_channel())
        )
        local_record_layout.addWidget(self.start_local_record_btn)

        # Stop Local Record button
        self.stop_local_record_btn = QPushButton()
        self.stop_local_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.stop_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/stopreclocal.svg"))
        self.stop_local_record_btn.setIconSize(QSize(48, 48))
        self.stop_local_record_btn.setStyleSheet(button_stylesheet("border-radius: 24px;", radius=24))
        describe(
            self.stop_local_record_btn,
            "Stop local recording",
            "Stop the recording saved on this computer. Keyboard: Ctrl+Shift+E.",
        )
        self.stop_local_record_btn.setToolTip("Stop the recording on this computer (Ctrl+Shift+E)")
        self.stop_local_record_btn.clicked.connect(self.stop_local_recording)
        local_record_layout.addWidget(self.stop_local_record_btn)

        controls_layout.addWidget(local_record_frame)

        

        # Volume slider and mute button
        # Mute button with icons for different states
        
        
        
        self.mute_btn = QPushButton()
        self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/unmute.svg"))
        self.mute_btn.setIconSize(QSize(32, 32))
        self.mute_btn.setFixedSize(32, 32)  # Remove extra parenthesis
        self.mute_btn.setCheckable(True)  # Make the button checkable
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.mute_btn.setStyleSheet(button_stylesheet("border: none;"))
        describe(self.mute_btn, "Mute", "Turn sound off. Keyboard: M. The button stays pressed while muted.")
        self.mute_btn.setToolTip("Mute (M)")

        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(150)  # Set fixed width to make slider less wide
        self.volume_slider.setSingleStep(1)
        self.volume_slider.setPageStep(10)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        describe(self.volume_slider, "Volume", "Playback volume from 0 to 100. Keyboard: Ctrl+Up and Ctrl+Down.")
        self.volume_slider.setToolTip("Volume")
        
        # Fullscreen button with icon
        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setIcon(QIcon(f"{self.icons_dir}/fullscreen.svg"))
        self.fullscreen_btn.setIconSize(QSize(32, 32))
        self.fullscreen_btn.setFixedSize(32, 32)
        self.fullscreen_btn.setCheckable(True)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_btn.setStyleSheet(button_stylesheet("border: none;"))
        describe(self.fullscreen_btn, "Fullscreen", "Fill the screen with the picture. Keyboard: F11 or F. Escape leaves fullscreen.")
        self.fullscreen_btn.setToolTip("Fullscreen (F11)")
        
        controls_layout.addStretch()  # Add stretch to push widgets to the right
        controls_layout.addWidget(self.mute_btn)
        controls_layout.addWidget(self.volume_slider)
        controls_layout.addWidget(self.fullscreen_btn)
        self.right_layout.addWidget(self.controls_bar)
        
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
        self._apply_tab_order()
        self.tasks_pane.refresh()

    def _apply_tab_order(self):
        """Follow the visual order: server, channels, search, picture, then controls."""
        order = [
            self.server_combo,
            self.manage_servers_btn,
            self.channel_list,
            self.search_box,
            self.video_frame,
            self.play_btn,
            self.stop_btn,
            self.start_record_btn,
            self.stop_record_btn,
            self.start_local_record_btn,
            self.stop_local_record_btn,
            self.mute_btn,
            self.volume_slider,
            self.fullscreen_btn,
            self.tasks_pane.search_box,
            self.tasks_pane.status_combo,
            self.tasks_pane.task_table,
            self.tasks_pane.action_btn,
            self.tasks_pane.reveal_btn,
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

    def _set_channel_row_playing(self, row, channel, is_playing, colors):
        table = self.channel_list
        status_item = table.item(row, 2)
        if status_item is None:
            status_item = QTableWidgetItem()
            table.setItem(row, 2, status_item)
        status = "Playing" if is_playing else ""
        if status_item.text() != status:
            status_item.setText(status)
        if is_playing and channel is not None:
            set_item_access(status_item, "Playing", f"{channel.name} is playing")
        else:
            status_item.setData(Qt.ItemDataRole.AccessibleTextRole, None)
            status_item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, None)
            status_item.setToolTip("")
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is None:
                continue
            if is_playing and colors is not None:
                item.setBackground(colors[0])
                item.setForeground(colors[1])
            else:
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
        name_item = table.item(row, 1)
        if name_item is None or channel is None:
            return
        description = f"Channel {channel.number}, {channel.name}."
        if is_playing:
            description += " Playing."
        description += " Press Enter to play."
        set_item_access(name_item, channel.name, description)

    def _mark_playing_channel(self, scroll=False):
        """Highlight the channel that is on, and write Playing in its status cell.

        Selection can move to another row. The playing row keeps its own color
        and status so the list still shows what is on.
        """
        table = getattr(self, 'channel_list', None)
        if table is None:
            return
        playing = self._playing_channel()
        colors = row_emphasis('playing' if playing is not None else None)
        sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)
        playing_item = None
        try:
            for row in range(table.rowCount()):
                channel = self.channel_from_row(row)
                is_playing = playing is not None and self._channels_match(channel, playing)
                self._set_channel_row_playing(row, channel, is_playing, colors)
                if is_playing:
                    playing_item = table.item(row, 1)
        finally:
            table.setSortingEnabled(sorting)
        if scroll and playing_item is not None:
            table.scrollToItem(playing_item)
            table.setCurrentItem(playing_item)

    def fetch_channels(self):
        """Fetch channel list from current TVHeadend server"""
        server = None
        try:
            if not self.servers:
                print("Debug: No servers configured")
                self.statusbar.showMessage("No servers configured")
                return
                
            server = self.current_server()
            if is_builtin_server(server) and not self._server_requests_ready():
                self.channel_list.setRowCount(0)
                supervisor = getattr(self, 'builtin', None)
                if supervisor is None:
                    self.statusbar.showMessage("Built-in server is not available in this build.")
                    return
                if supervisor.binary is None:
                    self.statusbar.showMessage("Built-in Tvheadend is not packaged in this build.")
                    print("Debug: Built-in Tvheadend binary was not found in this build.")
                    return
                self.statusbar.showMessage("Starting built-in server...")
                supervisor.start()
                return
            print(f"Debug: Fetching channels from server: {server['url']}")
            self.statusbar.showMessage("Connecting to server...")
            channels = self.get_backend().get_channels()
            self.channel_list.setSortingEnabled(False)
            self.channel_list.setRowCount(0)
            for channel in channels:
                row = self.channel_list.rowCount()
                self.channel_list.insertRow(row)
                number_item = QTableWidgetItem()
                number_item.setData(Qt.ItemDataRole.DisplayRole, channel.number)
                set_item_access(number_item, f"Channel {channel.number}", "Channel number")
                self.channel_list.setItem(row, 0, number_item)
                name_item = QTableWidgetItem(channel.name)
                name_item.setData(Qt.ItemDataRole.UserRole, channel.to_raw())
                set_item_access(
                    name_item,
                    channel.name,
                    f"Channel {channel.number}, {channel.name}. Press Enter to play.",
                )
                self.channel_list.setItem(row, 1, name_item)
                self.channel_list.setItem(row, 2, QTableWidgetItem(""))
            self.channel_list.setSortingEnabled(True)
            self._mark_playing_channel(scroll=True)
            self.statusbar.showMessage("Channels loaded successfully")
        except Exception as e:
            print(f"Debug: Error in fetch_channels: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            
            # Show error dialog
            dialog = ConnectionErrorDialog(
                (server or {}).get('name', 'server'),
                f"Unexpected error: {str(e)}", 
                self
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                print("Debug: Retrying connection...")
                self.close_backend()
                self.fetch_channels()
            else:
                print("Debug: Connection attempt aborted by user")
                self.statusbar.showMessage("Connection aborted")
                self.channel_list.clear()
        

    def start_recording(self):
        print("Debug: Starting recording")
        try:
            channel = self.selected_channel()
            if not channel:
                print("Debug: No channel selected for recording")
                self.statusbar.showMessage("Please select a channel to record")
                return

            duration_dialog = RecordingDurationDialog(self)
            if duration_dialog.exec() != QDialog.DialogCode.Accepted:
                print("Debug: Recording cancelled by user")
                return
            
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
            
    def stop_playback(self):
        """Stop current playback"""
        print("Debug: Stopping playback")
        self._awaiting_playback = False
        self._playback_active = False
        self._playback_channel = None
        self._mark_playing_channel()
        self._set_playback_spinner(False)
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
        self._set_playback_spinner(True)
        if hasattr(self, 'video_frame'):
            self.video_frame.setUpdatesEnabled(False)

    def _protect_video_surface(self, playing):
        """While a channel is on, do not let Qt paint or flash the splash."""
        self._playback_active = playing
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
        self._awaiting_playback = False
        self._set_playback_spinner(False)
        self._protect_video_surface(True)
        self._mark_playing_channel()
        channel = getattr(self, '_playback_channel', None)
        if channel is not None:
            self.statusbar.showMessage(f"Playing: {channel.name}")
            self._show_on_picture(f"{channel.number}  {channel.name}" if channel.number else channel.name)

    def _on_playback_failed(self):
        self._awaiting_playback = False
        self._playback_active = False
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
            self.controls_bar.hide()
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
            self.controls_bar.show()
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
            self.fullscreen_btn.setChecked(self.is_fullscreen)
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
            self._sync_builtin_controls()

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
            self.fetch_channels()
            pane = getattr(self, 'tasks_pane', None)
            if pane is not None:
                pane.clear_server_tasks()
                pane.refresh()
        self._sync_builtin_controls()

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
            idle_splash = getattr(self, 'idle_splash', None)
            if idle_splash is not None and idle_splash.isVisible():
                idle_splash.setGeometry(player_container.rect())
            spinner = getattr(self, 'playback_spinner', None)
            if spinner is not None and spinner.isVisible():
                spinner.setGeometry(player_container.rect())
                spinner.raise_()
            return False
        video_frame = getattr(self, 'video_frame', None)
        if video_frame is not None and obj is video_frame:
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
                if self.player and self.player.is_playing():
                    self.stop_playback()
                else:
                    self.play_channel_by_data(self.selected_channel())
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
                self.play_channel_by_data(self.selected_channel())
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
        
        if not is_muted:  # Switching to muted
            self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/mute.svg"))
            self.mute_btn.setChecked(True)
            describe(self.mute_btn, "Unmute", "Turn sound on. Keyboard: M. The button stays pressed while muted.")
            self.mute_btn.setToolTip("Unmute (M)")
            self.statusbar.showMessage("Muted")
            self._show_on_picture("Muted")
            print("Debug: Audio muted")
        else:  # Switching to unmuted
            self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/unmute.svg"))
            self.mute_btn.setChecked(False)
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

    def toggle_recording(self):
        """Toggle between starting and stopping recording"""
        if self.record_btn.isChecked():
            self.start_recording()
        else:
            self.stop_recording()

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
        except Exception as e:
            print(f"Debug: Error stopping local recording: {str(e)}")
            self.statusbar.showMessage(f"Error stopping local recording: {str(e)}")
            self.sync_recording_indicator()
        self._refresh_tasks()

    def closeEvent(self, event):
        """Save configuration when closing the application"""
        if not self._confirm_builtin_quit():
            event.ignore()
            return
        self.save_config()
        if self.builtin is not None:
            self.builtin.stop()
        self.local_recorder.stop()
        self.close_backend()
        if getattr(self, 'player', None) is not None:
            self.player.close()
        super().closeEvent(event)

    def _builtin_credentials(self):
        supervisor = getattr(self, 'builtin', None)
        if supervisor is None:
            return '', ''
        return supervisor.username, supervisor.password

    def _confirm_builtin_quit(self):
        supervisor = getattr(self, 'builtin', None)
        if supervisor is None or not supervisor.is_running():
            return True
        titles = []
        lookup_failed = False
        # Ask the built-in server itself, whichever server is selected.
        backend = None
        try:
            server = find_builtin_server(self.servers)
            if server is None:
                raise TvhError('Built-in server entry is missing')
            backend = create_backend(server)
            titles = recording_titles(backend.list_dvr_entries())
        except Exception:
            lookup_failed = True
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
        message = quit_confirmation(titles, lookup_failed)
        if not message:
            return True
        answer = QMessageBox.question(
            self,
            "Recording in progress",
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
        self._sync_builtin_controls()
        if is_builtin_server(self.current_server()):
            self.fetch_channels()
        self._refresh_builtin_playlists()

    def _on_builtin_failed(self, message):
        print(f"Debug: Built-in server failed: {message}")
        self.statusbar.showMessage(message)
        self._sync_builtin_controls()

    def _set_builtin_autostart(self, checked):
        self.config['builtin_autostart'] = bool(checked)

    def _sync_builtin_controls(self):
        buttons = (
            getattr(self, 'open_web_btn', None),
            getattr(self, 'builtin_log_btn', None),
            getattr(self, 'builtin_autostart', None),
        )
        if buttons[0] is None:
            return
        selected = is_builtin_server(self.current_server())
        running = self.builtin is not None and self.builtin.is_running()
        self.open_web_btn.setVisible(selected)
        self.builtin_log_btn.setVisible(selected)
        self.builtin_autostart.setVisible(selected)
        self.open_web_btn.setEnabled(selected and running)

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

    def forget_playlist_source(self, data):
        gone = PlaylistSource.from_dict(data)
        self.config['playlists'] = [
            source.to_dict() for source in self.playlist_sources()
            if (source.server, source.location) != (gone.server, gone.location)
        ]
        self.save_config()

    def _refresh_builtin_playlists(self):
        """Refresh playlists on the built-in server once per session, one at a time."""
        if self._builtin_playlists_refreshed:
            return
        self._builtin_playlists_refreshed = True
        server = find_builtin_server(self.servers)
        queue = [source for source in self.playlist_sources() if source.server == server_key(server or {})]

        def next_job(*_args):
            if not queue:
                return
            source = queue.pop(0)
            job = PlaylistJob(self, source, server, parent=self)
            job.finished.connect(lambda message, _skipped: self._playlist_refreshed(message, job.server))
            job.failed.connect(lambda message: self._playlist_refresh_failed(source, message))
            job.finished.connect(next_job)
            job.failed.connect(next_job)
            job.start()

        next_job()

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

    def show_server(self, server):
        for index, candidate in enumerate(self.servers):
            if self._same_server(candidate, server):
                self.server_combo.setCurrentIndex(index)
                return

    def show_builtin_log(self):
        supervisor = getattr(self, 'builtin', None)
        text = supervisor.log_text() if supervisor is not None else ''
        dialog = QDialog(self)
        dialog.setWindowTitle("Built-in server log")
        layout = QVBoxLayout(dialog)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text or "No log yet.")
        layout.addWidget(view)
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.resize(640, 360)
        dialog.exec()

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

    def filter_channels(self, search_text):
        """Filter channel list based on search text"""
        search_text = search_text.lower()
        for row in range(self.channel_list.rowCount()):
            item = self.channel_list.item(row, 1)  # Get name column item
            number_item = self.channel_list.item(row, 0)
            if item:
                channel_name = item.text().lower()
                number = number_item.text().lower() if number_item else ""
                self.channel_list.setRowHidden(
                    row,
                    search_text not in channel_name and search_text not in number,
                )




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
            "Each row is a program. Use the Rec button to schedule it.",
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
            record_btn = QPushButton("Rec")
            record_btn.setMinimumWidth(48)
            record_btn.setFixedHeight(32)
            record_btn.setStyleSheet(button_stylesheet(
                "border: 1px solid palette(mid); border-radius: 16px; padding: 0px;",
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
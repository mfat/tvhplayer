from datetime import datetime, timedelta
import os
import sys
import vlc
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QComboBox, QSplitter, QFrame,
    QListWidget, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox, QApplication,
    QPushButton, QLabel, QSlider, QStatusBar, QGridLayout, QMenuBar, QRadioButton, QSpinBox, QGraphicsOpacityEffect, QFileDialog,
    QMenu, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QSizePolicy, QToolButton, QCheckBox, QGroupBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, QRect, QEvent
from PyQt6.QtGui import QIcon, QPainter, QColor, QKeySequence, QPalette, QAction, QShortcut
import json
import requests
# Replace this line:
#from . import resources_rc

# With this more flexible import approach:
try:
    from . import resources_rc  # Try package import first
except ImportError:
    import resources_rc  # Fall back to direct import when running from source
try:
    from .core.backend import create_backend
    from .core.config import ConfigStore
    from .core.errors import TvhError
    from .core.models import PROTOCOL_HTTP, PROTOCOL_HTSP, Channel, recordings_to_stop
    from .core.recorder import LocalRecorder
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.backend import create_backend
    from core.config import ConfigStore
    from core.errors import TvhError
    from core.models import PROTOCOL_HTTP, PROTOCOL_HTSP, Channel, recordings_to_stop
    from core.recorder import LocalRecorder
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
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Upcoming/Current recordings tab
        self.upcoming_table = QTableWidget()
        self.upcoming_table.setColumnCount(5)  # Added one more column for status
        self.upcoming_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Duration', 'Status'])
        self.upcoming_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.upcoming_table, "Upcoming/Current")  # Changed tab title
        
        # Finished recordings tab
        self.finished_table = QTableWidget()
        self.finished_table.setColumnCount(4)
        self.finished_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Duration'])
        self.finished_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.finished_table, "Finished")
        
        # Failed recordings tab
        self.failed_table = QTableWidget()
        self.failed_table.setColumnCount(4)
        self.failed_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Error'])
        self.failed_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.failed_table, "Failed")
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
    def update_status(self):
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
                    upcoming.append((entry.channel_name, entry.title, start, duration, True))
                elif bucket == 'upcoming':
                    upcoming.append((entry.channel_name, entry.title, start, duration, False))
                elif bucket == 'finished':
                    finished.append((entry.channel_name, entry.title, start, duration))
                else:
                    error_msg = entry.error
                    if not error_msg and entry.errors:
                        error_msg = f"Recording failed with {entry.errors} errors"
                    if not error_msg and entry.errorcode:
                        error_msg = f"Error code: {entry.errorcode}"
                    failed.append((entry.channel_name, entry.title, start, error_msg or 'Unknown error'))

            upcoming.sort(key=lambda x: x[2])
            self.upcoming_table.setRowCount(len(upcoming))
            for i, (channel, title, start, duration, is_recording) in enumerate(upcoming):
                self.upcoming_table.setItem(i, 0, QTableWidgetItem(channel))
                self.upcoming_table.setItem(i, 1, QTableWidgetItem(title))
                self.upcoming_table.setItem(i, 2, QTableWidgetItem(start.strftime('%Y-%m-%d %H:%M')))
                self.upcoming_table.setItem(i, 3, QTableWidgetItem(str(duration)))
                self.upcoming_table.setItem(i, 4, QTableWidgetItem("Recording" if is_recording else "Scheduled"))
                if is_recording:
                    for col in range(5):
                        self.upcoming_table.item(i, col).setBackground(Qt.GlobalColor.green)

            finished.sort(key=lambda x: x[2], reverse=True)
            self.finished_table.setRowCount(len(finished))
            for i, (channel, title, start, duration) in enumerate(finished):
                self.finished_table.setItem(i, 0, QTableWidgetItem(channel))
                self.finished_table.setItem(i, 1, QTableWidgetItem(title))
                self.finished_table.setItem(i, 2, QTableWidgetItem(start.strftime('%Y-%m-%d %H:%M')))
                self.finished_table.setItem(i, 3, QTableWidgetItem(str(duration)))

            failed.sort(key=lambda x: x[2], reverse=True)
            self.failed_table.setRowCount(len(failed))
            for i, (channel, title, start, error) in enumerate(failed):
                self.failed_table.setItem(i, 0, QTableWidgetItem(channel))
                self.failed_table.setItem(i, 1, QTableWidgetItem(title))
                self.failed_table.setItem(i, 2, QTableWidgetItem(start.strftime('%Y-%m-%d %H:%M')))
                self.failed_table.setItem(i, 3, QTableWidgetItem(error))
                for col in range(4):
                    self.failed_table.item(i, col).setBackground(Qt.GlobalColor.red)
        except Exception as e:
            print(f"Debug: Error updating DVR status: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
    
    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)

class RecordingDurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recording Duration")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Quick duration buttons
        quick_duration_layout = QHBoxLayout()
        
        btn_30min = QPushButton("30 minutes")
        btn_1hr = QPushButton("1 hour") 
        btn_2hr = QPushButton("2 hours")
        btn_4hr = QPushButton("4 hours")
        
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
        
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 59)
        self.minutes_spin.setSuffix(" minutes")
        
        duration_layout.addWidget(self.hours_spin)
        duration_layout.addWidget(self.minutes_spin)
        
        layout.addWidget(QLabel("Set custome recording duration:"))
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
        
        # Server list
        self.server_list = QListWidget()
        layout.addWidget(QLabel("Configured Servers:"))
        layout.addWidget(self.server_list)
        
        # Connect double-click signal
        self.server_list.itemDoubleClicked.connect(self.edit_server)
        
        # Buttons
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Server")
        edit_btn = QPushButton("Edit Server")
        remove_btn = QPushButton("Remove Server")
        
        add_btn.clicked.connect(self.add_server)
        edit_btn.clicked.connect(self.edit_server)
        remove_btn.clicked.connect(self.remove_server)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(remove_btn)
        layout.addLayout(btn_layout)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
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
        if current_row >= 0:
            server_name = self.servers[current_row]['name']
            print(f"Debug: Removing server: {server_name}")
            self.servers.pop(current_row)
            self.server_list.takeItem(current_row)
        else:
            print("Debug: No server selected for removal")
            
class ServerConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Server Configuration")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QFormLayout(self)
        
        self.name_input = QLineEdit()
        self.url_input = QLineEdit()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        # Style placeholder text
        placeholder_color = QColor(100, 100, 100)  # Dark gray color
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, placeholder_color)
        self.setPalette(palette)
        
        # Apply placeholder text
        layout.addRow("Name:", self.name_input)
        self.name_input.setPlaceholderText("My Server")
        layout.addRow("Server address:", self.url_input)
        self.url_input.setPlaceholderText("http://127.0.0.1:9981")
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItem("HTTP JSON API", PROTOCOL_HTTP)
        self.protocol_combo.addItem("HTSP", PROTOCOL_HTSP)
        layout.addRow("Protocol:", self.protocol_combo)
        self.htsp_port_input = QSpinBox()
        self.htsp_port_input.setRange(1, 65535)
        self.htsp_port_input.setValue(9982)
        layout.addRow("HTSP port:", self.htsp_port_input)
        layout.addRow("Username:", self.username_input)
        self.username_input.setPlaceholderText("Optional")
        layout.addRow("Password:", self.password_input)
        self.password_input.setPlaceholderText("Optional")
        
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
        
        # Error icon and message
        message_layout = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(QMessageBox.standardIcon(QMessageBox.Icon.Critical))
        message_layout.addWidget(icon_label)
        
        error_text = QLabel(
            f"Failed to connect to server: {server_name}\n"
            f"Error: {error_msg}\n\n"
            "Would you like to retry the connection?"
        )
        error_text.setWordWrap(True)
        message_layout.addWidget(error_text)
        layout.addLayout(message_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        retry_btn = QPushButton("Retry")
        abort_btn = QPushButton("Abort")
        
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
        
        # Create tab widget
        self.tabs = QTabWidget()
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
        self.subscriptions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
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
        self.signal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.signal_table, "Signal Status")
        
        # Server info tab
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.tabs.addTab(self.info_text, "Server Info")
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
    def update_status(self):
        try:
            # 1. Update Server Info Tab
            protocol = self.server.get('protocol', PROTOCOL_HTTP)
            server_info = f"Server Information:\n\n"
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
        """Helper method to color code signal and SNR values"""
        if value is not None and scale > 0:
            if scale == 1:
                quality = (value * 100 / 65535)
            else:  # scale == 2
                if type == 'signal':
                    quality = min(100, max(0, (value / 1000 + 15) * 6.67))
                else:  # SNR
                    quality = min(100, max(0, (value / 1000 - 10) * 10))
            
            if quality >= 80:
                item.setBackground(Qt.GlobalColor.green)
            elif quality >= 60:
                item.setBackground(Qt.GlobalColor.yellow)
            elif quality >= 40:
                item.setBackground(Qt.GlobalColor.darkYellow)
            else:
                item.setBackground(Qt.GlobalColor.red)
    
    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)

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
        geometry = self.config.get('window_geometry', {'x': 100, 'y': 100, 'width': 1200, 'height': 700})
        self.setGeometry(
            geometry['x'],
            geometry['y'],
            geometry['width'],
            geometry['height']
        )
        
        # Initialize servers from config
        self.servers = self.config_store.servers
        self._backend = None
        self._backend_key = None
        self.local_recorder = LocalRecorder()
        print(f"Debug: Loaded {len(self.servers)} servers")
        
        # Initialize channels list
        self.channels = []
        
        self.is_fullscreen = False
        self._pre_fullscreen_state = None
        self._playback_active = False
        self._video_menu = None

        
        # Add recording indicator variables
        self.recording_indicator_timer = None
        self.recording_indicator_visible = False
        self.is_recording = False
        self.recording_animation = None
        self.opacity_effect = None
        
        # Initialize VLC with basic instance first
        print("Debug: Initializing VLC instance")
        try:
            if getattr(sys, 'frozen', False):
                # If running as compiled executable
                base_path = sys._MEIPASS
                plugin_path = os.path.join(base_path, 'vlc', 'plugins')
                
                # Set VLC plugin path via environment variable
                os.environ['VLC_PLUGIN_PATH'] = plugin_path
                
                # On Linux, might also need these
                if sys.platform.startswith('linux'):
                    os.environ['LD_LIBRARY_PATH'] = base_path
                    
                print(f"Debug: VLC plugin path set to: {plugin_path}")
                
            # Initialize VLC with hardware acceleration parameters
            vlc_args = [
                # Enable hardware decoding
                '--avcodec-hw=any',  # Try any hardware acceleration method
                '--file-caching=1000',  # Increase file caching for smoother playback
                '--network-caching=1000',  # Increase network caching for streaming
                '--no-video-title-show',  # Don't show the video title
                '--no-snapshot-preview',  # Don't show snapshot previews
            ]
            
            self.instance = vlc.Instance(vlc_args)
            if not self.instance:
                raise RuntimeError("VLC Instance creation returned None")
                
            print("Debug: VLC instance created successfully with hardware acceleration")
            
            self.media_player = self.instance.media_player_new()
            if not self.media_player:
                raise RuntimeError("VLC media player creation returned None")
                
            print("Debug: VLC media player created successfully")
            
        except Exception as e:
            print(f"Error initializing VLC: {str(e)}")
            raise RuntimeError(f"Failed to initialize VLC: {str(e)}")
        
        # Then setup UI
        self.setup_ui()
        self._bind_playback_splash()
        
        # Update to use config for last server
        self.server_combo.setCurrentIndex(self.config.get('last_server', 0))
        
        # Now configure hardware acceleration after UI is set up
        try:
            # Set player window - with proper type conversion
            if sys.platform.startswith('linux'):
                handle = self.video_frame.winId().__int__()
                if handle is not None:
                    self.media_player.set_xwindow(handle)
            elif sys.platform == "win32":
                self.media_player.set_hwnd(self.video_frame.winId().__int__())
            elif sys.platform == "darwin":
                self.media_player.set_nsobject(self.video_frame.winId().__int__())
            
            # Set hardware decoding to automatic
            if hasattr(self.media_player, 'set_hardware_decoding'):
                self.media_player.set_hardware_decoding(True)
            # Always let Qt receive clicks and keys on the video surface
            self._release_vlc_input()
            
            # Add a timer to check which hardware acceleration method is being used
            # This will check after playback starts
            self.hw_check_timer = QTimer()
            self.hw_check_timer.setSingleShot(True)
            self.hw_check_timer.timeout.connect(self.check_hardware_acceleration)
            self.hw_check_timer.start(5000)  # Check after 5 seconds of playback
                
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
        

        
        # Create menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        view_menu = menubar.addMenu("View")
        help_menu = menubar.addMenu("Help")

        # Add User Guide action to Help menu
        user_guide_action = QAction("User Guide", self)
        user_guide_action.triggered.connect(self.show_user_guide)
        help_menu.addAction(user_guide_action)
        
        # Add About action to Help menu
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        
        
        # Add Fullscreen action to View menu
        self.fullscreen_action = QAction("Fullscreen", self)
        self.fullscreen_action.setShortcut("F")
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(self.fullscreen_action)

        # Add Settings action to View menu
        #settings_action = QAction("Settings", self)
        ##view_menu.addAction(settings_action)
        
        # Create actions
        exit_action = QAction("Exit", self)
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
        left_layout = QVBoxLayout(self.left_pane)
        
        # Server selection with add/remove buttons
        server_layout = QHBoxLayout()
        self.server_combo = QComboBox()
        self.server_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for server in self.servers:
            self.server_combo.addItem(server['name'])
        
        # Connect server combo box change signal
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        
        manage_servers_btn = QToolButton()
        manage_servers_btn.clicked.connect(self.manage_servers)
        
        server_layout.addWidget(QLabel("Server:"))
        server_layout.addWidget(self.server_combo)
        manage_servers_btn.setText("⚙️")  # Unicode settings icon
        manage_servers_btn.setStyleSheet("font-size: 18px;")  # Make icon bigger
        manage_servers_btn.setToolTip("Manage servers")
        server_layout.addWidget(manage_servers_btn)
        left_layout.addLayout(server_layout)
        
    

        # Channel list
        self.channel_list = QTableWidget()
        self.channel_list.setColumnCount(2)
        self.channel_list.setHorizontalHeaderLabels(['', 'Channel Name'])
        self.channel_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.channel_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
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
        
        left_layout.addWidget(QLabel(""))
        left_layout.addWidget(self.channel_list)
        
        # Right pane
        self.right_pane = QFrame()
        self.right_pane.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Raised)
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
        self.video_frame.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
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
        playback_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        playback_frame.setWindowTitle("Playback")
        playback_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        playback_frame.setLineWidth(5)  # Make frame thicker
        playback_layout = QHBoxLayout(playback_frame)
        
        # Play button
        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setIcon(QIcon(f"{self.icons_dir}/play.svg"))
        self.play_btn.setIconSize(QSize(48, 48))
        self.play_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.play_btn.clicked.connect(lambda: self.play_channel_by_data(self.selected_channel()))
        self.play_btn.setToolTip("Play selected channel")
        playback_layout.addWidget(self.play_btn)
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setFixedSize(48, 48)
        self.stop_btn.setIcon(QIcon(f"{self.icons_dir}/stop.svg"))
        self.stop_btn.setIconSize(QSize(48, 48))
        self.stop_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_btn.clicked.connect(self.stop_playback)
        self.stop_btn.setToolTip("Stop playback")
        playback_layout.addWidget(self.stop_btn)
        
        controls_layout.addWidget(playback_frame)
        
        # Create frame for record buttons
        record_frame = QFrame()
        record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        record_frame.setWindowTitle("Recording")
        record_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        record_frame.setLineWidth(5)  # Make frame thicker
        record_layout = QHBoxLayout(record_frame)
        
        # Start Record button
        self.start_record_btn = QPushButton()
        self.start_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.start_record_btn.setIcon(QIcon(f"{self.icons_dir}/record.svg"))
        self.start_record_btn.setIconSize(QSize(48, 48))
        self.start_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_record_btn.setToolTip("Start Recording")
        self.start_record_btn.clicked.connect(self.start_recording)
        record_layout.addWidget(self.start_record_btn)

        # Stop Record button 
        self.stop_record_btn = QPushButton()
        self.stop_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.stop_record_btn.setIcon(QIcon(f"{self.icons_dir}/stoprec.svg"))
        self.stop_record_btn.setIconSize(QSize(48, 48))
        self.stop_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_record_btn.setToolTip("Stop Recording")
        self.stop_record_btn.clicked.connect(self.stop_recording)
        record_layout.addWidget(self.stop_record_btn)
        
        controls_layout.addWidget(record_frame)
        
        # Create frame for local record buttons
        local_record_frame = QFrame()
        local_record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        local_record_frame.setWindowTitle("Local Recording")
        local_record_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        local_record_layout = QHBoxLayout(local_record_frame)

        # Start Local Record button
        self.start_local_record_btn = QPushButton()
        self.start_local_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.start_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/reclocal.svg"))
        self.start_local_record_btn.setIconSize(QSize(48, 48))
        self.start_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_local_record_btn.setToolTip("Start Local Recording")
        self.start_local_record_btn.clicked.connect(
            lambda: self.start_local_recording(self.selected_channel())
        )
        local_record_layout.addWidget(self.start_local_record_btn)

        # Stop Local Record button
        self.stop_local_record_btn = QPushButton()
        self.stop_local_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.stop_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/stopreclocal.svg"))
        self.stop_local_record_btn.setIconSize(QSize(48, 48))
        self.stop_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_local_record_btn.setToolTip("Stop Local Recording")
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
        self.mute_btn.setToolTip("Toggle Mute")
        self.mute_btn.setStyleSheet("QPushButton { border: none; }")

        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(150)  # Set fixed width to make slider less wide
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        
        # Fullscreen button with icon
        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setIcon(QIcon(f"{self.icons_dir}/fullscreen.svg"))
        self.fullscreen_btn.setIconSize(QSize(32, 32))
        self.fullscreen_btn.setFixedSize(32, 32)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_btn.setToolTip("Toggle Fullscreen")
        self.fullscreen_btn.setStyleSheet("QPushButton { border: none; }")
        
        controls_layout.addStretch()  # Add stretch to push widgets to the right
        controls_layout.addWidget(self.mute_btn)
        controls_layout.addWidget(self.volume_slider)
        controls_layout.addWidget(self.fullscreen_btn)
        self.right_layout.addWidget(self.controls_bar)
        
        # Add panes to splitter instead of layout
        self.splitter.addWidget(self.left_pane)
        self.splitter.addWidget(self.right_pane)
        
        # Set initial sizes (optional)
        self.splitter.setSizes([300, 900])  # Adjust these numbers based on your preference
        
        # Add splitter to main layout
        layout.addWidget(self.splitter)
        self.main_layout = layout
        
        
        # Buttons removed
        
        # Status bar setup
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        # Create a container widget for status bar items
        status_container = QWidget()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(10)  # Space between indicator and text
        
        # Create recording indicator
        self.recording_indicator = QLabel()
        self.recording_indicator.setFixedSize(16, 16)
        self.recording_indicator.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 0, 0, 0.8);
                min-width: 16px;
                max-width: 16px;
                min-height: 16px;
                max-height: 16px;
                border-radius: 8px;
                margin: 2px;
            }
            QLabel[recording="false"] {
                background-color: transparent;
            }
        """)
        self.recording_indicator.setProperty("recording", False)
        
        # Create status message label
        self.status_label = QLabel("Ready")
        
        # Add widgets to horizontal layout
        status_layout.addWidget(self.recording_indicator)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()  # This pushes everything to the left
        
        # Add the container to the status bar
        self.statusbar.addWidget(status_container)
        
        # Override showMessage to update our custom label
        def custom_show_message(message, timeout=0):
            self.status_label.setText(message)
        self.statusbar.showMessage = custom_show_message
        
        # Initialize
        self.fetch_channels()
        
        # Connect channel list double click to play
        
        # Add event filter to video frame for double-click
        self.video_frame.installEventFilter(self)
        
        # Add Server Status to View menu
        server_status_action = view_menu.addAction("Server Status")
        server_status_action.triggered.connect(self.show_server_status)
        
        # Add DVR Status to View menu
        dvr_status_action = view_menu.addAction("DVR Status")
        dvr_status_action.triggered.connect(self.show_dvr_status)
        
        # Add search box before styling it
        search_layout = QHBoxLayout()
        search_icon = QLabel("🔍")  # Unicode search icon
        self.search_box = QLineEdit()
        
        # Style placeholder text
        placeholder_color = QColor(100, 100, 100)  # Dark gray color
        search_palette = self.search_box.palette()
        search_palette.setColor(QPalette.ColorRole.PlaceholderText, placeholder_color)
        self.search_box.setPalette(search_palette)
        
        self.search_box.setPlaceholderText("Press S to search channels...")
        self.search_box.textChanged.connect(self.filter_channels)
        self.search_box.setClearButtonEnabled(True)  # Add clear button inside search box
        
        # Add Ctrl+F shortcut for search box
        search_shortcut = QShortcut(QKeySequence(Qt.Key.Key_S), self)
        search_shortcut.activated.connect(self.search_box.setFocus)
        
        # Create custom clear button action
        clear_action = QAction("⌫", self.search_box)
        self.search_box.addAction(clear_action, QLineEdit.ActionPosition.TrailingPosition)
        
        search_layout.addWidget(search_icon)
        search_layout.addWidget(self.search_box)
        left_layout.addLayout(search_layout)  # Add to left pane layout
        
        # Now style the search box with custom clear button styling
        
        
        # Add margins to search layout
        search_layout.setContentsMargins(0, 5, 0, 5)
        search_layout.setSpacing(5)

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

    def get_backend(self):
        server = self.current_server()
        if not server:
            raise TvhError('No server selected')
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
        
    def fetch_channels(self):
        """Fetch channel list from current TVHeadend server"""
        server = None
        try:
            if not self.servers:
                print("Debug: No servers configured")
                self.statusbar.showMessage("No servers configured")
                return
                
            server = self.current_server()
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
                self.channel_list.setItem(row, 0, number_item)
                name_item = QTableWidgetItem(channel.name)
                name_item.setData(Qt.ItemDataRole.UserRole, channel.to_raw())
                self.channel_list.setItem(row, 1, name_item)
            self.channel_list.setSortingEnabled(True)
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
                title='Instant Recording',
                description='Recorded via TVHplayer',
                comment='Instant recording via TVHplayer',
            )
            duration_minutes = duration // 60
            self.statusbar.showMessage(
                f"Recording started for: {channel.name} ({duration_minutes} minutes)"
            )
            self.start_recording_indicator()
        except Exception as e:
            print(f"Debug: Recording error: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Recording error: {str(e)}")
            
    def stop_playback(self):
        """Stop current playback"""
        print("Debug: Stopping playback")
        self._playback_active = False
        self._playback_channel = None
        self.media_player.stop()
        self._protect_video_surface(False)
        self.statusbar.showMessage("Playback stopped")

    def _set_idle_splash(self, visible):
        """Show the logo overlay only when VLC is not drawing video."""
        if not hasattr(self, 'idle_splash'):
            return
        if visible:
            self.idle_splash.setGeometry(self.player_container.rect())
            self.idle_splash.show()
            self.idle_splash.raise_()
        else:
            self.idle_splash.hide()

    def _protect_video_surface(self, playing):
        """While a channel is on, do not let Qt paint or flash the splash."""
        self._playback_active = playing
        if hasattr(self, '_splash_idle_timer'):
            self._splash_idle_timer.stop()
        self._set_idle_splash(not playing)
        if hasattr(self, 'video_frame'):
            self.video_frame.setUpdatesEnabled(not playing)

    def _on_vlc_playing(self):
        self._protect_video_surface(True)

    def _on_vlc_stopped(self):
        # A menu or resize can make VLC tear down its output for a moment.
        # Do not treat that as a real stop or the splash will flash.
        if self._playback_active:
            return
        if not hasattr(self, '_splash_idle_timer'):
            return
        self._splash_idle_timer.start(400)

    def _show_splash_if_idle(self):
        if self._playback_active:
            return
        if self.media_player and self.media_player.is_playing():
            return
        self._protect_video_surface(False)

    def _bind_playback_splash(self):
        """Keep the splash in sync if VLC starts or stops on its own."""
        self._splash_idle_timer = QTimer(self)
        self._splash_idle_timer.setSingleShot(True)
        self._splash_idle_timer.timeout.connect(self._show_splash_if_idle)
        try:
            manager = self.media_player.event_manager()
            manager.event_attach(
                vlc.EventType.MediaPlayerPlaying,
                lambda event: QTimer.singleShot(0, self._on_vlc_playing),
            )
            manager.event_attach(
                vlc.EventType.MediaPlayerStopped,
                lambda event: QTimer.singleShot(0, self._on_vlc_stopped),
            )
            manager.event_attach(
                vlc.EventType.MediaPlayerEndReached,
                lambda event: QTimer.singleShot(0, self._on_vlc_stopped),
            )
        except Exception as e:
            print(f"Debug: Could not attach VLC splash events: {e}")

    def _release_vlc_input(self):
        """Stop VLC from eating mouse and keyboard so Qt can handle them."""
        try:
            self.media_player.video_set_key_input(False)
            self.media_player.video_set_mouse_input(False)
        except Exception as e:
            print(f"Debug: Could not disable VLC input grabbing: {e}")

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

    def _splitter_handle(self):
        if self.splitter.count() > 1:
            return self.splitter.handle(1)
        return None

    def _enter_fullscreen(self):
        handle = self._splitter_handle()
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
            'splitter_handle_visible': handle.isVisible() if handle else False,
        }
        self.setUpdatesEnabled(False)
        try:
            self.menuBar().hide()
            self.statusbar.hide()
            self.left_pane.hide()
            self.controls_bar.hide()
            self.right_pane.setFrameStyle(QFrame.Shape.NoFrame)
            self.right_pane.setLineWidth(0)
            self.splitter.setFrameStyle(QFrame.Shape.NoFrame)
            self.splitter.setHandleWidth(0)
            if handle:
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
            handle = self._splitter_handle()
            if handle and state.get('splitter_handle_visible', True):
                handle.show()
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
            self.fullscreen_btn.setToolTip('Exit Fullscreen' if self.is_fullscreen else 'Toggle Fullscreen')

    def _video_context_menu(self):
        """Build the right-click menu for the video surface."""
        menu = QMenu(self)
        channel = self.selected_channel()
        playing = bool(self.media_player and self.media_player.is_playing())
        muted = bool(self.media_player and self.media_player.audio_get_mute())

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
            self.servers = dialog.servers
            self.config_store.servers = self.servers
            print(f"Debug: Updated servers list, now has {len(self.servers)} servers")
            self.save_config()
            self.close_backend()
            
            # Update server combo
            self.server_combo.clear()
            for server in self.servers:
                print(f"Debug: Adding server to combo: {server['name']}")
                self.server_combo.addItem(server['name'])
            
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
            self.fetch_channels()

    def on_volume_changed(self, value):
        print(f"Debug: Volume changed to {value}")
        self.media_player.audio_set_volume(value)

    def eventFilter(self, obj, event):
        """Keep the video surface stable and handle player gestures."""
        if (
            hasattr(self, 'player_container')
            and obj is self.player_container
            and event.type() == QEvent.Type.Resize
        ):
            if hasattr(self, 'idle_splash') and self.idle_splash.isVisible():
                self.idle_splash.setGeometry(self.player_container.rect())
            return False
        if obj is self.video_frame:
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
        super().keyPressEvent(event)

    def toggle_mute(self):
        """Toggle audio mute state"""
        print("Debug: Toggling mute")
        is_muted = self.media_player.audio_get_mute()
        self.media_player.audio_set_mute(not is_muted)
        
        if not is_muted:  # Switching to muted
            self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/mute.svg"))
            self.mute_btn.setToolTip("Unmute")
            print("Debug: Audio muted")
        else:  # Switching to unmuted
            self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/unmute.svg"))
            self.mute_btn.setToolTip("Mute")
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
                    self.stop_recording_indicator()
                return
            for entry in targets:
                print(f"Debug: Stopping recording: {entry.title} ({entry.uuid}) on {entry.channel_name}")
                backend.stop_dvr_entry(entry)
            if len(targets) >= len(running):
                self.stop_recording_indicator()
            channel_name = targets[0].channel_name or (channel.name if channel else 'channel')
            if len(targets) == 1:
                self.statusbar.showMessage(f"Stopped recording for {channel_name}")
            else:
                self.statusbar.showMessage(f"Stopped {len(targets)} recordings for {channel_name}")
        except Exception as e:
            print(f"Debug: Error stopping recordings: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Error stopping recordings: {str(e)}")
            if len(running) <= 1:
                self.stop_recording_indicator()

    def start_recording_indicator(self):
        """Start the recording indicator with smooth pulsing animation"""
        print("Debug: Starting recording indicator")
        self.is_recording = True
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
            media = self.instance.media_new(url)
            self.media_player.set_media(media)
            self.media_player.play()
        except Exception as e:
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
            self.recording_monitor = QTimer()
            self.recording_monitor.timeout.connect(self.check_recording_status)
            self.recording_monitor.start(2000)
            self.statusbar.showMessage(f"Local recording started: {file_path}")
            self.start_recording_indicator()
            self.recording_status_dialog = RecordingStatusDialog(channel_name, file_path, self)
            self.recording_status_dialog.finished.connect(self.stop_local_recording)
            self.recording_status_dialog.show()
            
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
                    if hasattr(self, 'recording_status_dialog'):
                        self.recording_status_dialog.close()
                    QMessageBox.warning(self, "Local Recording Status", "Recording file does not exist")
                return
            if hasattr(self, 'recording_status_dialog'):
                self.recording_status_dialog.update_status(status.size, status.stalled)
            if status.return_code is not None:
                if status.size == 0 or status.return_code != 0:
                    self.stop_local_recording()
                    QMessageBox.critical(self, "Recording Error", "Recording failed - check console for errors")
                return
            if status.stalled:
                channel = getattr(self, '_recording_channel', None)
                QMessageBox.warning(self, "Recording Status", "Recording stalled - attempting restart")
                self.stop_local_recording()
                self.start_local_recording(channel or self.selected_channel())
        except Exception as e:
            print(f"Debug: Error checking recording status: {str(e)}")
            QMessageBox.critical(self, "Recording Error", str(e))

    def stop_local_recording(self):
        """Stop local recording"""
        try:
            if hasattr(self, 'recording_status_dialog'):
                self.recording_status_dialog.close()
                delattr(self, 'recording_status_dialog')
            if hasattr(self, 'recording_monitor') and self.recording_monitor is not None:
                self.recording_monitor.stop()
                self.recording_monitor = None
            self.local_recorder.stop()
            self.statusbar.showMessage("Local recording stopped")
            self.stop_recording_indicator()
        except Exception as e:
            print(f"Debug: Error stopping local recording: {str(e)}")
            self.statusbar.showMessage(f"Error stopping local recording: {str(e)}")
            self.stop_recording_indicator()

    def closeEvent(self, event):
        """Save configuration when closing the application"""
        self.save_config()
        self.local_recorder.stop()
        self.close_backend()
        super().closeEvent(event)

    def show_channel_context_menu(self, position):
        """Show context menu for channel list items"""
        menu = QMenu()
        
        # Get the item at the position
        row = self.channel_list.rowAt(position.y())
        if row >= 0:
            channel_item = self.channel_list.item(row, 1)  # Get name column item
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
            if isinstance(channel_data, Channel):
                channel = channel_data
            else:
                channel = Channel.from_raw(channel_data)
            self._playback_channel = channel
            stream_url = self.get_backend().stream_url(channel)
            print(f"Debug: Stream URL: {stream_url}")
            media = self.instance.media_new(stream_url)
            self.media_player.set_media(media)
            self.media_player.play()
            self._release_vlc_input()
            self._protect_video_surface(True)
            self.statusbar.showMessage(f"Playing: {channel.name}")
        except Exception as e:
            print(f"Debug: Error in play_channel: {str(e)}")
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
            if item:
                channel_name = item.text().lower()
                self.channel_list.setRowHidden(row, search_text not in channel_name)

    def check_hardware_acceleration(self):
        """Check and print which hardware acceleration method is being used"""
        if not self.media_player:
            return
            
        # This only works if a media is playing
        if not self.media_player.is_playing():
            return
            
        try:
            # Get media statistics - handle different VLC Python binding versions
            media = self.media_player.get_media()
            if not media:
                print("No media currently playing")
                return
                
            # Different versions of python-vlc have different APIs for get_stats
            try:
                # Newer versions (direct call)
                stats = media.get_stats()
                print("VLC Playback Statistics:")
                print(f"Decoded video blocks: {stats.decoded_video}")
                print(f"Displayed pictures: {stats.displayed_pictures}")
                print(f"Lost pictures: {stats.lost_pictures}")
            except TypeError:
                # Older versions (requiring a stats object parameter)
                stats = vlc.MediaStats()
                media.get_stats(stats)
                print("VLC Playback Statistics:")
                print(f"Decoded video blocks: {stats.decoded_video}")
                print(f"Displayed pictures: {stats.displayed_pictures}")
                print(f"Lost pictures: {stats.lost_pictures}")
            
            # Check if hardware decoding is enabled
            if hasattr(self.media_player, 'get_role'):
                print(f"Media player role: {self.media_player.get_role()}")
            
            # Try to get more detailed hardware acceleration info
            print("Hardware acceleration is active if you see 'Using ... for hardware decoding' in the logs above")
            print("For more details, run VLC with the same content and use:")
            print("Tools -> Messages -> Info to see which decoder is being used")
            
        except Exception as e:
            print(f"Error checking hardware acceleration: {e}")
            print(f"Traceback: {traceback.format_exc()}")



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
        
        # Create list widget for EPG entries
        self.epg_list = QListWidget()
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
            info_label = QLabel(f"{start_time} - {stop_time}: {title}")
            info_label.setToolTip(description)
            item_layout.addWidget(info_label, stretch=1)
            record_btn = QPushButton("⏺")
            record_btn.setFixedWidth(32)
            record_btn.setFixedHeight(32)
            record_btn.setStyleSheet("""
                QPushButton {
                    color: red;
                    font-size: 16px;
                    border: 1px solid #ccc;
                    border-radius: 16px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #f0f0f0;
                }
                QPushButton:pressed {
                    background-color: #e0e0e0;
                }
            """)
            record_btn.setToolTip("Schedule Recording")
            record_btn.clicked.connect(lambda checked, e=entry: self.schedule_recording(e))
            item_layout.addWidget(record_btn)
            list_item = QListWidgetItem(self.epg_list)
            list_item.setSizeHint(item_widget.sizeHint())
            self.epg_list.addItem(list_item)
            self.epg_list.setItemWidget(list_item, item_widget)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
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
        except Exception as e:
            print(f"Debug: Error scheduling recording: {str(e)}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to schedule recording: {str(e)}"
            )

class RecordingStatusDialog(QDialog):
    def __init__(self, channel_name, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recording Status")
        self.setModal(False)  # Allow interaction with main window
        self.resize(400, 200)
        self.setup_ui(channel_name, file_path)
        
    def setup_ui(self, channel_name, file_path):
        layout = QVBoxLayout(self)
        
        # Channel name
        channel_label = QLabel(f"Recording: {channel_name}")
        channel_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(channel_label)
        
        # File path
        path_label = QLabel(f"Saving to: {file_path}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        
        # Duration
        self.duration_label = QLabel("Duration: 00:00:00")
        layout.addWidget(self.duration_label)
        
        # File size
        self.size_label = QLabel("File size: 0 MB")
        layout.addWidget(self.size_label)
        
        # Status message
        self.status_label = QLabel("Status: Recording")
        self.status_label.setStyleSheet("color: green;")
        layout.addWidget(self.status_label)
        
        # Stop button
        stop_btn = QPushButton("Stop Recording")
        stop_btn.clicked.connect(self.stop_requested)
        layout.addWidget(stop_btn)
        
        # Start time for duration calculation
        self.start_time = time.time()
        
    def update_status(self, file_size, is_stalled=False):
        """Update the dialog with current recording status"""
        # Update duration
        duration = int(time.time() - self.start_time)
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        self.duration_label.setText(f"Duration: {hours:02d}:{minutes:02d}:{seconds:02d}")
        
        # Update file size
        size_mb = file_size / (1024 * 1024)  # Convert to MB
        self.size_label.setText(f"File size: {size_mb:.2f} MB")
        
        # Update status message
        if is_stalled:
            self.status_label.setText("Status: Stalled - Attempting recovery")
            self.status_label.setStyleSheet("color: orange;")
        else:
            self.status_label.setText("Status: Recording")
            self.status_label.setStyleSheet("color: green;")
    
    def stop_requested(self):
        """Signal that user wants to stop recording"""
        self.accept()

def main():
    """Main entry point for the application"""
    try:
        # VLC's window embedding is still more reliable on X11 than on Wayland.
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        app = QApplication(sys.argv)
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
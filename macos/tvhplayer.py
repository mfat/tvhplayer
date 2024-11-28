from datetime import datetime, timedelta
import sys
from tkinter.filedialog import FileDialog
import vlc
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QToolBar, QComboBox, QAction, QSplitter, QFrame,
    QListWidget, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox, QApplication,
    QPushButton, QLabel, QSlider, QStatusBar, QGridLayout, QMenuBar, QRadioButton, QSpinBox, QGraphicsOpacityEffect, QFileDialog,
    QMenu, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QSizePolicy, QToolButton, QShortcut, QCheckBox, QGroupBox  # Added QGroupBox here
)
from PyQt5.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, QAbstractAnimation, QRect, QCoreApplication
from PyQt5.QtGui import QIcon, QPainter, QColor, QKeySequence
import json
import requests
import resources_rc
import time
import subprocess
import os
import traceback
from pathlib import Path
import logging




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
            import PyQt5
            self.logger.info(f"PyQt5 version: {PyQt5.QtCore.QT_VERSION_STR}")
        except ImportError:
            self.logger.error("PyQt5 not found")
        
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
    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server
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
        self.upcoming_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabs.addTab(self.upcoming_table, "Upcoming/Current")  # Changed tab title
        
        # Finished recordings tab
        self.finished_table = QTableWidget()
        self.finished_table.setColumnCount(4)
        self.finished_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Duration'])
        self.finished_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabs.addTab(self.finished_table, "Finished")
        
        # Failed recordings tab
        self.failed_table = QTableWidget()
        self.failed_table.setColumnCount(4)
        self.failed_table.setHorizontalHeaderLabels(['Channel', 'Title', 'Start Time', 'Error'])
        self.failed_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabs.addTab(self.failed_table, "Failed")
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
    def update_status(self):
        try:
            # Create auth if needed
            auth = None
            if self.server.get('username') or self.server.get('password'):
                auth = (self.server.get('username', ''), self.server.get('password', ''))
            
            # Get DVR entries
            api_url = f'{self.server["url"]}/api/dvr/entry/grid'
            response = requests.get(api_url, auth=auth)
            
            if response.status_code == 200:
                data = response.json()
                entries = data.get('entries', [])
                print(f"Debug: Found {len(entries)} DVR entries")
                
                # Sort entries by status
                upcoming = []
                finished = []
                failed = []
                
                for entry in entries:
                    status = entry.get('status', '')  # Don't convert to lowercase yet
                    sched_status = entry.get('sched_status', '').lower()
                    errors = entry.get('errors', 0)
                    error_code = entry.get('errorcode', 0)
                    
                    print(f"\nDebug: Processing entry: {entry.get('disp_title', 'Unknown')}")
                    print(f"  Status: {status}")
                    print(f"  Sched Status: {sched_status}")
                    
                    # Check status (case-sensitive for "Running")
                    if status == "Running":
                        print(f"Debug: Found active recording: {entry.get('disp_title', 'Unknown')}")
                        upcoming.append((entry.get('channelname', 'Unknown'), entry.get('disp_title', 'Unknown'), datetime.fromtimestamp(entry.get('start', 0)), timedelta(seconds=entry.get('duration', 0)), True))
                    elif 'scheduled' in status.lower() or sched_status == 'scheduled':
                        upcoming.append((entry.get('channelname', 'Unknown'), entry.get('disp_title', 'Unknown'), datetime.fromtimestamp(entry.get('start', 0)), timedelta(seconds=entry.get('duration', 0)), False))
                    elif 'completed' in status.lower() or status.lower() == 'finished':
                        finished.append((entry.get('channelname', 'Unknown'), entry.get('disp_title', 'Unknown'), datetime.fromtimestamp(entry.get('start', 0)), timedelta(seconds=entry.get('duration', 0))))
                    elif ('failed' in status.lower() or 'invalid' in status.lower() or 
                          'error' in status.lower() or errors > 0 or error_code != 0):
                        error_msg = entry.get('error', '')
                        if not error_msg and errors > 0:
                            error_msg = f"Recording failed with {errors} errors"
                        if not error_msg and error_code != 0:
                            error_msg = f"Error code: {error_code}"
                        if not error_msg:
                            error_msg = "Unknown error"
                        failed.append((entry.get('channelname', 'Unknown'), entry.get('disp_title', 'Unknown'), datetime.fromtimestamp(entry.get('start', 0)), error_msg))
                        print(f"Debug: Added to failed: {entry.get('disp_title', 'Unknown')} (Error: {error_msg})")
                    else:
                        print(f"Debug: Unhandled status: {status} for entry: {entry.get('disp_title', 'Unknown')}")
                
                print(f"\nDebug: Sorted entries - Upcoming: {len(upcoming)}, "
                      f"Finished: {len(finished)}, Failed: {len(failed)}")
                
                # Sort upcoming recordings by start time
                upcoming.sort(key=lambda x: x[2])  # Sort by start_time
                
                # Update tables
                self.upcoming_table.setRowCount(len(upcoming))
                for i, (channel, title, start, duration, is_recording) in enumerate(upcoming):
                    self.upcoming_table.setItem(i, 0, QTableWidgetItem(channel))
                    self.upcoming_table.setItem(i, 1, QTableWidgetItem(title))
                    self.upcoming_table.setItem(i, 2, QTableWidgetItem(start.strftime('%Y-%m-%d %H:%M')))
                    self.upcoming_table.setItem(i, 3, QTableWidgetItem(str(duration)))
                    
                    # Add status column
                    status = "Recording" if is_recording else entry.get('sched_status', 'scheduled').capitalize()
                    self.upcoming_table.setItem(i, 4, QTableWidgetItem(status))
                    
                    # Highlight currently recording entries
                    if is_recording:
                        for col in range(5):  # Update range to include new column
                            self.upcoming_table.item(i, col).setBackground(Qt.green)
                
                # Sort finished recordings by start time (most recent first)
                finished.sort(key=lambda x: x[2], reverse=True)
                
                self.finished_table.setRowCount(len(finished))
                for i, (channel, title, start, duration) in enumerate(finished):
                    self.finished_table.setItem(i, 0, QTableWidgetItem(channel))
                    self.finished_table.setItem(i, 1, QTableWidgetItem(title))
                    self.finished_table.setItem(i, 2, QTableWidgetItem(start.strftime('%Y-%m-%d %H:%M')))
                    self.finished_table.setItem(i, 3, QTableWidgetItem(str(duration)))
                
                # Sort failed recordings by start time (most recent first)
                failed.sort(key=lambda x: x[2], reverse=True)
                
                self.failed_table.setRowCount(len(failed))
                for i, (channel, title, start, error) in enumerate(failed):
                    self.failed_table.setItem(i, 0, QTableWidgetItem(channel))
                    self.failed_table.setItem(i, 1, QTableWidgetItem(title))
                    self.failed_table.setItem(i, 2, QTableWidgetItem(start.strftime('%Y-%m-%d %H:%M')))
                    self.failed_table.setItem(i, 3, QTableWidgetItem(error))
                    # Highlight failed entries in red
                    for col in range(4):
                        self.failed_table.item(i, col).setBackground(Qt.red)
                
            else:
                print(f"Debug: Failed to fetch DVR entries. Status code: {response.status_code}")
                
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
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
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
        if dialog.exec_() == QDialog.Accepted:
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
            if dialog.exec_() == QDialog.Accepted:
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
        self.password_input.setEchoMode(QLineEdit.Password)
        
        layout.addRow("Name:", self.name_input)
        self.name_input.setPlaceholderText("My Server")
        layout.addRow("Server address:", self.url_input)
        self.url_input.setPlaceholderText("http://127.0.0.1:9981")
        layout.addRow("Username:", self.username_input)
        layout.addRow("Password:", self.password_input)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_server_config(self):
        return {
            'name': self.name_input.text(),
            'url': self.url_input.text(),
            'username': self.username_input.text(),
            'password': self.password_input.text()
        }
        
    def set_server_config(self, config):
        self.name_input.setText(config.get('name', ''))
        self.url_input.setText(config.get('url', ''))
        self.username_input.setText(config.get('username', ''))
        self.password_input.setText(config.get('password', ''))

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
        icon_label.setPixmap(QMessageBox.standardIcon(QMessageBox.Critical))
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
    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server
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
        self.subscriptions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
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
        self.signal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
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
            auth = None
            if self.server.get('username') or self.server.get('password'):
                auth = (self.server.get('username', ''), self.server.get('password', ''))

            # 1. Update Server Info Tab
            server_info = f"Server Information:\n\n"
            server_info += f"Name: {self.server.get('name', 'Unknown')}\n"
            server_info += f"URL: {self.server.get('url', 'Unknown')}\n"
            
            # Get server version and capabilities
            version_url = f"{self.server['url']}/api/serverinfo"
            try:
                version_response = requests.get(version_url, auth=auth)
                if version_response.status_code == 200:
                    server_data = version_response.json()
                    server_info += f"\nServer Version: {server_data.get('sw_version', 'Unknown')}\n"
                    server_info += f"API Version: {server_data.get('api_version', 'Unknown')}\n"
                    server_info += f"Server Name: {server_data.get('server_name', 'Unknown')}\n"
                    
                    if 'capabilities' in server_data:
                        server_info += "\nCapabilities:\n"
                        for cap in server_data['capabilities']:
                            server_info += f"- {cap}\n"
            except Exception as e:
                server_info += f"\nError fetching server info: {str(e)}\n"
            
            self.info_text.setText(server_info)

            # 2. Update Signal Status Tab
            inputs_url = f"{self.server['url']}/api/status/inputs"
            try:
                inputs_response = requests.get(inputs_url, auth=auth)
                
                if inputs_response.status_code == 200:
                    inputs = inputs_response.json().get('entries', [])
                    
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
            connections_url = f"{self.server['url']}/api/status/connections"
            subscriptions_url = f"{self.server['url']}/api/status/subscriptions"
            
            try:
                # Get both connections and subscriptions
                connections_response = requests.get(connections_url, auth=auth)
                subscriptions_response = requests.get(subscriptions_url, auth=auth)
                
                if connections_response.status_code == 200 and subscriptions_response.status_code == 200:
                    connections = connections_response.json().get('entries', [])
                    subscriptions = subscriptions_response.json().get('entries', [])
                    
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
                item.setBackground(Qt.green)
            elif quality >= 60:
                item.setBackground(Qt.yellow)
            elif quality >= 40:
                item.setBackground(Qt.darkYellow)
            else:
                item.setBackground(Qt.red)
    
    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)

class TVHeadendClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setup_paths()
        self.config_file = os.path.join(str(Path.home()), '.tvhplayer.conf')
        print(f"Debug: Config file location: {self.config_file}")
        self.config = self.load_config()
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
        self.servers = self.config.get('servers', [])
        print(f"Debug: Loaded {len(self.servers)} servers")
        
        # Initialize channels list
        self.channels = []
        
        self.is_fullscreen = False
 
        
        # Add recording indicator variables
        self.recording_indicator_timer = None
        self.recording_indicator_visible = False
        self.is_recording = False
        self.recording_animation = None
        self.opacity_effect = None
        
        # Initialize VLC
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
            else:
                # If running from source, use system VLC
                if sys.platform == 'darwin':
                    # On macOS, try to use VLC.app plugins
                    plugin_path = '/Applications/VLC.app/Contents/MacOS/plugins'
                    if os.path.exists(plugin_path):
                        os.environ['VLC_PLUGIN_PATH'] = plugin_path
                        print(f"Debug: Using system VLC plugins from: {plugin_path}")
                    else:
                        print("Debug: System VLC plugins not found, using default paths")
                
            # Initialize VLC without arguments
            self.instance = vlc.Instance()
            if not self.instance:
                raise RuntimeError("VLC Instance creation returned None")
                
            print("Debug: VLC instance created successfully")
            
            self.media_player = self.instance.media_player_new()
            if not self.media_player:
                raise RuntimeError("VLC media player creation returned None")
                
            print("Debug: VLC media player created successfully")
            
        except Exception as e:
            print(f"Error initializing VLC: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            raise RuntimeError(f"Failed to initialize VLC: {str(e)}")
        
        

        # Then setup UI
        self.setup_ui()
        
        # Update to use config for last server
        self.server_combo.setCurrentIndex(self.config.get('last_server', 0))
        
        #Set player window - with proper type conversion

        if sys.platform.startswith('linux'):
            handle = self.video_frame.winId().__int__()
            if handle is not None:
                self.media_player.set_xwindow(handle)
        elif sys.platform == "win32":
           self.media_player.set_hwnd(self.video_frame.winId().__int__())
        elif sys.platform == "darwin":
           self.media_player.set_nsobject(self.video_frame.winId().__int__())
    
          
    
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
                raise RuntimeError(f"Icons directory not found in {self.app_dir} or parent directory")
        
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
        
        # Add About action to Help menu
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        # Add Fullscreen action to View menu
        fullscreen_action = QAction("Fullscreen", self)
        fullscreen_action.setShortcut("F")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

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
        splitter = QSplitter(Qt.Horizontal)
        
        # Left pane
        left_pane = QFrame()
        left_pane.setFrameStyle(QFrame.Panel | QFrame.Raised)
        #left_pane.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        left_layout = QVBoxLayout(left_pane)
        
        # Server selection with add/remove buttons
        server_layout = QHBoxLayout()
        self.server_combo = QComboBox()
        self.server_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        self.channel_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.channel_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.channel_list.verticalHeader().setVisible(False)
        self.channel_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.channel_list.setSelectionMode(QTableWidget.SingleSelection)
        self.channel_list.setSortingEnabled(True)
        self.channel_list.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # Connect double-click to play
        self.channel_list.itemDoubleClicked.connect(self.play_channel_from_table)
        
        # Connect context menu
        self.channel_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.channel_list.customContextMenuRequested.connect(self.show_channel_context_menu)
        
        left_layout.addWidget(QLabel(""))
        left_layout.addWidget(self.channel_list)
        
        # Right pane
        right_pane = QFrame()
        right_pane.setFrameStyle(QFrame.Panel | QFrame.Raised)
        #right_pane.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        right_layout = QVBoxLayout(right_pane)
        right_layout.setObjectName("right_layout")
        
        # VLC player widget
        self.video_frame = QWidget()
        self.video_frame.setStyleSheet("""
            background-color: black;
            background-image: url(icons/playerbg.svg);
            background-position: center;
            background-repeat: no-repeat;
        """)
        
        right_layout.addWidget(self.video_frame)
        
        # Player controls
        controls_layout = QHBoxLayout()
       # Create frame for play/stop buttons
        playback_frame = QFrame()
        playback_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        playback_frame.setWindowTitle("Playback")
        playback_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        playback_frame.setLineWidth(5)  # Make frame thicker
        playback_layout = QHBoxLayout(playback_frame)
        
        # Play button
        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setIcon(QIcon(f"{self.icons_dir}/play.svg"))
        self.play_btn.setIconSize(QSize(48, 48))
        self.play_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.play_btn.clicked.connect(lambda: self.play_channel_by_data(
            self.channel_list.currentItem().data(Qt.UserRole) if self.channel_list.currentItem() 
            else (self.channel_list.item(0, 1).data(Qt.UserRole) if self.channel_list.rowCount() > 0 
            and self.channel_list.selectRow(0) or True else None)))
        self.play_btn.setToolTip("Play selected channel")
        playback_layout.addWidget(self.play_btn)
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setFixedSize(48, 48)
        self.stop_btn.setIcon(QIcon(f"{self.icons_dir}/stop.svg"))
        self.stop_btn.setIconSize(QSize(48, 48))
        self.stop_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_btn.clicked.connect(self.media_player.stop)
        self.stop_btn.setToolTip("Stop playback")
        playback_layout.addWidget(self.stop_btn)
        
        controls_layout.addWidget(playback_frame)
        
        # Create frame for record buttons
        record_frame = QFrame()
        record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        record_frame.setWindowTitle("Recording")
        record_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        record_frame.setLineWidth(5)  # Make frame thicker
        record_layout = QHBoxLayout(record_frame)
        
        # Start Record button
        self.start_record_btn = QPushButton()
        self.start_record_btn.setFixedSize(48, 48)
        self.start_record_btn.setIcon(QIcon(f"{self.icons_dir}/record.svg"))
        self.start_record_btn.setIconSize(QSize(48, 48))
        self.start_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_record_btn.setToolTip("Start Recording")
        self.start_record_btn.clicked.connect(self.start_recording)
        record_layout.addWidget(self.start_record_btn)

        # Stop Record button 
        self.stop_record_btn = QPushButton()
        self.stop_record_btn.setFixedSize(48, 48)
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
        local_record_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        local_record_frame.setLineWidth(5)  # Make frame thicker
        local_record_layout = QHBoxLayout(local_record_frame)

        # Start Local Record button
        self.start_local_record_btn = QPushButton()
        self.start_local_record_btn.setFixedSize(48, 48)
        self.start_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/reclocal.svg"))
        self.start_local_record_btn.setIconSize(QSize(48, 48))
        self.start_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_local_record_btn.setToolTip("Start Local Recording")
        self.start_local_record_btn.clicked.connect(
            lambda: self.start_local_recording(
                self.channel_list.currentItem().text() if self.channel_list.currentItem() else None
            )
        )
        local_record_layout.addWidget(self.start_local_record_btn)

        # Stop Local Record button
        self.stop_local_record_btn = QPushButton()
        self.stop_local_record_btn.setFixedSize(48, 48)
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
        self.mute_btn.setFixedSize(32, 32)
        self.mute_btn.setCheckable(True)
        self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/unmute.svg"))
        self.mute_btn.setIconSize(QSize(32, 32))
        self.mute_btn.setStyleSheet("QPushButton { border: none; }")
        self.mute_btn.setToolTip("Mute")
        
        # Connect toggled signal to handle icon changes
        def on_mute_toggled(checked):
            if checked:
                self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/mute.svg"))
                self.mute_btn.setToolTip("Unmute")
            else:
                self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/unmute.svg"))
                self.mute_btn.setToolTip("Mute")     
        self.mute_btn.toggled.connect(on_mute_toggled)


        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(150)  # Set fixed width to make slider less wide
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        
        # Fullscreen button with icon
        fullscreen_btn = QPushButton()
        fullscreen_btn.setIcon(QIcon(f"{self.icons_dir}/fullscreen.svg"))
        fullscreen_btn.setIconSize(QSize(32, 32))
        fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        fullscreen_btn.setToolTip("Toggle Fullscreen")
        fullscreen_btn.setStyleSheet("QPushButton { border: none; }")
        
        controls_layout.addStretch()  # Add stretch to push widgets to the right
        controls_layout.addWidget(self.mute_btn)
        controls_layout.addWidget(self.volume_slider)
        controls_layout.addWidget(fullscreen_btn)
        right_layout.addLayout(controls_layout)
        
        # Add panes to splitter instead of layout
        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        
        # Set initial sizes (optional)
        splitter.setSizes([300, 900])  # Adjust these numbers based on your preference
        
        # Add splitter to main layout
        layout.addWidget(splitter)
        
        
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
        
        # Add key event filter to main window
        self.installEventFilter(self)
        
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
        self.search_box.setPlaceholderText("Press S to search channels...")
        self.search_box.textChanged.connect(self.filter_channels)
        self.search_box.setClearButtonEnabled(True)  # Add clear button inside search box
        
        # Add Ctrl+F shortcut for search box
        search_shortcut = QShortcut(QKeySequence(Qt.Key_S, Qt.NoModifier), self)
        search_shortcut.activated.connect(self.search_box.setFocus)
        
        # Create custom clear button action
        clear_action = QAction("⌫", self.search_box)
        self.search_box.addAction(clear_action, QLineEdit.TrailingPosition)
        
        search_layout.addWidget(search_icon)
        search_layout.addWidget(self.search_box)
        left_layout.addLayout(search_layout)  # Add to left pane layout
        
        # Now style the search box with custom clear button styling
        self.search_box.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                padding-right: 25px;  /* Make room for clear button */
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
            }
            QLineEdit:focus {
                border-color: #0078d4;
            }
            QLineEdit QToolButton {  /* Style for the clear button */
                background: none;
                border: none;
                padding: 0px 6px;
                color: #666;
                font-size: 16px;
            }
            QLineEdit QToolButton:hover {
                background-color: #e0e0e0;
                border-radius: 2px;
            }
        """)
        
        # Style the search icon
        search_icon.setStyleSheet("""
            QLabel {
                color: #666;
                padding: 0 5px;
            }
        """)
        
        # Add margins to search layout
        search_layout.setContentsMargins(0, 5, 0, 5)
        search_layout.setSpacing(5)
        
    def fetch_channels(self):
        """Fetch channel list from current TVHeadend server"""
        try:
            if not self.servers:
                print("Debug: No servers configured")
                self.statusbar.showMessage("No servers configured")
                return
                
            server = self.servers[self.server_combo.currentIndex()]
            print(f"Debug: Fetching channels from server: {server['url']}")
            
            # Initialize verification list
            channel_verification = []
            
            # Update status bar
            self.statusbar.showMessage("Connecting to server...")
            
            # Clean and format the URL properly
            url = server['url']
            if url.startswith('https://') or url.startswith('http://'):
                base_url = url
            else:
                base_url = f"http://{url}"
            
            api_url = f'{base_url}/api/channel/grid?limit=10000'
            print(f"Debug: Making request to: {api_url}")
            
            # Create auth tuple if credentials exist
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                print(f"Debug: Using authentication with username: {server.get('username', '')}")
            
            # Add timeout parameter (10 seconds)
            response = requests.get(api_url, auth=auth, timeout=10)
            
            channels = response.json()['entries']
            print(f"Debug: Found {len(channels)} channels")
            
            # First, disable sorting while adding items
            #self.channel_list.setSortingEnabled(False)
            
            # Clear existing items
            self.channel_list.setRowCount(0)
            
            # Create a list to store channel data for sorting
            channel_data = []
            
            # Process all channels first
            for channel in channels:
                try:
                    channel_name = channel.get('name', 'Unknown Channel')
                    channel_number = channel.get('number', 0)  # Use 0 as default for unnumbered channels
                    
                    # Store channel data for sorting
                    channel_data.append({
                        'number': channel_number,
                        'name': channel_name,
                        'data': channel
                    })
                    
                except Exception as e:
                    print(f"Debug: Error processing channel {channel.get('name', 'Unknown')}: {str(e)}")
                    continue
            
            # Sort channels by number, then name
            channel_data.sort(key=lambda x: (x['number'] or float('inf'), x['name'].lower()))
            
            # Now add sorted channels to the table
            for idx, channel in enumerate(channel_data):
                try:
                    print(f"Debug: Adding channel {idx + 1}/{len(channel_data)}: {channel['name']}")
                    
                    row = self.channel_list.rowCount()
                    self.channel_list.insertRow(row)
                    
                    # Create and add number item
                    number_item = QTableWidgetItem()
                    number_item.setData(Qt.DisplayRole, channel['number'])
                    self.channel_list.setItem(row, 0, number_item)
                    
                    # Create and add name item
                    name_item = QTableWidgetItem(channel['name'])
                    name_item.setData(Qt.UserRole, channel['data'])
                    self.channel_list.setItem(row, 1, name_item)
                    
                    # Add to verification list
                    channel_verification.append({
                        'row': row,
                        'name': channel['name'],
                        'number': channel['number']
                    })
                    
                    print(f"Debug: Added channel to row {row}: {channel['name']}")
                    
                except Exception as e:
                    print(f"Debug: Error adding channel to table: {str(e)}")
                    continue
            
            # Re-enable sorting but don't trigger an automatic sort
            self.channel_list.setSortingEnabled(True)
            
            # Verify the final table contents
            print("\nDebug: Channel Verification:")
            print(f"Original channel count: {len(channels)}")
            print(f"Added channel count: {len(channel_verification)}")
            print(f"Table row count: {self.channel_list.rowCount()}")
            
            print("\nDebug: Final Table Contents:")
            for row in range(self.channel_list.rowCount()):
                number_item = self.channel_list.item(row, 0)
                name_item = self.channel_list.item(row, 1)
                if number_item and name_item:
                    number = number_item.data(Qt.DisplayRole)
                    name = name_item.text()
                    print(f"Row {row}: #{number} - {name}")
                else:
                    print(f"Row {row}: Missing items")
            
            self.statusbar.showMessage("Channels loaded successfully")
            
        except Exception as e:
            print(f"Debug: Error in fetch_channels: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            
            # Show error dialog
            dialog = ConnectionErrorDialog(
                server['name'], 
                f"Unexpected error: {str(e)}", 
                self
            )
            if dialog.exec_() == QDialog.Accepted:
                print("Debug: Retrying connection...")
                self.fetch_channels()
            else:
                print("Debug: Connection attempt aborted by user")
                self.statusbar.showMessage("Connection aborted")
                self.channel_list.clear()
        

    def start_recording(self):
        print("Debug: Starting recording")
        try:
            # Get selected channel
            current_channel = self.channel_list.currentItem()
            if not current_channel:
                print("Debug: No channel selected for recording")
                self.statusbar.showMessage("Please select a channel to record")
                return

            # Show duration dialog
            duration_dialog = RecordingDurationDialog(self)
            if duration_dialog.exec_() != QDialog.Accepted:
                print("Debug: Recording cancelled by user")
                return
            
            duration = duration_dialog.get_duration()
            print(f"Debug: Selected recording duration: {duration} seconds")

            channel_name = current_channel.text()
            print(f"Debug: Attempting to record channel: {channel_name}")
            
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            print(f"Debug: Using server: {server['url']}")
            
            # Create auth if needed
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                print(f"Debug: Using authentication with username: {server.get('username', '')}")
            
            # First, get channel UUID
            api_url = f'{server["url"]}/api/channel/grid?limit=10000'
            print(f"Debug: Getting channel UUID from: {api_url}")
            
            response = requests.get(api_url, auth=auth)
            print(f"Debug: Channel list response status: {response.status_code}")
            
            channels = response.json()['entries']
            channel_uuid = None
            for channel in channels:
                if channel['name'] == channel_name:
                    channel_uuid = channel['uuid']
                    print(f"Debug: Found channel UUID: {channel_uuid}")
                    break
                
            if not channel_uuid:
                print(f"Debug: Channel UUID not found for: {channel_name}")
                self.statusbar.showMessage("Channel not found")
                return
            
            # Prepare recording request
            now = int(datetime.now().timestamp())
            stop_time = now + duration
            
            # Format exactly as in the working curl command
            conf_data = {
                "start": now,
                "stop": stop_time,
                "channel": channel_uuid,
                "title": {"eng": "Instant Recording"},
                "subtitle": {"eng": "Recorded via TVHplayer"}
            }
            
            # Convert to string format as expected by the API
            data = {'conf': json.dumps(conf_data)}
            print(f"Debug: Recording data: {data}")
            
            # Make recording request
            record_url = f'{server["url"]}/api/dvr/entry/create'
            print(f"Debug: Sending recording request to: {record_url}")
            
            response = requests.post(record_url, data=data, auth=auth)
            print(f"Debug: Recording response status: {response.status_code}")
            print(f"Debug: Recording response: {response.text}")
            
            if response.status_code == 200:
                duration_minutes = duration // 60
                self.statusbar.showMessage(
                    f"Recording started for: {channel_name} ({duration_minutes} minutes)"
                )
                print("Debug: Recording started successfully")
                self.start_recording_indicator()  # Start the recording indicator
            else:
                self.statusbar.showMessage("Failed to start recording")
                print(f"Debug: Recording failed with status {response.status_code}")
                
        except Exception as e:
            print(f"Debug: Recording error: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Recording error: {str(e)}")
            
    def stop_playback(self):
        print("Debug: Stopping playback")
        """Stop current playback"""
        self.media_player.stop()
        self.statusbar.showMessage("Playback stopped")

    def toggle_fullscreen(self):
        """Toggle fullscreen mode for just the video frame"""
        print(f"Debug: Toggling fullscreen. Current state: {self.is_fullscreen}")
        
        if self.is_fullscreen:
            # Exit fullscreen - restore video frame to original layout
            self.video_frame.setParent(self.findChild(QFrame))
            right_layout = self.findChild(QVBoxLayout, "right_layout") 
            right_layout.insertWidget(0, self.video_frame)
            
            # Reset VLC window handle for normal view
            if sys.platform.startswith('linux'):
                self.media_player.set_xwindow(self.video_frame.winId().__int__())
            elif sys.platform == "win32":
                self.media_player.set_hwnd(self.video_frame.winId().__int__())
            elif sys.platform == "darwin":
                self.media_player.set_nsobject(self.video_frame.winId().__int__())
        else:
            # Enter fullscreen - make video frame fill screen
            self.video_frame.setParent(None)
            self.video_frame.setWindowFlags(Qt.Window)
            self.video_frame.showFullScreen()
            
            # Reset VLC window handle for fullscreen
            if sys.platform.startswith('linux'):
                self.media_player.set_xwindow(self.video_frame.winId().__int__())
            elif sys.platform == "win32":
                self.media_player.set_hwnd(self.video_frame.winId().__int__())
            elif sys.platform == "darwin":
                self.media_player.set_nsobject(self.video_frame.winId().__int__())
        
        self.is_fullscreen = not self.is_fullscreen

    def load_servers(self):
        """Load TVHeadend server configurations"""
        try:
            with open('servers.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # Return empty list if no config file exists
            return []
        except json.JSONDecodeError:
            # Return default server if config file is invalid
            return [{
                'name': 'Default Server',
                'url': '127.0.0.1:9981'
            }]

    def manage_servers(self):
        print("Debug: Opening server management dialog")
        dialog = ServerDialog(self)
        dialog.load_servers(self.servers)
        print(f"Debug: Loaded {len(self.servers)} servers into dialog")
        if dialog.exec_() == QDialog.Accepted:
            self.servers = dialog.servers
            print(f"Debug: Updated servers list, now has {len(self.servers)} servers")
            self.save_config()
            
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
            # Update window geometry in config
            if not self.is_fullscreen:
                self.config['window_geometry'] = {
                    'x': self.x(),
                    'y': self.y(),
                    'width': self.width(),
                    'height': self.height()
                }
            
            # Update servers in config
            self.config['servers'] = self.servers
            
            # Update last server
            self.config['last_server'] = self.server_combo.currentIndex()
            
            # Save to file
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
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
            channel_data = name_item.data(Qt.UserRole)
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
            
            # Update config with new server selection
            self.config['last_server'] = index
            
            # Save updated config to file
            try:
                with open(self.config_file, 'w') as f:
                    json.dump(self.config, f)
                print(f"Debug: Saved server index {index} to config")
            except Exception as e:
                print(f"Debug: Error saving config: {e}")
                
            # Load channels from newly selected server
            self.fetch_channels()

    def on_volume_changed(self, value):
        print(f"Debug: Volume changed to {value}")
        self.media_player.audio_set_volume(value)

    def eventFilter(self, obj, event):
        """Handle double-click and key events"""
        if obj == self.video_frame:
            if event.type() == event.MouseButtonDblClick:
                self.toggle_fullscreen()
                return True
            
        # Handle key events for both main window and fullscreen window
        if event.type() == event.KeyPress:
            if event.key() == Qt.Key_Escape and self.is_fullscreen:
                self.toggle_fullscreen()
                return True
            elif event.key() == Qt.Key_F:
                self.toggle_fullscreen()
                return True
            
        return super().eventFilter(obj, event)

    def toggle_mute(self):
        """Toggle audio mute state"""
        print("Debug: Toggling mute")
        is_muted = self.mute_btn.isChecked()
        
        if is_muted:
            self.media_player.audio_set_mute(True)
            self.mute_btn.setText("🔇")  # Muted speaker icon
            self.mute_btn.setToolTip("Unmute")
            print("Debug: Audio muted")
        else:
            self.media_player.audio_set_mute(False)
            self.mute_btn.setText("🔊")  # Speaker icon
            self.mute_btn.setToolTip("Mute")
            print("Debug: Audio unmuted")

    def show_about(self):
        """Show the about dialog"""
        print("Debug: Showing about dialog")
        about_text = (
            "<div style='text-align: center;'>"
            "<h2>TVHplayer</h2>"
            "<p>Version 3.3</p>"
            "<p>A powerful and user-friendly TVHeadend client application.</p>"
            "<p style='margin-top: 20px;'><b>Created by:</b><br>mFat</p>"
            "<p style='margin-top: 20px;'><b>Built with:</b><br>"
            "Python, PyQt5, and VLC</p>"
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
        msg.setTextFormat(Qt.RichText)
        msg.setMinimumWidth(400)  # Make dialog wider to prevent text wrapping
        msg.exec_()

    def toggle_recording(self):
        """Toggle between starting and stopping recording"""
        if self.record_btn.isChecked():
            self.start_recording()
        else:
            self.stop_recording()

    def stop_recording(self):
        """Stop active recordings"""
        print("Debug: Attempting to stop recordings")
        try:
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            print(f"Debug: Using server: {server['url']}")
            
            # Create auth if needed
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                print(f"Debug: Using authentication with username: {server.get('username', '')}")
            
            # Get list of active recordings
            api_url = f'{server["url"]}/api/dvr/entry/grid'
            print(f"Debug: Getting recordings from: {api_url}")
            
            response = requests.get(api_url, auth=auth)
            print(f"Debug: Recording list response status: {response.status_code}")
            
            recordings = response.json()['entries']
            print(f"Debug: Total recordings found: {len(recordings)}")
            
            # Print all recordings and their statuses for debugging
            for recording in recordings:
                print(f"Debug: Recording '{recording.get('disp_title', 'Unknown')}' - Status: {recording.get('status', 'unknown')}")
            
            # Look for recordings with status 'Running' (this seems to be the actual status used by TVHeadend)
            active_recordings = [r for r in recordings if r['status'] in ['Running', 'recording']]
            
            if not active_recordings:
                print("Debug: No active recordings found")
                self.statusbar.showMessage("No active recordings to stop")
                self.stop_recording_indicator()  # Make sure to hide indicator
                return
                
            print(f"Debug: Found {len(active_recordings)} active recordings")
            
            # Stop each active recording
            for recording in active_recordings:
                stop_url = f'{server["url"]}/api/dvr/entry/stop'
                data = {'uuid': recording['uuid']}
                
                print(f"Debug: Stopping recording: {recording.get('disp_title', 'Unknown')} ({recording['uuid']})")
                stop_response = requests.post(stop_url, data=data, auth=auth)
                
                if stop_response.status_code == 200:
                    print(f"Debug: Successfully stopped recording: {recording['uuid']}")
                else:
                    print(f"Debug: Failed to stop recording: {recording['uuid']}")
                    print(f"Debug: Response: {stop_response.text}")
            
            self.stop_recording_indicator()  # Hide the indicator after stopping recordings
            self.statusbar.showMessage(f"Stopped {len(active_recordings)} recording(s)")
            
        except Exception as e:
            print(f"Debug: Error stopping recordings: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Error stopping recordings: {str(e)}")
            self.stop_recording_indicator()  # Make sure to hide indicator even on error

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
        self.recording_animation.setEasingCurve(QEasingCurve.InOutSine)
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
            server = self.servers[self.server_combo.currentIndex()]
            print(f"Debug: Using server: {server}")

            # Test connection first
            test_url = f"{server['url']}/api/status/connections"
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                print(f"Debug: Using authentication with username: {server.get('username', '')}")

            print(f"Debug: Testing connection to: {test_url}")
            try:
                test_response = requests.get(test_url, auth=auth, timeout=5)
                print(f"Debug: Connection test response: {test_response.status_code}")
                if test_response.status_code == 200:
                    print("Debug: Server connection successful")
                else:
                    print(f"Debug: Server connection failed with status {test_response.status_code}")
                    self.statusbar.showMessage("Failed to connect to server")
                    return
            except Exception as conn_err:
                print(f"Debug: Connection test failed: {str(conn_err)}")
                self.statusbar.showMessage("Failed to connect to server")
                return

            # Now try to get DVR data
            dvr_url = f"{server['url']}/api/dvr/entry/grid"
            print(f"Debug: Fetching DVR data from: {dvr_url}")
            try:
                dvr_response = requests.get(dvr_url, auth=auth, timeout=5)
                print(f"Debug: DVR data response: {dvr_response.status_code}")
                if dvr_response.status_code == 200:
                    dvr_data = dvr_response.json()
                    print(f"Debug: DVR data received: {len(dvr_data.get('entries', []))} entries")
                    # Print first entry as sample if available
                    if dvr_data.get('entries'):
                        print("Debug: Sample DVR entry:")
                        print(dvr_data['entries'][0])
                else:
                    print(f"Debug: Failed to get DVR data: {dvr_response.text}")
                    self.statusbar.showMessage("Failed to get DVR data")
                    return
            except Exception as dvr_err:
                print(f"Debug: DVR data fetch failed: {str(dvr_err)}")
                self.statusbar.showMessage("Failed to get DVR data")
                return

            # If we got here, show the dialog
            dialog = DVRStatusDialog(server, self)
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

    def start_local_recording(self, channel_name):
        """Record channel stream to local disk using ffmpeg"""
        try:
            if not channel_name:
                print("Debug: No channel selected for recording")
                self.statusbar.showMessage("Please select a channel to record")
                return

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
                
            # Get current server and auth info
            server = self.servers[self.server_combo.currentIndex()]
            
            # Get channel UUID
            api_url = f'{server["url"]}/api/channel/grid?limit=10000'
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
            
            print(f"Debug: Fetching channel list from: {api_url}")
            response = requests.get(api_url, auth=auth)
            channels = response.json()['entries']
            
            channel_uuid = None
            for channel in channels:
                if channel['name'] == channel_name:
                    channel_uuid = channel['uuid']
                    break
                    
            if not channel_uuid:
                print(f"Debug: Channel UUID not found for: {channel_name}")
                self.statusbar.showMessage("Channel not found")
                return
                
            # Create stream URL
            server_url = server['url'].rstrip('/')
            if not server_url.startswith(('http://', 'https://')):
                server_url = f'http://{server_url}'
            
            stream_url = f'{server_url}/stream/channel/{channel_uuid}'
            
            # Build ffmpeg command
            ffmpeg_cmd = [
                'ffmpeg',
                '-hide_banner',
                '-loglevel', 'warning',
                '-nostats',
                '-y'  # Overwrite output
            ]
            
            # Add auth headers if needed
            if auth:
                import base64
                auth_string = f"{auth[0]}:{auth[1]}"
                auth_bytes = auth_string.encode('ascii')
                base64_bytes = base64.b64encode(auth_bytes)
                base64_auth = base64_bytes.decode('ascii')
                ffmpeg_cmd.extend([
                    '-headers', f'Authorization: Basic {base64_auth}\r\n'
                ])
            
            # Add input options
            ffmpeg_cmd.extend([
                '-i', stream_url,
                '-analyzeduration', '10M',  # Increase analyze duration
                '-probesize', '10M'         # Increase probe size
            ])

            # Add output options based on file extension
            if file_path.lower().endswith('.mp4'):
                ffmpeg_cmd.extend([
                    '-c:v', 'copy',
                    '-c:a', 'aac',          # Transcode audio to AAC
                    '-b:a', '192k',         # Audio bitrate
                    '-movflags', '+faststart',
                    '-f', 'mp4'
                ])
            else:  # Default to .ts
                ffmpeg_cmd.extend([
                    '-c', 'copy',           # Copy both streams without transcoding
                    '-f', 'mpegts'          # Force MPEG-TS format
                ])
            
            # Add output file
            ffmpeg_cmd.append(file_path)
            
            print("Debug: Starting ffmpeg with command:")
            # Print command with hidden auth if present
            safe_cmd = ' '.join(ffmpeg_cmd)
            if auth:
                safe_cmd = safe_cmd.replace(base64_auth, "***")
            print(f"Debug: {safe_cmd}")
            
            # Start ffmpeg process
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8
            )
            
            # Start monitoring process
            self.recording_monitor = QTimer()
            self.recording_monitor.timeout.connect(
                lambda: self.check_recording_status(file_path)
            )
            self.recording_monitor.start(2000)  # Check every 2 seconds
            
            self.statusbar.showMessage(f"Local recording started: {file_path}")
            self.start_recording_indicator()
            
        except Exception as e:
            print(f"Debug: Local recording error: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Local recording error: {str(e)}")

    def check_recording_status(self, file_path):
        """Check if the recording is actually working"""
        try:
            import os
            if not os.path.exists(file_path):
                print("Debug: Recording file does not exist")
                return
            
            file_size = os.path.getsize(file_path)
            print(f"Debug: Current recording file size: {file_size} bytes")
            
            if hasattr(self, 'ffmpeg_process'):
                return_code = self.ffmpeg_process.poll()
                if return_code is not None:
                    # Process has ended
                    _, stderr = self.ffmpeg_process.communicate()
                    print(f"Debug: FFmpeg process ended with return code: {return_code}")
                    if stderr:
                        print(f"Debug: FFmpeg error output: {stderr.decode()}")
                    
                    if file_size == 0 or return_code != 0:
                        print("Debug: Recording failed - stopping processes")
                        self.stop_local_recording()
                        self.statusbar.showMessage("Recording failed - check console for errors")
                        return
                    
                # Check if file is growing
                if hasattr(self, 'last_file_size'):
                    if file_size == self.last_file_size:
                        print("Debug: File size not increasing - potential stall")
                        self.stall_count = getattr(self, 'stall_count', 0) + 1
                        if self.stall_count > 5:  # After 10 seconds of no growth
                            print("Debug: Recording stalled - restarting")
                            self.stop_local_recording()
                            self.start_local_recording(self.channel_list.currentItem().text())
                            return
                    else:
                        self.stall_count = 0
                
                self.last_file_size = file_size
            
        except Exception as e:
            print(f"Debug: Error checking recording status: {str(e)}")

    def stop_local_recording(self):
        """Stop local recording"""
        try:
            print("Debug: Stopping local recording")
            
            # Stop monitoring
            if hasattr(self, 'recording_monitor') and self.recording_monitor is not None:
                self.recording_monitor.stop()
                self.recording_monitor = None
            
            # Stop ffmpeg process
            if hasattr(self, 'ffmpeg_process') and self.ffmpeg_process is not None:
                print("Debug: Stopping ffmpeg process")
                self.ffmpeg_process.terminate()
                try:
                    self.ffmpeg_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.ffmpeg_process.kill()
                self.ffmpeg_process = None
            
            # Clear stall detection variables
            if hasattr(self, 'last_file_size'):
                del self.last_file_size
            if hasattr(self, 'stall_count'):
                del self.stall_count
            
            self.statusbar.showMessage("Local recording stopped")
            self.stop_recording_indicator()
            
        except Exception as e:
            print(f"Debug: Error stopping local recording: {str(e)}")
            self.statusbar.showMessage(f"Error stopping local recording: {str(e)}")
            self.stop_recording_indicator()

    def load_config(self):
        """Load application configuration"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            else:
                # Return default configuration
                return {
                    'volume': 50,
                    'last_server': 0,
                    'recording_path': str(Path.home()),
                    'window_geometry': {
                        'x': 100,
                        'y': 100,
                        'width': 1200,
                        'height': 700
                    },
                }
        except Exception as e:
            print(f"Debug: Error loading config: {str(e)}")
            return self.get_default_config()

    def get_default_config(self):
        """Return default configuration"""
        return {
            'volume': 50,
            'last_server': 0,
            'recording_path': str(Path.home()),
            'window_geometry': {
                'x': 100,
                'y': 100,
                'width': 1200,
                'height': 700
            },
        }

    def closeEvent(self, event):
        """Save configuration when closing the application"""
        self.save_config()
        super().closeEvent(event)

    def show_channel_context_menu(self, position):
        """Show context menu for channel list items"""
        menu = QMenu()
        
        # Get the item at the position
        row = self.channel_list.rowAt(position.y())
        if row >= 0:
            channel_item = self.channel_list.item(row, 1)  # Get name column item
            channel_data = channel_item.data(Qt.UserRole)
            
            # Add menu actions
            play_action = menu.addAction("Play")
            play_action.triggered.connect(lambda: self.play_channel_by_data(channel_data))
            record_action = menu.addAction("Record")
            record_action.triggered.connect(lambda: self.start_recording())
            local_record_action = menu.addAction("Record Locally")
            local_record_action.triggered.connect(
                lambda: self.start_local_recording(channel_data['name']))
            
            # Add EPG action
            epg_action = menu.addAction("Show EPG")
            epg_action.triggered.connect(lambda: self.show_channel_epg(channel_data['name']))
            
            # Show the menu at the cursor position
            menu.exec_(self.channel_list.viewport().mapToGlobal(position))

    def show_channel_epg(self, channel_name):
        """Fetch and show EPG data for the selected channel"""
        try:
            print(f"Debug: Fetching EPG for channel: {channel_name}")
            
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            print(f"Debug: Using server: {server['url']}")
            
            # Create auth if needed
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                print(f"Debug: Using authentication with username: {server.get('username', '')}")
            
            # First get channel UUID
            api_url = f'{server["url"]}/api/channel/grid?limit=10000'
            print(f"Debug: Getting channel UUID from: {api_url}")
            
            response = requests.get(api_url, auth=auth)
            print(f"Debug: Channel list response status: {response.status_code}")
            
            channels = response.json()['entries']
            print(f"Debug: Found {len(channels)} channels in response")
            
            channel_uuid = None
            for channel in channels:
                if channel['name'] == channel_name:
                    channel_uuid = channel['uuid']
                    print(f"Debug: Found channel UUID: {channel_uuid}")
                    break
            
            if not channel_uuid:
                print(f"Debug: Channel UUID not found for: {channel_name}")
                self.statusbar.showMessage("Channel not found")
                return
            
            # Get EPG data for the channel
            epg_url = f'{server["url"]}/api/epg/events/grid'
            params = {
                'channel': channel_uuid,
                'limit': 24  # Get next 24 events
            }
            print(f"Debug: Fetching EPG data from: {epg_url}")
            print(f"Debug: With parameters: {params}")
            
            response = requests.get(epg_url, params=params, auth=auth)
            print(f"Debug: EPG response status: {response.status_code}")
            
            if response.status_code == 200:
                epg_data = response.json()['entries']
                if epg_data:
                    dialog = EPGDialog(channel_name, epg_data, server, self)
                    dialog.show()
                else:
                    self.statusbar.showMessage("No EPG data available")
            else:
                self.statusbar.showMessage("Failed to fetch EPG data")
                
        except Exception as e:
            print(f"Debug: Error fetching EPG: {str(e)}")
            self.statusbar.showMessage(f"Error fetching EPG: {str(e)}")

    def play_channel_from_table(self, item):
        """Play channel from table selection"""
        row = item.row()
        channel_item = self.channel_list.item(row, 1)  # Get name column item
        channel_data = channel_item.data(Qt.UserRole)  # Original data is stored here
        self.play_channel_by_data(channel_data)

    def play_channel_by_data(self, channel_data):
        """Play channel using channel data"""
        try:
            server = self.servers[self.server_combo.currentIndex()]
            server_url = server['url']
            print(f"Debug: Playing channel from server: {server_url}")
            
            # Create auth string if credentials exist
            auth_string = ''
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                auth_string = f"{server.get('username', '')}:{server.get('password', '')}@"
            
            # Use channel UUID directly from stored data
            channel_uuid = channel_data['uuid']
            
            if channel_uuid:
                # Create media URL with auth if needed
                if auth_string:
                    # Ensure server_url starts with http:// or https://
                    if not server_url.startswith(('http://', 'https://')):
                        server_url = f'http://{server_url}'
                    
                    # Insert auth string after http:// or https://
                    stream_url = server_url.replace('://', f'://{auth_string}')
                    stream_url = f'{stream_url}/stream/channel/{channel_uuid}'

                else:
                    if not server_url.startswith(('http://', 'https://')):
                        server_url = f'http://{server_url}'
                    stream_url = f'{server_url}/stream/channel/{channel_uuid}'
                print(f"Debug: Stream URL: {stream_url}")
                
                media = self.instance.media_new(stream_url)
                self.media_player.set_media(media)
                self.media_player.play()
                print(f"Debug: Started playback")
                self.statusbar.showMessage(f"Playing: {channel_data['name']}")
            else:
                print(f"Debug: Channel not found: {channel_data['name']}")
                self.statusbar.showMessage("Channel not found")
                
        except Exception as e:
            print(f"Debug: Error in play_channel: {str(e)}")
            self.statusbar.showMessage(f"Playback error: {str(e)}")

    def show_server_status(self):
        """Show server status dialog"""
        try:
            server = self.servers[self.server_combo.currentIndex()]
            dialog = ServerStatusDialog(server, self)
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



class EPGDialog(QDialog):
    def __init__(self, channel_name, epg_data, server, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"EPG Guide - {channel_name}")
        self.setModal(False)
        self.resize(800, 500)
        self.server = server
        self.channel_name = channel_name
        self.setup_ui(epg_data)
        
    def setup_ui(self, epg_data):
        layout = QVBoxLayout(self)
        
        # Create list widget for EPG entries
        self.epg_list = QListWidget()
        layout.addWidget(self.epg_list)
        
        # Add EPG entries to list with record buttons
        for entry in epg_data:
            # Create widget to hold program info and record button
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 2, 5, 2)
            # Get start and stop times
            start_time = datetime.fromtimestamp(entry['start']).strftime('%H:%M')
            stop_time = datetime.fromtimestamp(entry['stop']).strftime('%H:%M')
            
            # Get title and description
            if isinstance(entry.get('title'), dict):
                title = entry['title'].get('eng', 'No title')
            else:
                title = str(entry.get('title', 'No title'))
                
            if isinstance(entry.get('description'), dict):
                description = entry['description'].get('eng', 'No description')
            else:
                description = str(entry.get('description', 'No description'))
                
                # Create label for program info
                info_text = f"{start_time} - {stop_time}: {title}"
                info_label = QLabel(info_text)
                info_label.setToolTip(description)
                item_layout.addWidget(info_label, stretch=1)
                
                # Create record button with unicode icon
                record_btn = QPushButton("⏺")  # Unicode record symbol
                record_btn.setFixedWidth(32)  # Make button smaller since it's just an icon
                record_btn.setFixedHeight(32)  # Make it square
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
                record_btn.clicked.connect(
                    lambda checked, e=entry: self.schedule_recording(e)
                )
                item_layout.addWidget(record_btn)
                
                # Create list item and set custom widget
                list_item = QListWidgetItem(self.epg_list)
                list_item.setSizeHint(item_widget.sizeHint())
                self.epg_list.addItem(list_item)
                self.epg_list.setItemWidget(list_item, item_widget)
                try:
                    self.epg_list.addItem(list_item)
                    self.epg_list.setItemWidget(list_item, item_widget)
                except Exception as e:
                    print(f"Debug: Error processing EPG entry: {str(e)}")
                    print(f"Debug: Problematic entry: {entry}")
                    continue

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
    def schedule_recording(self, entry):
        """Schedule a recording for the selected EPG entry"""
        try:
            print(f"Debug: Scheduling recording for: {entry.get('title', 'Unknown')}")
            
            # Create auth if needed
            auth = None
            if self.server.get('username') or self.server.get('password'):
                auth = (self.server.get('username', ''), self.server.get('password', ''))
            
            # Prepare recording request
            conf_data = {
                "start": entry['start'],
                "stop": entry['stop'],
                "channel": entry['channelUuid'],
                "title": entry.get('title', {"eng": "Scheduled Recording"}),
                "description": entry.get('description', {"eng": ""}),
                "comment": "Scheduled via TVHplayer"
            }
            
            # Convert to string format as expected by the API
            data = {'conf': json.dumps(conf_data)}
            print(f"Debug: Recording data: {data}")
            
            # Make recording request
            record_url = f'http://{self.server["url"]}/api/dvr/entry/create'
            print(f"Debug: Sending recording request to: {record_url}")
            
            response = requests.post(record_url, data=data, auth=auth)
            print(f"Debug: Recording response status: {response.status_code}")
            print(f"Debug: Recording response: {response.text}")
            
            if response.status_code == 200:
                QMessageBox.information(
                    self,
                    "Success",
                    f"Recording scheduled successfully for {entry.get('title', 'Unknown')}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Failed to schedule recording: {response.text}"
                )
                
        except Exception as e:
            print(f"Debug: Error scheduling recording: {str(e)}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to schedule recording: {str(e)}"
            )

def main():
    app = QApplication(sys.argv)
    try:
        # Try to set display name if supported
        if hasattr(QCoreApplication, 'setApplicationDisplayName'):
            QCoreApplication.setApplicationDisplayName("TVHplayer")
    except Exception as e:
        print(f"Debug: Could not set application display name: {e}")
        
    # Set application name (this should work on all versions)
    app.setApplicationName("TVHplayer")
    
    window = TVHeadendClient()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
from datetime import datetime, timedelta
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
    QMenu, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QSizePolicy, QToolButton, QShortcut, QCheckBox, QGroupBox, QInputDialog
)
from PyQt5.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, QAbstractAnimation, QRect, QCoreApplication, pyqtSignal
from PyQt5.QtGui import QIcon, QPainter, QColor, QKeySequence, QPalette, QPixmap, QFont, QBrush  # Removed duplicate QColor
import json
import requests
# Replace this line:
#from . import resources_rc

# With this more flexible import approach:
try:
    from . import resources_rc  # Try package import first
except ImportError:
    import resources_rc  # Fall back to direct import when running from source
# or
#from tvhplayer import resources_rc  # Use absolute import
import time
import subprocess
import os
import traceback
from pathlib import Path
import logging
import platform
from enum import Enum
import m3u8
import re
import base64
from urllib.parse import urlparse, urljoin, urlunparse
import threading
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from epg_window import EPGWindow  # Add this import at the top of your file

# Add this line to explicitly set the platform plugin
import os
os.environ['QT_QPA_PLATFORM'] = 'cocoa'  # Use 'cocoa' for macOS

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
        self.upcoming_table.setSelectionBehavior(QTableWidget.SelectRows)  # Select entire rows
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
        
        # Buttons layout
        button_layout = QHBoxLayout()
        
        # Stop button
        self.stop_btn = QPushButton("Stop Selected Recording")
        self.stop_btn.clicked.connect(self.stop_selected_recording)
        self.stop_btn.setEnabled(False)  # Disabled by default until a recording is selected
        button_layout.addWidget(self.stop_btn)
        
        # Spacer
        button_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Connect selection change to enable/disable stop button
        self.upcoming_table.itemSelectionChanged.connect(self.on_selection_changed)
        
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

    def on_selection_changed(self):
        """Enable/disable stop button based on selection"""
        selected_items = self.upcoming_table.selectedItems()
        if not selected_items:
            self.stop_btn.setEnabled(False)
            return
            
        # Get the row and check if it's a recording in progress
        row = selected_items[0].row()
        status_item = self.upcoming_table.item(row, 4)
        
        if status_item and status_item.text() == "Recording":
            self.stop_btn.setEnabled(True)
        else:
            self.stop_btn.setEnabled(False)
            
    def stop_selected_recording(self):
        """Stop the selected recording"""
        selected_items = self.upcoming_table.selectedItems()
        if not selected_items:
            return
            
        row = selected_items[0].row()
        
        # Get recording information
        channel_item = self.upcoming_table.item(row, 0)
        title_item = self.upcoming_table.item(row, 1)
        status_item = self.upcoming_table.item(row, 4)
        
        if not channel_item or not title_item or not status_item:
            return
            
        if status_item.text() != "Recording":
            QMessageBox.information(self, "Stop Recording", "Only active recordings can be stopped.")
            return
            
        channel_name = channel_item.text()
        title = title_item.text()
        
        # Confirm with user
        confirm = QMessageBox.question(
            self, 
            "Stop Recording", 
            f"Are you sure you want to stop recording '{title}' on channel '{channel_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
            
        # Find the recording UUID from the API
        try:
            # Create auth if needed
            auth = None
            if self.server.get('username') or self.server.get('password'):
                auth = (self.server.get('username', ''), self.server.get('password', ''))
            
            # Get DVR entries
            api_url = f'{self.server["url"]}/api/dvr/entry/grid'
            print(f"Debug: Fetching DVR entries from: {api_url}")
            response = requests.get(api_url, auth=auth)
            
            if response.status_code == 200:
                data = response.json()
                entries = data.get('entries', [])
                
                # Find the matching recording
                for entry in entries:
                    if (entry.get('channelname', '') == channel_name and 
                        entry.get('disp_title', '') == title and 
                        entry.get('status', '') == "Running"):
                        
                        # Found the recording, get its UUID
                        uuid = entry.get('uuid')
                        if uuid:
                            print(f"Debug: Found recording to stop - UUID: {uuid}")
                            
                            # Directly stop the recording on the server
                            stop_url = f'{self.server["url"]}/api/dvr/entry/stop'
                            print(f"Debug: Sending stop request to: {stop_url}")
                            
                            # Prepare stop request
                            data = {'uuid': uuid}
                            print(f"Debug: Stop request data: {data}")
                            
                            try:
                                # Set a 5-second timeout for the request
                                stop_response = requests.post(stop_url, data=data, auth=auth, timeout=5)
                                print(f"Debug: Stop request response status: {stop_response.status_code}")
                                print(f"Debug: Stop request response text: {stop_response.text}")
                                
                                if stop_response.status_code == 200:
                                    print(f"Debug: TVHeadend recording stopped successfully")
                                    
                                    # Also call parent's stop_recording to update its internal state
                                    parent = self.parent()
                                    if parent and hasattr(parent, 'stop_recording'):
                                        parent.stop_recording(uuid=uuid)
                                    
                                    # Update the table after a short delay
                                    QTimer.singleShot(2000, self.update_status)
                                    return
                                else:
                                    print(f"Debug: Failed to stop TVHeadend recording: {stop_response.text}")
                                    QMessageBox.warning(self, "Error", f"Failed to stop recording: Server returned {stop_response.status_code}")
                            except requests.exceptions.Timeout:
                                print("Debug: Request timed out when trying to stop recording")
                                QMessageBox.warning(self, "Error", "Failed to stop recording: Server timeout")
                            except requests.exceptions.ConnectionError:
                                print("Debug: Connection error when trying to stop recording")
                                QMessageBox.warning(self, "Error", "Failed to stop recording: Server unreachable")
                            
                            return
                
                # If we get here, we didn't find the recording
                QMessageBox.warning(self, "Error", "Could not find the recording in the server.")
            else:
                QMessageBox.warning(self, "Error", f"Failed to get recording information from server: {response.status_code}")
                
        except Exception as e:
            print(f"Debug: Error stopping recording: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            QMessageBox.warning(self, "Error", f"Failed to stop recording: {str(e)}")
    
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
        """Get recording duration in hours and minutes"""
        hours = self.hours_spin.value()
        minutes = self.minutes_spin.value()
        return hours, minutes

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
            
class SourceType(Enum):
    TVHEADEND = "tvheadend"
    M3U = "m3u"
            
class ServerConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Source Configuration")
        self.setModal(True)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QFormLayout(self)
        
        # Source type selection
        self.source_type = QComboBox()
        self.source_type.addItem("M3U Playlist", SourceType.M3U)
        self.source_type.addItem("TVHeadend Server", SourceType.TVHEADEND)
        self.source_type.currentIndexChanged.connect(self.on_source_type_changed)
        layout.addRow("Source Type:", self.source_type)
        
        self.name_input = QLineEdit()
        self.url_input = QLineEdit()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        
        # Style placeholder text
        placeholder_color = QColor(100, 100, 100)  # Dark gray color
        palette = self.palette()
        palette.setColor(QPalette.PlaceholderText, placeholder_color)
        self.setPalette(palette)
        
        # Add fields
        layout.addRow("Name:", self.name_input)
        self.name_input.setPlaceholderText("Name")
        layout.addRow("URL:", self.url_input)
        
        # TVHeadend specific fields
        self.tvheadend_widget = QWidget()
        tvheadend_layout = QFormLayout(self.tvheadend_widget)
        tvheadend_layout.addRow("Username:", self.username_input)
        self.username_input.setPlaceholderText("Optional")
        tvheadend_layout.addRow("Password:", self.password_input)
        self.password_input.setPlaceholderText("Optional")
        layout.addRow(self.tvheadend_widget)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Set initial state
        self.on_source_type_changed()
        
    def on_source_type_changed(self):
        source_type = self.source_type.currentData()
        if source_type == SourceType.TVHEADEND:
            self.url_input.setPlaceholderText("http://127.0.0.1:9981")
            self.tvheadend_widget.show()
            self.username_input.setPlaceholderText("TVHeadend username (optional)")
            self.password_input.setPlaceholderText("TVHeadend password (optional)")
        else:  # M3U
            self.url_input.setPlaceholderText("http://example.com/playlist.m3u")
            # Show authentication fields for M3U sources as well
            self.tvheadend_widget.show()
            self.username_input.setPlaceholderText("username")
            self.password_input.setPlaceholderText("password")
        
    def get_server_config(self):
        return {
            'name': self.name_input.text(),
            'url': self.url_input.text(),
            'username': self.username_input.text(),
            'password': self.password_input.text(),
            'type': self.source_type.currentData().value
        }
        
    def set_server_config(self, config):
        source_type = SourceType(config.get('type', SourceType.TVHEADEND.value))
        self.source_type.setCurrentText("TVHeadend Server" if source_type == SourceType.TVHEADEND else "M3U Playlist")
        self.name_input.setText(config.get('name', ''))
        self.url_input.setText(config.get('url', ''))
        self.username_input.setText(config.get('username', ''))
        self.password_input.setText(config.get('password', ''))
        self.on_source_type_changed()

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

class RunningJobsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Running Jobs")
        self.resize(800, 300)  # Start with a larger default size
        self.setup_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(1000)  # Update every second
        
        # Initial update
        self.update_status()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Jobs table
        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(5)
        self.jobs_table.setHorizontalHeaderLabels([
            'Channel',
            'Type',
            'File',
            'Size',
            'Status'
        ])
        
        # Set column resize modes
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Channel
        self.jobs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Type
        self.jobs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)      # File
        self.jobs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Size
        self.jobs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Status
        
        # Set a reasonable width for the File column
        self.jobs_table.setColumnWidth(2, 300)
        
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.jobs_table)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.stop_btn = QPushButton("Stop Selected")
        self.stop_btn.clicked.connect(self.stop_selected)
        btn_layout.addWidget(self.stop_btn)
        
        self.stop_all_btn = QPushButton("Stop All")
        self.stop_all_btn.clicked.connect(self.stop_all)
        btn_layout.addWidget(self.stop_all_btn)
        
        btn_layout.addStretch()
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.update_status)
        btn_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(btn_layout)
        
        # Adjust window size after UI is set up
        QTimer.singleShot(100, self.adjust_window_size)
        
    def adjust_window_size(self):
        """Adjust window size to fit all columns"""
        table_width = self.jobs_table.horizontalHeader().length() + 30  # Add some margin
        table_height = self.jobs_table.verticalHeader().length() + 100  # Add space for buttons
        
        # Get current window size
        current_width = self.width()
        current_height = self.height()
        
        # Set new size, but don't make it smaller than the default
        new_width = max(current_width, table_width)
        new_height = max(current_height, table_height)
        
        # Limit maximum size to screen size
        screen = QApplication.desktop().screenGeometry()
        new_width = min(new_width, screen.width() * 0.8)
        new_height = min(new_height, screen.height() * 0.8)
        
        self.resize(new_width, new_height)
        
    def update_status(self):
        try:
            # Store current selection
            selected_rows = set(item.row() for item in self.jobs_table.selectedItems())
            selected_type = None
            selected_file = None
            if selected_rows:
                row = list(selected_rows)[0]  # Get the first selected row
                type_item = self.jobs_table.item(row, 1)
                file_item = self.jobs_table.item(row, 2)
                if type_item and file_item:
                    selected_type = type_item.text()
                    selected_file = file_item.toolTip()  # Full file path from tooltip
            
            self.jobs_table.setRowCount(0)
            row = 0
            
            # Check for active recordings from parent
            if hasattr(self.parent, 'recordings'):
                for recording in self.parent.recordings:
                    # Skip if process is no longer running
                    if recording['type'] == 'ffmpeg':
                        if 'process' not in recording or recording['process'].poll() is not None:
                            continue
                    
                    self.jobs_table.insertRow(row)
                    
                    # Channel name
                    self.jobs_table.setItem(row, 0, QTableWidgetItem(recording['channel']))
                    
                    # Type
                    self.jobs_table.setItem(row, 1, QTableWidgetItem(recording['type'].upper()))
                    
                    # File
                    if 'file' in recording:
                        file_path = recording['file']
                    elif 'file_path' in recording:
                        file_path = recording['file_path']
                    elif recording['type'] == 'tvheadend' and 'uuid' in recording:
                        # For TVHeadend recordings, use the UUID as the file path
                        file_path = f"TVHeadend Recording UUID: {recording['uuid']}"
                    else:
                        print(f"Debug: No file path or UUID found in recording: {recording}")
                        continue
                    
                    # Truncate long filenames
                    filename = os.path.basename(file_path) if os.path.basename(file_path) else file_path
                    if len(filename) > 40:  # Truncate if longer than 40 characters
                        truncated_name = filename[:18] + "..." + filename[-18:]
                    else:
                        truncated_name = filename
                        
                    file_item = QTableWidgetItem(truncated_name)
                    file_item.setToolTip(file_path)  # Show full path on hover
                    self.jobs_table.setItem(row, 2, file_item)
                    
                    # Size
                    try:
                        if recording['type'] == 'tvheadend':
                            # TVHeadend recordings don't have a local file to measure
                            size_str = "N/A (TVHeadend)"
                        elif os.path.exists(file_path):
                            size = os.path.getsize(file_path)
                            size_str = self.format_size(size)
                        else:
                            size_str = "0 B"
                    except Exception as e:
                        print(f"Debug: Error getting file size: {str(e)}")
                        size_str = "0 B"
                    self.jobs_table.setItem(row, 3, QTableWidgetItem(size_str))
                    
                    # Status
                    self.jobs_table.setItem(row, 4, QTableWidgetItem("Recording"))
                    
                    # Restore selection if this was the selected row
                    if selected_type and selected_file:
                        current_type = recording['type'].upper()
                        current_file = file_path
                        if current_type == selected_type and current_file == selected_file:
                            self.jobs_table.selectRow(row)
                    
                    row += 1
            
            # Adjust window size after updating content
            if row > 0:
                self.adjust_window_size()
                
            # Enable/disable buttons based on row count
            has_jobs = self.jobs_table.rowCount() > 0
            self.stop_btn.setEnabled(has_jobs)
            self.stop_all_btn.setEnabled(has_jobs)
            
            # Display a message if there are no active recordings
            if not has_jobs:
                # Add a single row with a message
                self.jobs_table.insertRow(0)
                no_jobs_item = QTableWidgetItem("No active recordings")
                no_jobs_item.setTextAlignment(Qt.AlignCenter)
                # Create a font for the message
                font = no_jobs_item.font()
                font.setItalic(True)
                no_jobs_item.setFont(font)
                # Span all columns
                self.jobs_table.setSpan(0, 0, 1, 5)
                self.jobs_table.setItem(0, 0, no_jobs_item)
                
        except Exception as e:
            print(f"Debug: Error updating job status: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            
            # Clean up if we encounter an error
            if hasattr(self.parent, 'recordings'):
                # Remove any recordings with dead processes
                for recording in self.parent.recordings[:]:  # Create a copy to iterate
                    if recording['type'] == 'ffmpeg':
                        if 'process' not in recording or recording['process'].poll() is not None:
                            self.parent.recordings.remove(recording)
                
    
    def format_size(self, size):
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def stop_selected(self):
        """Stop the selected recording"""
        selected_items = self.jobs_table.selectedItems()
        if not selected_items:
            return
            
        row = selected_items[0].row()
        self.stop_job(row)
        
    def stop_all(self):
        """Stop all recordings"""
        row_count = self.jobs_table.rowCount()
        for row in range(row_count):
            self.stop_job(row)
            
    def stop_job(self, row):
        """Stop a specific recording job"""
        try:
            type_item = self.jobs_table.item(row, 1)
            file_item = self.jobs_table.item(row, 2)
            if not type_item or not file_item:
                return
                
            recording_type = type_item.text().lower()
            file_path = file_item.toolTip()  # Get full path from tooltip
            
            # For TVHeadend recordings, extract the UUID from the file path
            uuid = None
            if recording_type == 'tvheadend' and 'TVHeadend Recording UUID:' in file_path:
                uuid = file_path.split('TVHeadend Recording UUID:')[1].strip()
                print(f"Debug: Extracted UUID for TVHeadend recording: {uuid}")
            
            # Find and stop the matching recording
            for recording in self.parent.recordings[:]:  # Create a copy to iterate
                # For TVHeadend recordings, match by UUID
                if recording_type == 'tvheadend' and uuid and recording.get('type') == 'tvheadend':
                    if recording.get('uuid') == uuid:
                        print(f"Debug: Found TVHeadend recording to stop by UUID: {uuid}")
                        
                        # Create a status item to show the stopping status
                        status_item = self.jobs_table.item(row, 4)
                        if status_item:
                            status_item.setText("Stopping...")
                            QApplication.processEvents()  # Update the UI
                        
                        # Stop TVHeadend recording via API
                        try:
                            # Pass the UUID to stop the specific recording
                            self.parent.stop_recording(uuid=uuid)
                            
                            # If we get here, the recording was successfully stopped
                            if recording in self.parent.recordings:
                                self.parent.recordings.remove(recording)
                            else:
                                print(f"Debug: Recording not in list, may have been already removed")
                            
                            # Close the recording status dialog if it exists
                            if hasattr(self.parent, 'recording_dialog') and self.parent.recording_dialog:
                                print("Debug: Closing recording status dialog")
                                self.parent.recording_dialog.close()
                                self.parent.recording_dialog = None
                        except Exception as e:
                            print(f"Debug: Error stopping TVHeadend recording: {str(e)}")
                            
                            # Update the status item to show the error
                            if status_item:
                                status_item.setText("Error: Server unreachable")
                                # Make the text red to indicate an error
                                status_item.setForeground(QBrush(QColor("red")))
                            
                            # Don't remove the recording from the list since we couldn't confirm it was stopped
                        
                        break
                    continue
                
                # For other recording types, match by file path
                recording_file = None
                if 'file' in recording:
                    recording_file = recording['file']
                elif 'file_path' in recording:
                    recording_file = recording['file_path']
                
                if recording_file is None:
                    print(f"Debug: No file path found in recording: {recording}")
                    continue
                    
                if recording['type'] == recording_type and recording_file == file_path:
                    print(f"Debug: Found recording to stop: {recording_file}")
                    
                    # Create a status item to show the stopping status
                    status_item = self.jobs_table.item(row, 4)
                    if status_item:
                        status_item.setText("Stopping...")
                        QApplication.processEvents()  # Update the UI
                    
                    try:
                        if recording_type == 'ffmpeg' and 'process' in recording:
                            # Stop local ffmpeg recording
                            recording['process'].terminate()
                            recording['process'].wait()
                            if recording in self.parent.recordings:
                                self.parent.recordings.remove(recording)
                            else:
                                print(f"Debug: Recording not in list, may have been already removed")
                        elif recording_type == 'local':
                            # Stop local VLC recording
                            self.parent.stop_local_recording()
                            if recording in self.parent.recordings:
                                self.parent.recordings.remove(recording)
                            else:
                                print(f"Debug: Recording not in list, may have been already removed")
                        
                        # Close the recording status dialog if it exists
                        if hasattr(self.parent, 'recording_dialog') and self.parent.recording_dialog:
                            print("Debug: Closing recording status dialog")
                            self.parent.recording_dialog.close()
                            self.parent.recording_dialog = None
                    except Exception as e:
                        print(f"Debug: Error stopping recording: {str(e)}")
                        
                        # Update the status item to show the error
                        if status_item:
                            status_item.setText("Error: Failed to stop")
                            # Make the text red to indicate an error
                            status_item.setForeground(QBrush(QColor("red")))
                        
                        # Don't remove the recording from the list since we couldn't confirm it was stopped
                    
                    break
            else:
                print(f"Debug: No matching recording found for path: {file_path}")
            
            # Stop recording indicator if no recordings are left
            if not self.parent.recordings:
                self.parent.stop_recording_indicator()
                
        except Exception as e:
            print(f"Debug: Error stopping job: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            
            # Try to clean up even if there was an error
            if not self.parent.recordings:
                self.parent.stop_recording_indicator()

    def closeEvent(self, event):
        """Handle dialog close event"""
        if self.update_timer:
            self.update_timer.stop()
        super().closeEvent(event)

class TVHeadendClient(QMainWindow):
    def __init__(self):
        """Initialize TVHeadend client"""
        super().__init__()
        
        # Set window title and geometry from config
        self.setWindowTitle("TVHplayer")
        
        # Initialize logger
        self.logger = Logger("TVHeadendClient")
        self.logger.debug("Initializing TVHeadendClient")
        
        # Initialize recording tracking
        self.recordings = []  # List to track multiple recordings
        
        # Initialize VLC instance
        self.logger.debug("Initializing VLC instance")
        
        print("Debug: Initializing TVHeadendClient")
        
        # Initialize VLC instance
        print("Debug: Initializing VLC instance")
        self.vlc_instance = vlc.Instance()
        print("Debug: VLC instance created successfully with hardware acceleration")
        
        # Create VLC media player
        self.media_player = self.vlc_instance.media_player_new()
        print("Debug: VLC media player created successfully")
        
        # Set up event manager for media player
        self.event_manager = self.media_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self.on_media_playing)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self.on_media_error)
        
        # Initialize OSD
        self.setup_osd()
        
        # Initialize fullscreen state
        self.is_fullscreen = False
        self.fullscreen_toggle_time = 0  # Track last toggle time for debounce
        
        self.setup_paths()
        
        # Get OS-specific config path using sys.platform
        if sys.platform == 'darwin':  # macOS
            self.config_dir = os.path.join(os.path.expanduser('~/Library/Application Support'), 'TVHplayer')
        elif sys.platform == 'win32':  # Windows
            self.config_dir = os.path.join(os.getenv('APPDATA'), 'TVHplayer')
        else:  # Linux/Unix
            CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            self.config_dir = os.path.join(CONFIG_HOME, "tvhplayer")
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Set config file path
        self.config_file = os.path.join(self.config_dir, 'tvhplayer.conf')
        print(f"Debug: Config file location: {self.config_file}")
        self.config = self.load_config()
        print(f"Debug: Current config: {json.dumps(self.config, indent=2)}")
        
        # Set window geometry from config
        geometry = self.config.get('window_geometry', {'x': 100, 'y': 100, 'width': 1200, 'height': 700})
        self.setGeometry(
            geometry['x'],
            geometry['y'],
            geometry['width'],
            geometry['height']
        )
        
        # Initialize servers from config
        self.servers = self.config.get('servers', [])
        
        # Initialize recording-related attributes
        self.local_recording_process = None
        self.recording_check_timer = None
        self.recording_status_dialog = None
        
        # Then setup UI
        self.setup_ui()
        
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
            # else:
            #     # Alternative method for older VLC Python bindings
            #     self.media_player.video_set_key_input(False)
            #     self.media_player.video_set_mouse_input(False)
            
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
        controls_menu = menubar.addMenu("Controls")
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
        fullscreen_action = QAction("Fullscreen", self)
        fullscreen_action.setShortcut("F")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)
        
        # Add Next/Previous Channel actions to Controls menu
        next_channel_action = QAction("Next Channel", self)
        if sys.platform == "darwin":  # macOS
            next_channel_action.setShortcuts(["Cmd+N", "Right"])
        else:  # Windows/Linux
            next_channel_action.setShortcuts(["Ctrl+N", "Right"])
        next_channel_action.triggered.connect(self.play_next_channel)
        controls_menu.addAction(next_channel_action)
        
        prev_channel_action = QAction("Previous Channel", self)
        if sys.platform == "darwin":  # macOS
            prev_channel_action.setShortcuts(["Cmd+P", "Left"])
        else:  # Windows/Linux
            prev_channel_action.setShortcuts(["Ctrl+P", "Left"])
        prev_channel_action.triggered.connect(self.play_previous_channel)
        controls_menu.addAction(prev_channel_action)
        
        # Add Play/Pause action to Controls menu
        play_pause_action = QAction("Play/Pause", self)
        play_pause_action.setShortcut("Space")
        play_pause_action.triggered.connect(self.toggle_play_pause)
        controls_menu.addAction(play_pause_action)

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
        manage_servers_btn.setText("⚙")  # Unicode settings icon
        manage_servers_btn.setStyleSheet("font-size: 14px;")  # Make icon bigger
        manage_servers_btn.setToolTip("Manage servers")
        server_layout.addWidget(manage_servers_btn)
        left_layout.addLayout(server_layout)
        
        # Profile selection for TVHeadend sources
        self.profile_frame = QFrame()
        profile_layout = QHBoxLayout(self.profile_frame)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.profile_combo.addItem("Default", "")  # Default option with empty value
        profile_layout.addWidget(self.profile_combo)
        left_layout.addWidget(self.profile_frame)
        # Hide profile selection by default, will show only for TVHeadend sources
        self.profile_frame.setVisible(False)
        
        # Connect profile combo box change signal
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
    
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
        self.video_frame.setFocusPolicy(Qt.StrongFocus)  # Ensure video frame can receive keyboard focus
        
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
            else self.channel_list.item(0, 1).data(Qt.UserRole) if self.channel_list.rowCount() > 0 
            else None))
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
        self.record_frame = QFrame()
        self.record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        self.record_frame.setWindowTitle("Recording")
        self.record_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.record_frame.setLineWidth(5)  # Make frame thicker
        record_layout = QHBoxLayout(self.record_frame)
        
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
        self.stop_record_btn.clicked.connect(self.show_recording_jobs)
        record_layout.addWidget(self.stop_record_btn)
        
        controls_layout.addWidget(self.record_frame)
        
        # Create frame for local record buttons
        self.local_record_frame = QFrame()
        self.local_record_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}");
        self.local_record_frame.setWindowTitle("Local Recording")
        self.local_record_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        local_record_layout = QHBoxLayout(self.local_record_frame)

        # Start Local Record button
        self.start_local_record_btn = QPushButton()
        self.start_local_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.start_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/reclocal.svg"))
        self.start_local_record_btn.setIconSize(QSize(48, 48))
        self.start_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_local_record_btn.setToolTip("Start Local Recording")
        self.start_local_record_btn.clicked.connect(
            lambda: self.start_local_recording(
                self.channel_list.currentItem().text() if self.channel_list.currentItem() else None
            ))
        local_record_layout.addWidget(self.start_local_record_btn)

        # Stop Local Record button
        self.stop_local_record_btn = QPushButton()
        self.stop_local_record_btn.setFixedSize(48, 48)  # Remove extra parenthesis
        self.stop_local_record_btn.setIcon(QIcon(f"{self.icons_dir}/stopreclocal.svg"))
        self.stop_local_record_btn.setIconSize(QSize(48, 48))
        self.stop_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_local_record_btn.setToolTip("Stop Local Recording")
        self.stop_local_record_btn.clicked.connect(self.show_running_jobs)
        local_record_layout.addWidget(self.stop_local_record_btn)

        controls_layout.addWidget(self.local_record_frame)

        # Create frame for EPG button
        self.epg_frame = QFrame()
        self.epg_frame.setStyleSheet(".QFrame{border: 1px solid grey; border-radius: 8px;}")
        self.epg_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        epg_layout = QHBoxLayout(self.epg_frame)

        # EPG button
        self.epg_btn = QPushButton()
        self.epg_btn.setFixedSize(48, 48)
        self.epg_btn.setIcon(QIcon(f"{self.icons_dir}/epg.svg"))
        self.epg_btn.setIconSize(QSize(48, 48))
        self.epg_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.epg_btn.setToolTip("Show Electronic Program Guide")
        self.epg_btn.clicked.connect(self.show_epg)
        epg_layout.addWidget(self.epg_btn)

        controls_layout.addWidget(self.epg_frame)

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

        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(150)  # Set fixed width to make slider less wide
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        
        # Fullscreen button with icon
        fullscreen_btn = QPushButton()
        fullscreen_btn.setIcon(QIcon(f"{self.icons_dir}/fullscreen.svg"))
        fullscreen_btn.setIconSize(QSize(32, 32))
        fullscreen_btn.setFixedSize(32, 32)  # Remove extra parenthesis
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
        self.fetch_streaming_profiles()
        
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
        
        # Add Running Jobs to View menu
        running_jobs_action = QAction("Running Jobs", self)
        running_jobs_action.setStatusTip("Show running recording jobs")
        running_jobs_action.triggered.connect(self.show_running_jobs)
        view_menu.addAction(running_jobs_action)
        
        # Add search box before styling it
        search_layout = QHBoxLayout()
        search_icon = QLabel("🔍")  # Unicode search icon
        self.search_box = QLineEdit()
        
        # Style placeholder text
        placeholder_color = QColor(100, 100, 100)  # Dark gray color
        search_palette = self.search_box.palette()
        search_palette.setColor(QPalette.PlaceholderText, placeholder_color)
        self.search_box.setPalette(search_palette)
        
        self.search_box.setPlaceholderText("Press S to search channels...")
        self.search_box.textChanged.connect(self.filter_channels)
        self.search_box.setClearButtonEnabled(True)  # Add clear button inside search box
        
        # Add S shortcut for search box
        search_shortcut = QShortcut(QKeySequence(Qt.Key_S, Qt.NoModifier), self)
        search_shortcut.activated.connect(self.search_box.setFocus)
        
        # Add global space shortcut for play/pause
        # space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        # space_shortcut.activated.connect(self.toggle_play_pause)
        
        # Add global shortcuts for next/previous channel
        # if sys.platform == "darwin":  # macOS
        #     next_channel_shortcut = QShortcut(QKeySequence("Cmd+N"), self)
        #     prev_channel_shortcut = QShortcut(QKeySequence("Cmd+P"), self)
        # else:  # Windows/Linux
        #     next_channel_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        #     prev_channel_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        
        # next_channel_shortcut.activated.connect(self.play_next_channel)
        # prev_channel_shortcut.activated.connect(self.play_previous_channel)
        
        # Create custom clear button action
        clear_action = QAction("⌫", self.search_box)
        self.search_box.addAction(clear_action, QLineEdit.TrailingPosition)
        
        search_layout.addWidget(search_icon)
        search_layout.addWidget(self.search_box)
        left_layout.addLayout(search_layout)  # Add to left pane layout
        
        # Now style the search box with custom clear button styling
        
        
        # Add margins to search layout
        search_layout.setContentsMargins(0, 5, 0, 5)
        search_layout.setSpacing(5)
        
        # Add EPG action to View menu
        epg_action = QAction("Program Guide (EPG)", self)
        epg_action.setShortcut("Ctrl+E")
        epg_action.triggered.connect(self.show_epg)
        view_menu.addAction(epg_action)
        
        # Create control buttons
        control_layout = QHBoxLayout()
        
        # ... existing control buttons ...
        
        
        
        # ... rest of the layout setup ...
        
        # Add control layout to the main layout
        right_layout.addLayout(control_layout)
        
        # ... rest of the existing code ...
    
    def fetch_channels(self):
        """Fetch channels from the selected server"""
        try:
            # Clear existing channels
            self.channel_list.setRowCount(0)
            
            # Get current server
            server_index = self.server_combo.currentIndex()
            if server_index < 0 or server_index >= len(self.servers):
                print("Debug: Invalid server index")
                return
                
            server = self.servers[server_index]
            print(f"Debug: Fetching channels from server: {server['name']}")
            
            # Get server URL and ensure it has http:// prefix
            base_url = server['url']
            if not base_url.startswith(('http://', 'https://')):
                base_url = f"http://{base_url}"
                
            # Get source type
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            print(f"Debug: Source type: {source_type}")
            
            # Show/hide recording buttons based on source type
            if source_type == SourceType.M3U:
                # For M3U sources, hide TVHeadend recording buttons and show local recording buttons
                print("Debug: M3U source detected, showing only local recording buttons")
                if hasattr(self, 'record_frame'):
                    self.record_frame.hide()
                if hasattr(self, 'local_record_frame'):
                    self.local_record_frame.show()
                    
                # Connect the main record button to local recording for M3U sources
                if hasattr(self, 'record_btn'):
                    self.record_btn.triggered.disconnect()
                    self.record_btn.triggered.connect(
                        lambda: self.start_local_recording(
                            self.channel_list.currentItem().text() if self.channel_list.currentItem() else None
                        ))
            else:
                # For TVHeadend sources, show both recording options
                print("Debug: TVHeadend source detected, showing all recording buttons")
                if hasattr(self, 'record_frame'):
                    self.record_frame.show()
                if hasattr(self, 'local_record_frame'):
                    self.local_record_frame.show()
                    
                # Connect the main record button to TVHeadend recording for TVHeadend sources
                if hasattr(self, 'record_btn'):
                    try:
                        self.record_btn.triggered.disconnect()
                    except TypeError:
                        # If not connected, ignore the error
                        pass
                    self.record_btn.triggered.connect(self.start_recording)
            
            # Initialize channel data list
            channel_data = []
            
            if source_type == SourceType.TVHEADEND:
                # Fetch channels from TVHeadend server
                api_url = f'{base_url}/api/channel/grid?limit=10000'
                print(f"Debug: Making request to: {api_url}")
                
                # Create auth tuple if credentials exist
                auth = None
                if server.get('username') or server.get('password'):
                    auth = (server.get('username', ''), server.get('password', ''))
                    print(f"Debug: Using authentication with username: {server.get('username', '')}")
                
                # Make request to TVHeadend API
                response = requests.get(api_url, auth=auth)
                print(f"Debug: Response status: {response.status_code}")
                
                if response.status_code == 200:
                    channels = response.json()['entries']
                    print(f"Debug: Found {len(channels)} channels")
                    
                    # Sort channels by number
                    channels.sort(key=lambda x: x.get('number', 0))
                    
                    # Add channels to list
                    for channel in channels:
                        try:
                            channel_name = channel.get('name', 'Unknown Channel')
                            channel_number = channel.get('number', 0)
                            
                            channel_data.append({
                                'number': channel_number,
                                'name': channel_name,
                                'uuid': channel.get('uuid'),
                                'icon': channel.get('icon_public_url'),
                                'type': 'tvheadend',
                                'data': {
                                    'name': channel_name,
                                    'uuid': channel.get('uuid'),
                                    'icon': channel.get('icon_public_url')
                                }
                            })
                        except Exception as e:
                            print(f"Debug: Error processing channel: {str(e)}")
                            continue
                        
            else:  # M3U source
                try:
                    # Fetch M3U playlist
                    headers = {}
                    auth = None
                    
                    # Check if credentials exist for M3U source
                    if server.get('username') or server.get('password'):
                        username = server.get('username', '')
                        password = server.get('password', '')
                        print(f"Debug: Using authentication for M3U source with username: {username}")
                        
                        # Try different authentication methods
                        # 1. Basic Auth
                        auth = (username, password)
                        
                        # 2. Add Authorization header
                        auth_string = f"{username}:{password}"
                        encoded_auth = base64.b64encode(auth_string.encode()).decode()
                        headers['Authorization'] = f"Basic {encoded_auth}"
                    
                    # Make request with auth and headers
                    response = requests.get(base_url, auth=auth, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        # Pass authentication credentials to parse_m3u for stream URLs
                        channels = parse_m3u(response.text, username=server.get('username', ''), 
                                            password=server.get('password', ''))
                        print(f"Debug: Found {len(channels)} channels in M3U playlist")
                        
                        # Process M3U channels
                        for idx, channel in enumerate(channels):
                            try:
                                channel_name = channel['name']
                                channel_number = idx + 1
                                
                                channel_data.append({
                                    'number': channel_number,
                                    'name': channel_name,
                                    'data': {
                                        'name': channel_name,
                                        'uri': channel['uri'],
                                        'attributes': channel.get('attributes', {})
                                    },
                                    'type': 'm3u'
                                })
                            except Exception as e:
                                print(f"Debug: Error processing M3U channel {idx}: {str(e)}")
                                continue
                    else:
                        raise Exception(f"Failed to fetch M3U playlist: {response.status_code}")
                except Exception as e:
                    print(f"Debug: Error processing M3U playlist: {str(e)}")
                    raise
            
            print(f"Debug: Found {len(channel_data)} channels")
            
            # Sort channels by number, then name
            channel_data.sort(key=lambda x: (x['number'] or float('inf'), x['name'].lower()))
            
            # Clear existing items
            self.channel_list.setRowCount(0)
            
            # Initialize channel verification list
            channel_verification = []
            
            # Add sorted channels to the table
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
            print(f"Original channel count: {len(channel_data)}")
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
        """Start recording current channel"""
        try:
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            # Get current channel name and data
            current_row = self.channel_list.currentRow()
            if current_row < 0:
                print("Debug: No channel selected")
                return
                
            name_item = self.channel_list.item(current_row, 1)
            if not name_item:
                print("Debug: No channel item found")
                return
                
            channel_name = name_item.text()
            channel_data = name_item.data(Qt.UserRole)
            if not channel_data:
                print("Debug: No channel data found")
                return
            
            # Handle recording based on source type
            if source_type == SourceType.TVHEADEND:
                # Get channel UUID directly from channel data
                channel_uuid = channel_data.get('uuid')
                if not channel_uuid:
                    print(f"Debug: Channel UUID not found for: {channel_name}")
                    self.statusbar.showMessage("Channel not found")
                    return
                
                # Show duration dialog
                duration_dialog = RecordingDurationDialog(self)
                if duration_dialog.exec_() != QDialog.Accepted:
                    return
                
                hours, minutes = duration_dialog.get_duration()
                
                # Calculate start and stop timestamps
                start_time = int(time.time())
                duration_seconds = (hours * 3600) + (minutes * 60)
                stop_time = start_time + duration_seconds

                # Create auth if needed
                auth = None
                if server.get('username') or server.get('password'):
                    auth = (server.get('username', ''), server.get('password', ''))

                # Prepare recording request with proper language object structure
                conf_data = {
                    "start": start_time,
                    "stop": stop_time,
                    "channel": channel_uuid,
                    "title": {
                        "eng": f"Manual Recording - {channel_name}"
                    },
                    "subtitle": {
                        "eng": f"Started at {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    },
                    "comment": "Started via TVHplayer"
                }

                # Convert to string format as expected by the API
                data = {'conf': json.dumps(conf_data)}
                print(f"Debug: Starting TVHeadend recording: {conf_data}")

                # Make recording request
                record_url = f'{server["url"]}/api/dvr/entry/create'
                response = requests.post(record_url, data=data, auth=auth)

                if response.status_code == 200:
                    self.statusbar.showMessage(f"Recording started for {channel_name}")
                    # Add recording to the list
                    recording_uuid = response.json().get('uuid')
                    if recording_uuid:
                        self.recordings.append({
                            'type': 'tvheadend',
                            'uuid': recording_uuid,
                            'channel': channel_name,
                            'start_time': time.time()
                        })
                        print(f"Debug: Added recording to list: {recording_uuid}")
                    self.start_recording_indicator()
                else:
                    print(f"Debug: Failed to start TVHeadend recording: {response.text}")
                    self.statusbar.showMessage("Failed to start recording")
                    return

            else:  # M3U source
                self.start_local_recording(channel_name)

        except Exception as e:
            print(f"Debug: Error starting recording: {str(e)}")
            self.statusbar.showMessage("Error starting recording")

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
        """Play a channel using its data"""
        try:
            print(f"Debug: Playing channel: {channel_data.get('name', 'Unknown')}")
            print(f"Debug: Channel data: {channel_data}")  # Add this to see the full channel data
            
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            # Construct proper URL based on source type
            url = None
            if source_type == SourceType.TVHEADEND:
                # Construct TVHeadend stream URL
                base_url = server['url']
                if not base_url.startswith(('http://', 'https://')):
                    base_url = f"http://{base_url}"
                
                url = f"{base_url}/stream/channel/{channel_data['uuid']}"
                
                # Add selected profile if available
                selected_profile = self.profile_combo.currentData()
                if selected_profile:
                    url = f"{url}?profile={selected_profile}"
                    print(f"Debug: Using streaming profile: {selected_profile}")
                
                # Add authentication if needed
                if server.get('username') or server.get('password'):
                    username = server.get('username', '')
                    password = server.get('password', '')
                    print(f"Debug: Adding TVHeadend authentication to playback URL")
                    # Add auth to URL for VLC
                    url = url.replace('://', f'://{username}:{password}@')
            elif source_type == SourceType.M3U:
                # For M3U sources, the URL is stored directly in the channel data
                url = channel_data.get('uri')  # FIXED: Changed 'url' to 'uri'
                
                # Add authentication if needed
                if server.get('username') or server.get('password'):
                    username = server.get('username', '')
                    password = server.get('password', '')
                    print(f"Debug: Adding M3U authentication to playback URL")
                    # Add auth to URL for VLC
                    url = url.replace('://', f'://{username}:{password}@')
            
            # Handle relative URLs for M3U sources
            if url and not url.startswith(('http://', 'https://')):
                base_url = server['url']
                base_dir = '/'.join(base_url.split('/')[:-1])
                url = f"{base_dir}/{url}"
            
            if not url:
                print(f"Debug: No URL found for channel: {channel_data.get('name', 'Unknown')}")
                self.statusbar.showMessage(f"⚠ Error: No URL for {channel_data.get('name', 'Unknown')}")
                return
                
            print(f"Debug: Playing URL: {url}")
            
            # Create a new media instance
            media = self.vlc_instance.media_new(url)
            
            # Set the media to the player
            self.media_player.set_media(media)
            
            # Play the media
            self.media_player.play()
            
            # Set up playback timeout timer
            self.playback_timeout_timer = QTimer()
            self.playback_timeout_timer.setSingleShot(True)
            self.playback_timeout_timer.timeout.connect(lambda: self.handle_playback_timeout(channel_data))
            self.playback_timeout_timer.start(15000)  # 15 second timeout
            
            # Update current channel
            self.current_channel = channel_data
            self.statusbar.showMessage(f"▶ Playing: {channel_data.get('name', 'Unknown')}")
            
            # Show channel name in OSD
            self.show_osd_message(f"Now playing: {channel_data.get('name', 'Unknown')}")
            
        except Exception as e:
            print(f"Debug: Error in play_channel: {str(e)}")
            self.statusbar.showMessage(f"⚠ Error playing channel: {str(e)}")
            
    def handle_playback_timeout(self, channel_data):
        """Handle playback timeout when a channel fails to play"""
        # Check if playback has started successfully
        state = self.media_player.get_state()
        print(f"Debug: Playback state after timeout: {state}")
        
        if state not in [vlc.State.Playing, vlc.State.Paused]:
            print(f"Debug: Playback failed to start for channel: {channel_data.get('name', 'Unknown')}")
            # Stop the failed playback attempt
            self.media_player.stop()
            self.statusbar.showMessage(f"⚠ Playback timeout: Failed to play {channel_data.get('name', 'Unknown')}")
            # Show OSD message
            self.show_osd_message(f"Playback timeout: Failed to play {channel_data.get('name', 'Unknown')}", 5000)

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
            
            
            
        except Exception as e:
            print(f"Error checking hardware acceleration: {e}")
            print(f"Traceback: {traceback.format_exc()}")

    def show_running_jobs(self):
        """Show the running jobs dialog"""
        try:
            dialog = RunningJobsDialog(self)
            dialog.show()
        except Exception as e:
            print(f"Debug: Error showing running jobs dialog: {str(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage("Error showing running jobs")

    def get_save_path(self, channel_name):
        """Get save path for recording from user"""
        try:
            # Create default filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"recording_{channel_name}_{timestamp}.ts"  # Using .ts format initially
            
            # Show file save dialog
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Recording As",
                os.path.join(self.config_dir, 'recordings', default_filename),
                "TS Files (*.ts);;MP4 Files (*.mp4);;All Files (*.*)"
            )
            
            if not file_path:  # User cancelled
                print("Debug: Recording cancelled - no file selected")
                return None
                
            # Ensure recordings directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            return file_path
            
        except Exception as e:
            print(f"Debug: Error getting save path: {str(e)}")
            self.statusbar.showMessage(f"Error getting save path: {str(e)}")
            return None

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
                    'servers': []
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
            'servers': []
        }
        
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
                
            print(f"Debug: Opened user guide URL: {url}")
            
        except Exception as e:
            print(f"Debug: Error opening user guide URL: {str(e)}")
            QMessageBox.critical(
                self, 
                "Error",
                f"Failed to open user guide: {str(e)}",
                QMessageBox.Ok
            )

    def show_about(self):
        """Show about dialog with application information"""
        about_text = (
            "<div style='text-align: center;'>"
            "<h2>TVHplayer</h2>"
            "<p>Version 4.0.0</p>"
            "<p>A modern TVHeadend client for watching and recording TV.</p>"
            "<p>Copyright © 2023</p>"
            "<p>This program is free software: you can redistribute it and/or modify "
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
    
    def eventFilter(self, obj, event):
        """Handle double-click and key events"""
        if obj == self.video_frame:
            if event.type() == event.MouseButtonDblClick:
                print("Debug: Double click detected on video frame")
                self.toggle_fullscreen()
                return True
            elif event.type() == event.MouseMove:
                # Show channel info on mouse movement if a channel is playing
                if hasattr(self, 'current_channel') and self.current_channel:
                    channel_name = self.current_channel.get('name', 'Unknown')
                    self.show_osd_message(f"Channel: {channel_name}", 2000)
                return False  # Continue event propagation
            
        # Handle key events for both main window and fullscreen window
        if event.type() == event.KeyPress:
            print(f"Debug: Key press detected: {event.key()}, modifiers: {event.modifiers()}")
            
            # Handle Alt+F4 to close the entire application
            if event.key() == Qt.Key_F4 and (event.modifiers() & Qt.AltModifier):
                print("Debug: Alt+F4 detected - closing application")
                self.close()  # Close the main window, which will exit the application
                return True
            
            if event.key() == Qt.Key_Escape and self.is_fullscreen:
                print("Debug: Escape key pressed in fullscreen mode")
                self.toggle_fullscreen()
                return True
            elif event.key() == Qt.Key_F:
                print("Debug: F key pressed")
                self.toggle_fullscreen()
                return True
            elif event.key() == Qt.Key_Space:
                # Toggle pause/play
                if self.media_player.is_playing():
                    self.media_player.pause()
                    self.show_osd_message("Paused")
                else:
                    self.media_player.play()
                    self.show_osd_message("Playing")
                return True
            elif event.key() == Qt.Key_P and (event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
                # Previous channel (Ctrl+P or Cmd+P)
                self.play_previous_channel()
                return True
            elif event.key() == Qt.Key_N and (event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
                # Next channel (Ctrl+N or Cmd+N)
                print("Debug: Ctrl+N pressed for next channel")
                self.play_next_channel()
                return True
            elif event.key() == Qt.Key_Right:
                # Next channel (Right arrow)
                print("Debug: Right arrow pressed for next channel")
                self.play_next_channel()
                return True
            elif event.key() == Qt.Key_Left:
                # Previous channel (Left arrow)
                print("Debug: Left arrow pressed for previous channel")
                self.play_previous_channel()
                return True
            
        return super().eventFilter(obj, event)

    def toggle_fullscreen(self):
        """Toggle fullscreen mode for VLC player"""
        print(f"Debug: Toggling fullscreen. Current state: {self.is_fullscreen}")
        
        # Debounce mechanism to prevent rapid toggling
        current_time = time.time()
        if current_time - self.fullscreen_toggle_time < 0.5:  # 500ms debounce
            print("Debug: Ignoring rapid fullscreen toggle")
            return
        self.fullscreen_toggle_time = current_time
        
        try:
            if not self.is_fullscreen:
                # Store the video frame's original parent and layout position
                self.original_parent = self.video_frame.parent()
                self.original_layout = self.findChild(QVBoxLayout, "right_layout")
                
                # Create a new fullscreen window
                self.fullscreen_window = QWidget()
                self.fullscreen_window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
                self.fullscreen_window.installEventFilter(self)
                self.fullscreen_window.setFocusPolicy(Qt.StrongFocus)  # Ensure window can receive keyboard focus
                
                # Override the closeEvent to exit fullscreen mode instead of closing the application
                def fullscreen_close_event(event):
                    print("Debug: Fullscreen window close event - exiting fullscreen mode")
                    event.ignore()  # Ignore the close event
                    self.toggle_fullscreen()  # Exit fullscreen mode instead
                
                self.fullscreen_window.closeEvent = fullscreen_close_event
                
                # Add global shortcuts to fullscreen window
                space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self.fullscreen_window)
                space_shortcut.activated.connect(self.toggle_play_pause)
                
                if sys.platform == "darwin":  # macOS
                    next_channel_shortcut = QShortcut(QKeySequence("Cmd+N"), self.fullscreen_window)
                    prev_channel_shortcut = QShortcut(QKeySequence("Cmd+P"), self.fullscreen_window)
                else:  # Windows/Linux
                    next_channel_shortcut = QShortcut(QKeySequence("Ctrl+N"), self.fullscreen_window)
                    prev_channel_shortcut = QShortcut(QKeySequence("Ctrl+P"), self.fullscreen_window)
                
                next_channel_shortcut.activated.connect(self.play_next_channel)
                prev_channel_shortcut.activated.connect(self.play_previous_channel)
                
                layout = QVBoxLayout(self.fullscreen_window)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)  # Remove spacing between widgets
                
                # Move video frame to fullscreen
                self.video_frame.setParent(self.fullscreen_window)
                layout.addWidget(self.video_frame)
                
                # Update state before showing the window
                self.is_fullscreen = True
                
                # Show OSD message for fullscreen
                self.show_osd_message("Fullscreen mode")
                
                # Show fullscreen
                QApplication.processEvents()  # Process any pending events
                self.fullscreen_window.showFullScreen()
                self.video_frame.show()
                self.fullscreen_window.setFocus()  # Ensure window has focus to receive keyboard events
                
                # Reset VLC window handle for fullscreen
                if sys.platform.startswith('linux'):
                    QApplication.processEvents()  # Give X11 time to update
                    self.media_player.set_xwindow(self.video_frame.winId().__int__())
                elif sys.platform == "win32":
                    self.media_player.set_hwnd(self.video_frame.winId().__int__())
                elif sys.platform == "darwin":
                    self.media_player.set_nsobject(self.video_frame.winId().__int__())
            else:
                # Remove from fullscreen layout
                if hasattr(self, 'fullscreen_window') and self.fullscreen_window:
                    if self.fullscreen_window.layout():
                        self.fullscreen_window.layout().removeWidget(self.video_frame)
                    
                    # Find the right pane's layout again
                    right_layout = self.findChild(QVBoxLayout, "right_layout")
                    if right_layout:
                        # Restore to right pane
                        self.video_frame.setParent(self.original_parent)
                        right_layout.insertWidget(0, self.video_frame)
                        QApplication.processEvents()  # Process any pending events
                        self.video_frame.show()
                        
                        # Check if media player exists, create it if it doesn't
                        if not hasattr(self, 'media_player') or self.media_player is None:
                            print("Debug: Media player is absent, creating a new one")
                            self.vlc_instance = vlc.Instance()
                            self.media_player = self.vlc_instance.media_player_new()
                            self.event_manager = self.media_player.event_manager()
                            self.event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self.on_media_playing)
                            self.event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self.on_media_error)
                        
                        # Reset VLC window handle for normal view
                        if sys.platform.startswith('linux'):
                            QApplication.processEvents()  # Give X11 time to update
                            self.media_player.set_xwindow(self.video_frame.winId().__int__())
                        elif sys.platform == "win32":
                            self.media_player.set_hwnd(self.video_frame.winId().__int__())
                        elif sys.platform == "darwin":
                            self.media_player.set_nsobject(self.video_frame.winId().__int__())
                        
                        # Update state before closing the window
                        self.is_fullscreen = False
                        
                        # Show OSD message for exiting fullscreen
                        self.show_osd_message("Exited fullscreen mode")
                        
                        # Close fullscreen window
                        self.fullscreen_window.close()
                        self.fullscreen_window = None
                    else:
                        print("Debug: Could not find right_layout")
                else:
                    print("Debug: Fullscreen window is None, already in normal mode")
                    self.is_fullscreen = False
                    return
            
            print(f"Debug: New fullscreen state: {self.is_fullscreen}")
            
        except Exception as e:
            print(f"Debug: Error in toggle_fullscreen: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")

    def on_server_changed(self, index):
        """Handle server selection change"""
        if index >= 0 and index < len(self.servers):
            server = self.servers[index]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            # Show/hide EPG button based on source type
            show_epg = (source_type == SourceType.TVHEADEND)
            self.epg_frame.setVisible(show_epg)
            
            # Rest of your existing on_server_changed method...
            self.statusbar.showMessage(f"Selected server: {server['name']}")
            self.fetch_channels()
            
            # If it's a TVHeadend server, fetch streaming profiles
            if source_type == SourceType.TVHEADEND:
                self.fetch_streaming_profiles()
                self.profile_combo.setVisible(True)
                self.profile_frame.setVisible(True)
            else:
                self.profile_combo.setVisible(False)
                self.profile_frame.setVisible(False)

    def manage_servers(self):
        """Open server management dialog"""
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

    def show_channel_context_menu(self, position):
        """Show context menu for channel list items"""
        menu = QMenu()
        
        # Get the item at the position
        row = self.channel_list.rowAt(position.y())
        if row >= 0:
            channel_item = self.channel_list.item(row, 1)  # Get name column item
            channel_data = channel_item.data(Qt.UserRole)
            
            # Get current server and source type
            server_index = self.server_combo.currentIndex()
            server = self.servers[server_index]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            # Add menu actions
            play_action = menu.addAction("Play")
            play_action.triggered.connect(lambda: self.play_channel_by_data(channel_data))
            
            # Only show Record option for TVHeadend sources
            if source_type == SourceType.TVHEADEND:
                record_action = menu.addAction("Record")
                record_action.triggered.connect(lambda: self.start_recording())
            
            # Always show Record Locally option
            local_record_action = menu.addAction("Record Locally")
            local_record_action.triggered.connect(
                lambda: self.start_local_recording(channel_data['name']))
            
            # Only show EPG action for TVHeadend sources
            if source_type == SourceType.TVHEADEND:
                epg_action = menu.addAction("Show EPG")
                epg_action.triggered.connect(lambda: self.show_channel_epg(channel_data['name']))
            
            # Show the menu at the cursor position
            menu.exec_(self.channel_list.viewport().mapToGlobal(position))

    def stop_recording(self, file_path=None, uuid=None):
        """Stop recording current channel or specific recording by file_path or UUID"""
        try:
            # If no specific recording is targeted, show the running jobs dialog
            if file_path is None and uuid is None:
                # Check if there are any active recordings
                if not self.recordings:
                    self.statusbar.showMessage("No active recordings to stop")
                    return
                
                # Check if there are any TVHeadend recordings specifically
                has_tvheadend_recordings = any(rec.get('type') == 'tvheadend' for rec in self.recordings)
                
                # Show the running jobs dialog
                print("Debug: Showing running jobs dialog to select recording to stop")
                self.show_running_jobs()
                return
            
            # Get current server
            server = self.servers[self.server_combo.currentIndex()]
            print(f"Debug: Using server: {server['name']} ({server['url']})")
            
            # If UUID is provided, directly stop the recording on the server
            if uuid is not None:
                print(f"Debug: Directly stopping recording with UUID: {uuid}")
                
                # Create auth if needed
                auth = None
                if server.get('username') or server.get('password'):
                    auth = (server.get('username', ''), server.get('password', ''))
                
                # Prepare stop request
                data = {'uuid': uuid}
                print(f"Debug: Stopping TVHeadend recording: {data}")
                
                # Make stop request with timeout
                stop_url = f'{server["url"]}/api/dvr/entry/stop'
                print(f"Debug: Sending stop request to: {stop_url}")
                
                try:
                    # Set a 5-second timeout for the request
                    response = requests.post(stop_url, data=data, auth=auth, timeout=5)
                    print(f"Debug: Stop request response status: {response.status_code}")
                    print(f"Debug: Stop request response text: {response.text}")
                    
                    if response.status_code == 200:
                        print(f"Debug: TVHeadend recording stopped successfully")
                        self.statusbar.showMessage("Recording stopped")
                        
                        # Remove from recordings list if present
                        for recording in self.recordings[:]:
                            if recording.get('type') == 'tvheadend' and recording.get('uuid') == uuid:
                                self.recordings.remove(recording)
                                break
                    else:
                        print(f"Debug: Failed to stop TVHeadend recording: {response.text}")
                        self.statusbar.showMessage(f"Failed to stop recording: Server returned {response.status_code}")
                except requests.exceptions.Timeout:
                    print("Debug: Request timed out when trying to stop recording")
                    self.statusbar.showMessage("Failed to stop recording: Server timeout")
                except requests.exceptions.ConnectionError:
                    print("Debug: Connection error when trying to stop recording")
                    self.statusbar.showMessage("Failed to stop recording: Server unreachable")
                
                # Stop recording indicator if no recordings are left
                if not self.recordings:
                    self.stop_recording_indicator()
                
                return
            
            # If file_path is provided, find the recording in the recordings list
            if file_path is not None:
                for recording in self.recordings[:]:
                    if recording.get('type') == 'tvheadend':
                        recording_file = recording.get('file', '')
                        if recording_file == file_path:
                            # Found the recording, get its UUID
                            uuid = recording.get('uuid')
                            if uuid:
                                # Recursively call with the UUID
                                self.stop_recording(uuid=uuid)
                                return
            
            # If we get here, we didn't find the recording
            print(f"Debug: No matching recording found to stop")
            self.statusbar.showMessage("No matching recording found")
            
        except Exception as e:
            print(f"Debug: Error stopping recording: {str(e)}")
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage("Error stopping recording")

    def start_local_recording(self, channel_name):
        """Start recording a channel locally using ffmpeg"""
        try:
            # Check if already recording
            if self.local_recording_process:
                self.show_osd_message("Already recording")
                return False
                
            # Get current channel data
            if not self.current_channel:
                self.show_osd_message("No channel selected")
                return False
                
            # Get stream URL
            stream_url = None
            server = self.servers[self.server_combo.currentIndex()]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            if source_type == SourceType.TVHEADEND:
                # Construct TVHeadend stream URL
                base_url = server['url']
                if not base_url.startswith(('http://', 'https://')):
                    base_url = f"http://{base_url}"
                    
                stream_url = f"{base_url}/stream/channel/{self.current_channel['uuid']}"
                
                # Add selected profile if available
                selected_profile = self.profile_combo.currentData()
                if selected_profile:
                    stream_url = f"{stream_url}?profile={selected_profile}"
                
                # Add authentication if needed
                if server.get('username') or server.get('password'):
                    username = server.get('username', '')
                    password = server.get('password', '')
                    stream_url = stream_url.replace('://', f'://{username}:{password}@')
            else:  # M3U
                # For M3U streams, use the URI directly
                stream_url = self.current_channel.get('uri')
                
                # Add authentication if needed
                if server.get('username') or server.get('password'):
                    username = server.get('username', '')
                    password = server.get('password', '')
                    
                    try:
                        # Parse the URL
                        parsed_url = urlparse(stream_url)
                        
                        # Check if URL already has authentication
                        if '@' not in parsed_url.netloc:
                            # Add authentication to the URL
                            auth_string = f"{username}:{password}@"
                            netloc_with_auth = auth_string + parsed_url.netloc
                            
                            # Reconstruct the URL with authentication
                            url_parts = list(parsed_url)
                            url_parts[1] = netloc_with_auth  # Replace netloc
                            stream_url = urlunparse(url_parts)
                    except Exception as e:
                        print(f"Debug: Error adding authentication to recording URL: {str(e)}")
            
            if not stream_url:
                self.show_osd_message("No stream URL available")
                return False
                
            # Get save path
            file_path = self.get_save_path(channel_name)
            if not file_path:
                self.show_osd_message("Recording canceled")
                return False
                
            # Prepare ffmpeg command
            ffmpeg_cmd = [
                'ffmpeg',
                '-y',  # Overwrite output file if it exists
                '-hide_banner',
                '-loglevel', 'warning'
            ]
            
            # Add input options
            ffmpeg_cmd.extend([
                '-i', stream_url,
                '-analyzeduration', '10M',  # Increase analyze duration
                '-probesize', '10M'         # Increase probe size
            ])
            
            # Add output options based on file extension
            if file_path.lower().endswith('.mp4'):
                ffmpeg_cmd.extend([
                    '-c:v', 'copy',         # Copy video stream without transcoding
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
            
            print(f"Debug: Starting recording with command: {' '.join(ffmpeg_cmd)}")
            
            # Start ffmpeg process
            self.local_recording_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
                
            # Add to recordings list for tracking
            recording_info = {
                'type': 'local',
                'channel': channel_name,
                'file_path': file_path,
                'start_time': time.time(),
                'process': self.local_recording_process,
                'size': 0
            }
            self.recordings.append(recording_info)
            print(f"Debug: Added recording to tracking list. Total recordings: {len(self.recordings)}")
            
            # Start recording indicator
            self.start_recording_indicator()
            
            # Create recording status dialog
            self.recording_status_dialog = RecordingStatusDialog(
                channel_name,
                file_path,
                self
            )
            self.recording_status_dialog.stopRequested.connect(self.stop_local_recording)
            self.recording_status_dialog.show()
            
            # Start timer to check recording status
            self.recording_check_timer = QTimer()
            self.recording_check_timer.timeout.connect(lambda: self.check_recording_status(file_path))
            self.recording_check_timer.start(1000)  # Check every second
            
            self.show_osd_message(f"Recording started: {channel_name}")
            return True
            
        except Exception as e:
            print(f"Debug: Error starting recording: {str(e)}")
            self.show_osd_message(f"Recording error: {str(e)}")
            return False

    def check_recording_status(self, file_path):
        """Check status of local recording file"""
        try:
            if not os.path.exists(file_path):
                print(f"Debug: Recording file not found: {file_path}")
                return
                
            file_size = os.path.getsize(file_path)
            
            # Update recording size in tracking list
            for recording in self.recordings:
                if recording.get('file_path') == file_path:
                    recording['size'] = file_size
                    break
            
            # Find the recording dialog
            if hasattr(self, 'recording_status_dialog') and self.recording_status_dialog and not self.recording_status_dialog.isHidden():
                # Check if file size is growing
                is_stalled = False
                if hasattr(self, 'last_file_size'):
                    if self.last_file_size == file_size:
                        self.stall_count = getattr(self, 'stall_count', 0) + 1
                        if self.stall_count > 5:  # Stalled for 5 seconds
                            is_stalled = True
                    else:
                        self.stall_count = 0
                
                self.last_file_size = file_size
                self.recording_status_dialog.update_status(file_size, is_stalled)
            else:
                # Dialog closed, stop the timer
                if hasattr(self, 'recording_check_timer') and self.recording_check_timer:
                    self.recording_check_timer.stop()
        
        except Exception as e:
            print(f"Debug: Error checking recording status: {str(e)}")
            if hasattr(self, 'recording_check_timer') and self.recording_check_timer:
                self.recording_check_timer.stop()
                
                self.last_file_size = file_size
                self.recording_status_dialog.update_status(file_size, is_stalled)
            else:
                # Dialog closed, stop the timer
                if hasattr(self, 'recording_check_timer') and self.recording_check_timer:
                    self.recording_check_timer.stop()
        
        except Exception as e:
            print(f"Debug: Error checking recording status: {str(e)}")
            if hasattr(self, 'recording_check_timer') and self.recording_check_timer:
                self.recording_check_timer.stop()
    
    def stop_local_recording(self):
        """Stop local recording"""
        try:
            # Stop recording instance
            if hasattr(self, 'local_recording_process') and self.local_recording_process:
                print("Debug: Stopping local recording")
                try:
                    self.local_recording_process.terminate()
                    self.local_recording_process.wait()
                except Exception as e:
                    print(f"Debug: Error stopping local recording: {str(e)}")
                
                # Remove from recordings list
                for i, recording in enumerate(self.recordings):
                    if recording.get('type') == 'local' and recording.get('process') == self.local_recording_process:
                        print(f"Debug: Removing recording from tracking list: {recording.get('channel')}")
                        self.recordings.pop(i)
                        break
                
                self.local_recording_process = None
                
                # Stop timer
                if hasattr(self, 'recording_check_timer') and self.recording_check_timer:
                    self.recording_check_timer.stop()
                    self.recording_check_timer = None
                    
                # Only stop recording indicator if no recordings are left
                if not self.recordings:
                    self.stop_recording_indicator()
                
                # Close the recording dialog if it exists and wasn't closed by stop_job
                if hasattr(self, 'recording_status_dialog') and self.recording_status_dialog:
                    # Check if this was called from the dialog itself
                    caller = traceback.extract_stack()[-2]
                    if 'stop_requested' not in caller.name:  # Not called from dialog's stop button
                        print("Debug: Closing recording status dialog from stop_local_recording")
                        self.recording_status_dialog.close()
                        self.recording_status_dialog = None
                
                self.statusbar.showMessage("Local recording stopped")
            else:
                print("Debug: No active local recording to stop")
                
        except Exception as e:
            print(f"Debug: Error stopping local recording: {str(e)}")
            self.statusbar.showMessage("Error stopping local recording")

    def toggle_mute(self):
        """Toggle audio mute state"""
        print("Debug: Toggling mute")
        if not hasattr(self, 'media_player') or not self.media_player:
            print("Debug: No media player available")
            return
            
        try:
            # Check if media is loaded and playing
            if not self.media_player.get_media():
                print("Debug: No media loaded, cannot toggle mute")
                return
                
            # Get current mute state
            try:
                is_muted = self.media_player.audio_get_mute()
            except Exception as e:
                print(f"Debug: Error getting mute state: {str(e)}")
                # Default to unmuted if we can't get the state
                is_muted = False
                
            # Set new mute state
            try:
                self.media_player.audio_set_mute(not is_muted)
            except Exception as e:
                print(f"Debug: Error setting mute state: {str(e)}")
                return
            
            if not is_muted:  # Switching to muted
                self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/mute.svg"))
                self.mute_btn.setToolTip("Unmute")
                print("Debug: Audio muted")
            else:  # Switching to unmuted
                self.mute_btn.setIcon(QIcon(f"{self.icons_dir}/unmute.svg"))
                self.mute_btn.setToolTip("Mute")
                print("Debug: Audio unmuted")
        except Exception as e:
            print(f"Debug: Error toggling mute: {str(e)}")

    def on_volume_changed(self, value):
        """Handle volume slider changes"""
        print(f"Debug: Volume changed to {value}")
        self.media_player.audio_set_volume(value)

    def show_dvr_status(self):
        """Show DVR status dialog"""
        try:
            # Get the current server
            server_index = self.server_combo.currentIndex()
            if server_index < 0 or server_index >= len(self.servers):
                return
                
            server = self.servers[server_index]
            
            # Create and show the DVR status dialog
            dialog = DVRStatusDialog(server, self)
            dialog.exec_()
        except Exception as e:
            print(f"Debug: Error showing recording jobs: {str(e)}")
            self.statusbar.showMessage("Error showing recording jobs")
            
    def fetch_streaming_profiles(self):
        """Fetch streaming profiles from TVHeadend server"""
        try:
            # Clear existing profiles except the default one
            self.profile_combo.clear()
            self.profile_combo.addItem("Default", "")
            
            # Get current server
            server_index = self.server_combo.currentIndex()
            if server_index < 0 or server_index >= len(self.servers):
                print("Debug: Invalid server index")
                return
                
            server = self.servers[server_index]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            # Only fetch profiles for TVHeadend sources
            if source_type != SourceType.TVHEADEND:
                self.profile_frame.setVisible(False)
                return
                
            # Show profile selection for TVHeadend sources
            self.profile_frame.setVisible(True)
            
            # Get server URL and ensure it has http:// prefix
            base_url = server['url']
            if not base_url.startswith(('http://', 'https://')):
                base_url = f"http://{base_url}"
                
            # Create API URL for profiles
            api_url = f'{base_url}/api/profile/list'
            print(f"Debug: Fetching streaming profiles from: {api_url}")
            
            # Create auth tuple if credentials exist
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                print(f"Debug: Using authentication with username: {server.get('username', '')}")
            
            # Make request to TVHeadend API
            response = requests.get(api_url, auth=auth, timeout=10)
            print(f"Debug: Response status: {response.status_code}")
            
            if response.status_code == 200:
                response_json = response.json()
                print(f"Debug: Raw response: {response_json}")
                profiles = response_json.get('entries', [])
                print(f"Debug: Found {len(profiles)} streaming profiles")
                
                # Add profiles to combo box
                for profile in profiles:
                    # According to the TVHeadend API docs, the profile name is in 'val' and the UUID is in 'key'
                    profile_name = profile.get('val', 'Unknown')
                    profile_uuid = profile.get('key', '')
                    self.profile_combo.addItem(profile_name, profile_name)  # Use name as the value
                    print(f"Debug: Added profile: {profile_name}")
            else:
                print(f"Debug: Failed to fetch profiles, status code: {response.status_code}")
                
        except Exception as e:
            print(f"Debug: Error fetching streaming profiles: {str(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")

    def start_recording_indicator(self):
        """Start the recording indicator with smooth pulsing animation"""
        print("Debug: Starting recording indicator")
        self.is_recording = True
        
        # Check if recording_indicator exists
        if hasattr(self, 'recording_indicator'):
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
        else:
            print("Debug: Recording indicator widget not found")
            # Just set the flag without animation
            self.statusbar.showMessage("Recording in progress")

    def stop_recording_indicator(self):
        """Stop the recording indicator animation"""
        print("Debug: Stopping recording indicator")
        self.is_recording = False
        
        if hasattr(self, 'recording_animation') and self.recording_animation:
            self.recording_animation.stop()
            self.recording_animation = None
            
        if hasattr(self, 'recording_indicator') and self.recording_indicator:
            if hasattr(self, 'opacity_effect') and self.opacity_effect:
                self.recording_indicator.setGraphicsEffect(None)
                self.opacity_effect = None
            
            self.recording_indicator.setProperty("recording", False)
            self.recording_indicator.style().polish(self.recording_indicator)
        else:
            self.statusbar.showMessage("Recording stopped")

    def show_recording_jobs(self):
        """Show recording jobs dialog"""
        dialog = RunningJobsDialog(self)
        dialog.show()
        
    def on_profile_changed(self, index):
        """Handle when user changes the streaming profile.
        Restart playback with the selected profile if a channel is currently playing.
        
        Args:
            index (int): Index of the newly selected profile in the profile_combo
        """
        print(f"Debug: Profile changed to index {index}")
        
        # Only restart playback if we have a current channel and it's a TVHeadend source
        if hasattr(self, 'current_channel') and self.current_channel:
            server = self.servers[self.server_combo.currentIndex()]
            source_type = SourceType(server.get('type', SourceType.TVHEADEND.value))
            
            if source_type == SourceType.TVHEADEND:
                print(f"Debug: Restarting playback with new profile: {self.profile_combo.currentText()}")
                # Stop current playback
                self.media_player.stop()
                
                # Restart playback with the same channel but new profile
                self.play_channel_by_data(self.current_channel)
        
    def on_media_playing(self, event):
        """Called when media starts playing successfully"""
        print("Debug: Playback started successfully")
        # Cancel the timeout timer if it's running
        if hasattr(self, 'playback_timeout_timer') and self.playback_timeout_timer.isActive():
            self.playback_timeout_timer.stop()
            print("Debug: Playback timeout timer canceled")
        
        # Show OSD message
        if hasattr(self, 'current_channel') and self.current_channel:
            channel_name = self.current_channel.get('name', 'Unknown')
            self.show_osd_message(f"Playing: {channel_name}")

    def on_media_error(self, event):
        """Called when media encounters an error"""
        print(f"Debug: Media error: {event}")
        
        # Get the current channel name if available
        channel_name = "Unknown"
        if hasattr(self, 'current_channel') and self.current_channel:
            channel_name = self.current_channel.get('name', 'Unknown')
        
        # Cancel the timeout timer if it's running
        if hasattr(self, 'playback_timeout_timer') and self.playback_timeout_timer.isActive():
            self.playback_timeout_timer.stop()
            
        # Stop the failed playback attempt
        self.media_player.stop()
        self.statusbar.showMessage(f"⚠ Error playing {channel_name}: Media playback failed")
        
        # Show OSD message
        self.show_osd_message(f"Error playing {channel_name}", 5000)

    def play_next_channel(self):
        """Play the next channel in the list"""
        try:
            if self.channel_list.rowCount() == 0:
                print("Debug: No channels in list")
                self.show_osd_message("No channels available")
                return
                
            # Get current row
            current_row = -1
            if hasattr(self, 'current_channel') and self.current_channel:
                # Find the current channel in the list
                for row in range(self.channel_list.rowCount()):
                    name_item = self.channel_list.item(row, 1)
                    if name_item and name_item.data(Qt.UserRole):
                        channel_data = name_item.data(Qt.UserRole)
                        if channel_data.get('name') == self.current_channel.get('name'):
                            current_row = row
                            break
            
            # Calculate next row (with wrap-around)
            next_row = (current_row + 1) % self.channel_list.rowCount()
            
            # Play the channel at next_row
            name_item = self.channel_list.item(next_row, 1)
            if name_item and name_item.data(Qt.UserRole):
                print(f"Debug: Playing next channel at row {next_row}")
                self.channel_list.selectRow(next_row)
                self.show_osd_message("Next channel")
                self.play_channel_by_data(name_item.data(Qt.UserRole))
        except Exception as e:
            print(f"Debug: Error playing next channel: {str(e)}")
            self.show_osd_message(f"Error: {str(e)}")
            
    def play_previous_channel(self):
        """Play the previous channel in the list"""
        try:
            if self.channel_list.rowCount() == 0:
                print("Debug: No channels in list")
                self.show_osd_message("No channels available")
                return
                
            # Get current row
            current_row = -1
            if hasattr(self, 'current_channel') and self.current_channel:
                # Find the current channel in the list
                for row in range(self.channel_list.rowCount()):
                    name_item = self.channel_list.item(row, 1)
                    if name_item and name_item.data(Qt.UserRole):
                        channel_data = name_item.data(Qt.UserRole)
                        if channel_data.get('name') == self.current_channel.get('name'):
                            current_row = row
                            break
            
            # Calculate previous row (with wrap-around)
            prev_row = (current_row - 1) % self.channel_list.rowCount()
            
            # Play the channel at prev_row
            name_item = self.channel_list.item(prev_row, 1)
            if name_item and name_item.data(Qt.UserRole):
                print(f"Debug: Playing previous channel at row {prev_row}")
                self.channel_list.selectRow(prev_row)
                self.show_osd_message("Previous channel")
                self.play_channel_by_data(name_item.data(Qt.UserRole))
        except Exception as e:
            print(f"Debug: Error playing previous channel: {str(e)}")
            self.show_osd_message(f"Error: {str(e)}")
            
    def toggle_play_pause(self):
        """Toggle play/pause state of the media player"""
        if self.media_player.is_playing():
            self.media_player.pause()
            self.show_osd_message("Paused")
        else:
            self.media_player.play()
            self.show_osd_message("Playing")
            
    def setup_osd(self):
        """Setup VLC's built-in OSD (On-Screen Display) using marquee"""
        # Enable marquee
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Enable, 1)
        
        # Set marquee text size (pixels) - increased to 48 for better visibility
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Size, 48)
        
        # Try using just the top position (4) first
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Position, 5)  # 4 = top
        
                
        # Set margins from edges
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.X, 20)
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Y, 20)
        
        # Set text color (white) and opacity
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Color, 0xFFFFFF)
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Opacity, 255)  # 0-255
        
        # Set timeout (milliseconds)
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Timeout, 3000)
        
        # Initialize with empty text
        self.media_player.video_set_marquee_string(vlc.VideoMarqueeOption.Text, "")
        
    def show_osd_message(self, message, timeout=3000):
        """Show a message on the OSD"""
        # Set the timeout (in milliseconds)
        self.media_player.video_set_marquee_int(vlc.VideoMarqueeOption.Timeout, timeout)
        
        # Set the message text
        self.media_player.video_set_marquee_string(vlc.VideoMarqueeOption.Text, message)

    def show_epg(self):
        """Show the EPG window"""
        # Get the current server
        current_server_index = self.server_combo.currentIndex()
        if current_server_index >= 0 and current_server_index < len(self.servers):
            server = self.servers[current_server_index]
            
            # Only show EPG for TVHeadend servers
            if server.get('type') == 'tvheadend':
                epg_window = EPGWindow(server, self)
                epg_window.exec_()
            else:
                self.statusBar().showMessage("EPG is only available for TVHeadend servers", 3000)

    def play_channel_by_uuid(self, channel_uuid):
        """Play a channel by its UUID"""
        # Find the channel in the channel list
        for row in range(self.channel_list.rowCount()):
            channel_item = self.channel_list.item(row, 1)
            if channel_item and channel_item.data(Qt.UserRole).get('uuid') == channel_uuid:
                self.play_channel_from_table(channel_item)
                return
        
        # If not found, show a message
        self.statusBar().showMessage(f"Channel not found", 3000)

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
            try:
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
                    lambda checked, e=entry: self.schedule_recording(e))
                item_layout.addWidget(record_btn)
                
                # Create list item and set custom widget
                list_item = QListWidgetItem(self.epg_list)
                list_item.setSizeHint(item_widget.sizeHint())
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
                "title": {
                    "eng": entry.get('title', 'Scheduled Recording')
                },
                "description": {
                    "eng": entry.get('description', '')
                },
                "comment": "Scheduled via TVHplayer"
            }
            
            # Convert to string format as expected by the API
            data = {'conf': json.dumps(conf_data)}
            print(f"Debug: Recording data: {data}")
            
            # Make recording request
            record_url = f'{self.server["url"]}/api/dvr/entry/create'
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

class RecordingStatusDialog(QDialog):
    # Signal for stop request
    stopRequested = pyqtSignal()
    
    def __init__(self, channel_name, file_path, parent=None):
        super().__init__(parent)
        self.setup_ui(channel_name, file_path)
    
    def setup_ui(self, channel_name, file_path):
        """Set up the recording status dialog UI"""
        self.setWindowTitle(f"Recording: {channel_name}")
        self.setMinimumWidth(400)
        
        # Create layout
        layout = QVBoxLayout(self)
        
        # Add recording info
        info_layout = QFormLayout()
        
        # Channel name
        channel_label = QLabel(channel_name)
        channel_label.setStyleSheet("font-weight: bold;")
        info_layout.addRow("Channel:", channel_label)
        
        # File path
        path_label = QLabel(file_path)
        path_label.setWordWrap(True)
        info_layout.addRow("Saving to:", path_label)
        
        # Current size
        self.size_label = QLabel("0 MB")
        info_layout.addRow("Current size:", self.size_label)
        
        # Status
        self.status_label = QLabel("Recording...")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        info_layout.addRow("Status:", self.status_label)
        
        layout.addLayout(info_layout)
        
        # Add stop button
        self.stop_button = QPushButton("Stop Recording")
        self.stop_button.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)
        
        # Set dialog properties
        self.setModal(False)  # Non-modal dialog
        self.resize(450, 200)
    
    def update_status(self, file_size, is_stalled=False):
        """Update the recording status information"""
        # Convert file size to MB
        size_mb = file_size / (1024 * 1024)
        self.size_label.setText(f"{size_mb:.2f} MB")
        
        # Update status if stalled
        if is_stalled:
            self.status_label.setText("Stalled - No data received")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.status_label.setText("Recording...")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
    
    def stop_requested(self):
        """Signal that user wants to stop recording"""
        self.stopRequested.emit()  # Emit the signal
        self.accept()

def parse_m3u(content, username='', password=''):
    """Parse M3U/M3U8 playlist content"""
    channels = []
    current_channel = None
    
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF:'):
            # Parse the EXTINF line
            # Format: #EXTINF:-1 tvg-id="..." tvg-name="..." tvg-logo="..." group-title="...",Channel Name
            try:
                # Extract channel name after the comma
                channel_name = line.split(',')[-1].strip()
                
                # Extract attributes using regex
                attrs = {}
                for attr in ['tvg-id', 'tvg-name', 'tvg-logo', 'group-title']:
                    match = re.search(f'{attr}="([^"]*)"', line)
                    if match:
                        attrs[attr] = match.group(1)
                
                current_channel = {
                    'name': channel_name,
                    'attributes': attrs
                }
            except Exception as e:
                print(f"Debug: Error parsing EXTINF line: {str(e)}")
                current_channel = None
                
        elif line.startswith('#'):
            # Skip other M3U directives
            continue
        elif current_channel is not None:
            # This is the URL line
            stream_url = line
            
            # Add authentication to stream URL if credentials are provided
            if username and password and not ('://' + username + ':' in stream_url):
                try:
                    # Parse the URL
                    parsed_url = urlparse(stream_url)
                    
                    # Check if URL already has authentication
                    if '@' not in parsed_url.netloc:
                        # Add authentication to the URL
                        auth_string = f"{username}:{password}@"
                        netloc_with_auth = auth_string + parsed_url.netloc
                        
                        # Reconstruct the URL with authentication
                        stream_url_parts = list(parsed_url)
                        stream_url_parts[1] = netloc_with_auth  # Replace netloc
                        stream_url = urlunparse(stream_url_parts)
                        print(f"Debug: Added authentication to stream URL for {current_channel['name']}")
                except Exception as e:
                    print(f"Debug: Error adding authentication to URL: {str(e)}")
            
            current_channel['uri'] = stream_url
            channels.append(current_channel)
            current_channel = None
            
    return channels

def main():
    """Main entry point for the application"""
    try:
        # Force the application to use XCB instead of Wayland
        # This helps with VLC integration under Wayland
        #QCoreApplication.setAttribute(Qt.AA_X11InitThreads, True)
        #os.environ["QT_QPA_PLATFORM"] = "xcb"
        
        app = QApplication(sys.argv)
        player = TVHeadendClient()
        player.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Error starting application: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == '__main__':
    main()
import sys
import json
import time
from datetime import datetime, timedelta
import requests
from urllib.parse import urlencode
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLineEdit, QLabel, 
                            QListWidget, QMessageBox, QDialog, QFormLayout,
                            QComboBox, QMenu, QSpinBox, QDialogButtonBox,
                            QSplitter, QStyle, QSpacerItem, QFrame, QFileDialog)
from PyQt5.QtCore import Qt, QSettings, QSize, QRect, QTimer
from PyQt5.QtGui import QWindow, QScreen
import vlc
import subprocess
import os
import threading

def toggle_fullscreen(self):
    if not self.is_fullscreen:
        # Store current window state and flags
        self.normal_geometry = self.geometry()
        self.normal_state = self.windowState()
        self.normal_flags = self.windowFlags()
        
        # Hide UI elements except video frame
        self.menuBar().hide()
        self.splitter.hide()
        self.video_frame.setParent(None)
        self.centralWidget().layout().addWidget(self.video_frame)
        
        # Get screen size
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        
        # Make window fullscreen without borders
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.showFullScreen()
        self.setGeometry(screen_geometry)
        
        # Set video frame to maintain aspect ratio
        if self.player:
            video_width = self.player.video_get_width()
            video_height = self.player.video_get_height()
            if video_width and video_height:
                # Calculate aspect ratio
                aspect_ratio = video_width / video_height
                screen_ratio = screen_geometry.width() / screen_geometry.height()
                
                if aspect_ratio > screen_ratio:
                    # Video is wider than screen
                    w = screen_geometry.width()
                    h = int(w / aspect_ratio)
                    x = 0
                    y = (screen_geometry.height() - h) // 2
                else:
                    # Video is taller than screen
                    h = screen_geometry.height()
                    w = int(h * aspect_ratio)
                    x = (screen_geometry.width() - w) // 2
                    y = 0
                
                # Set video frame geometry to maintain aspect ratio
                self.video_frame.setGeometry(x, y, w, h)
                # Set background color for letterboxing
                self.setStyleSheet("background-color: black;")
            else:
                # If can't get video dimensions, fill screen
                self.video_frame.setGeometry(0, 0, screen_geometry.width(), screen_geometry.height())
        
    else:
        # Restore window flags and state
        self.setStyleSheet("")  # Clear background color
        self.setWindowFlags(self.normal_flags)
        self.showNormal()
        self.setGeometry(self.normal_geometry)
        
        # Restore UI elements
        self.menuBar().show()
        self.video_frame.setParent(None)
        self.centralWidget().layout().removeWidget(self.video_frame)
        self.splitter.insertWidget(1, self.video_frame)
        self.splitter.show()
    
    self.is_fullscreen = not self.is_fullscreen
    
class RecordDurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Recording Duration")
        layout = QVBoxLayout()
        
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["30 minutes", "1 hour", "2 hours", "4 hours", "Custom"])
        layout.addWidget(self.duration_combo)
        
        self.custom_widget = QWidget()
        custom_layout = QHBoxLayout()
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 1440)  # 1 min to 24 hours
        self.duration_spin.setValue(60)
        custom_layout.addWidget(self.duration_spin)
        custom_layout.addWidget(QLabel("minutes"))
        self.custom_widget.setLayout(custom_layout)
        self.custom_widget.hide()
        layout.addWidget(self.custom_widget)
        
        self.duration_combo.currentTextChanged.connect(self.on_duration_changed)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        
    def on_duration_changed(self, text):
        self.custom_widget.setVisible(text == "Custom")
        
    def get_duration_minutes(self):
        duration_text = self.duration_combo.currentText()
        if duration_text == "Custom":
            return self.duration_spin.value()
        elif duration_text == "30 minutes":
            return 30
        elif duration_text == "1 hour":
            return 60
        elif duration_text == "2 hours":
            return 120
        elif duration_text == "4 hours":
            return 240
        return 60  # Default to 1 hour

class ServerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add TVHeadend Server")
        self.setMinimumWidth(400)  # Set minimum width
        layout = QFormLayout()
        layout.setSpacing(10)  # Add some spacing between elements
        
        # Create and configure input fields with better sizes
        self.name_edit = QLineEdit()
        self.name_edit.setMinimumWidth(300)  # Set minimum width for input fields
        
        self.url_edit = QLineEdit()
        self.url_edit.setMinimumWidth(300)
        self.url_edit.setPlaceholderText("http://server:9981")
        
        self.username_edit = QLineEdit()
        self.username_edit.setMinimumWidth(300)
        
        self.password_edit = QLineEdit()
        self.password_edit.setMinimumWidth(300)
        self.password_edit.setEchoMode(QLineEdit.Password)
        
        # Add validation
        self.name_edit.textChanged.connect(self.validate_input)
        self.url_edit.textChanged.connect(self.validate_input)
        
        # Add widgets to layout with some padding
        layout.setContentsMargins(20, 20, 20, 20)  # Add margins around the form
        layout.addRow("Name:", self.name_edit)
        layout.addRow("URL:", self.url_edit)
        layout.addRow("Username:", self.username_edit)
        layout.addRow("Password:", self.password_edit)
        
        # Configure button box
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.save_button = self.button_box.button(QDialogButtonBox.Save)
        self.save_button.setEnabled(False)
        
        # Add some vertical spacing before the buttons
        layout.addItem(QSpacerItem(0, 20))  # Add 20 pixels of vertical space
        layout.addRow(self.button_box)
        
        self.setLayout(layout)
        
        # Set a reasonable default size for the dialog
        self.resize(450, 250)
        
    def validate_input(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        self.save_button.setEnabled(bool(name and url))
        
    def get_server_info(self):
        return {
            'name': self.name_edit.text().strip(),
            'url': self.url_edit.text().strip().rstrip('/'),
            'username': self.username_edit.text().strip(),
            'password': self.password_edit.text()
        }

def find_vlc():
    """Find VLC library path"""
    import os
    import sys
    
    if sys.platform == "win32":
        # Windows paths
        paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "vlc"),
            os.path.join(os.path.dirname(sys.executable), "vlc"),
            r"C:\Program Files\VideoLAN\VLC",
            r"C:\Program Files (x86)\VideoLAN\VLC",
        ]
    else:
        # Linux paths
        paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "vlc"),
            os.path.join(os.path.dirname(sys.executable), "vlc"),
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib",
            "/usr/local/lib",
            "/usr/lib/vlc",
            "/usr/lib64/vlc",
            "/usr/local/lib/vlc",
        ]
    
    for path in paths:
        if os.path.exists(path):
            print(f"Found VLC path: {path}")
            return path
    return None

class TVHeadendClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TVHplayer by mFat")
        self.setGeometry(100, 100, 1000, 600)
        
        # Initialize VLC with proper error handling
        try:
            print("Initializing VLC...")
            
            # Set environment variables for VLC
            if getattr(sys, 'frozen', False):
                # Running as compiled
                base_path = sys._MEIPASS
                plugin_path = os.path.join(base_path, 'plugins')
                os.environ['VLC_PLUGIN_PATH'] = plugin_path
                
                # Add the directory containing VLC libraries to LD_LIBRARY_PATH
                if sys.platform == "linux":
                    current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
                    os.environ['LD_LIBRARY_PATH'] = f"{base_path}:{current_ld_path}"
            
            # VLC initialization arguments
            vlc_args = [
                '--no-video-title-show',
                '--quiet',
            ]
            
            print(f"VLC_PLUGIN_PATH: {os.environ.get('VLC_PLUGIN_PATH', 'Not set')}")
            print(f"LD_LIBRARY_PATH: {os.environ.get('LD_LIBRARY_PATH', 'Not set')}")
            
            self.instance = vlc.Instance(vlc_args)
            if not self.instance:
                raise Exception("Failed to create VLC instance")
            
            self.player = self.instance.media_player_new()
            if not self.player:
                raise Exception("Failed to create media player")
            
            print("VLC initialized successfully")
            
        except Exception as e:
            error_msg = (
                f"Failed to initialize VLC: {str(e)}\n"
                "Please ensure VLC is properly installed on your system.\n"
                f"Current platform: {sys.platform}\n"
                f"Python executable: {sys.executable}\n"
                f"VLC_PLUGIN_PATH: {os.environ.get('VLC_PLUGIN_PATH', 'Not set')}\n"
                f"LD_LIBRARY_PATH: {os.environ.get('LD_LIBRARY_PATH', 'Not set')}\n"
            )
            QMessageBox.critical(self, "VLC Error", error_msg)
            raise
        
        self.is_fullscreen = False
        self.active_recording = None
        self.local_recording = False
        self.recording_filename = None
        self.ffmpeg_process = None
        self.fullscreen_instance = None
        self.fullscreen_player = None
        self.fullscreen_window = None
        self.fullscreen_frame = None
        
        self.settings = QSettings('TVHeadendClient', 'Servers')
        self.servers = self.load_servers()
        self.current_server = None
        self.channels_data = {}
        
        self.setup_ui()
        
    def load_servers(self):
        servers = self.settings.value('servers', {})
        return servers if isinstance(servers, dict) else {}
    
    def save_servers(self):
        self.settings.setValue('servers', self.servers)
        self.update_server_list()
    
    def update_server_list(self):
        current = self.server_combo.currentText()
        self.server_combo.clear()
        self.server_combo.addItems(sorted(self.servers.keys()))
        
        index = self.server_combo.findText(current)
        if index >= 0:
            self.server_combo.setCurrentIndex(index)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Create splitter for resizable panels
        self.splitter = QSplitter(Qt.Horizontal)
        
        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Server controls with improved styling
        server_widget = QWidget()
        server_layout = QVBoxLayout(server_widget)
        server_layout.setContentsMargins(5, 5, 5, 5)
        
        server_header = QHBoxLayout()
        self.server_combo = QComboBox()
        self.server_combo.setMinimumWidth(200)
        self.server_combo.setContextMenuPolicy(Qt.CustomContextMenu)
        self.server_combo.customContextMenuRequested.connect(self.show_server_context_menu)
        
        server_header.addWidget(QLabel("Server:"))
        server_header.addWidget(self.server_combo, stretch=1)
        
        server_buttons = QHBoxLayout()
        add_server_btn = QPushButton("Add")
        add_server_btn.setToolTip("Add new server")
        edit_server_btn = QPushButton("Edit")
        edit_server_btn.setToolTip("Edit selected server")
        remove_server_btn = QPushButton("Remove")
        remove_server_btn.setToolTip("Remove selected server")
        
        server_buttons.addWidget(add_server_btn)
        server_buttons.addWidget(edit_server_btn)
        server_buttons.addWidget(remove_server_btn)
        
        server_layout.addLayout(server_header)
        server_layout.addLayout(server_buttons)
        
        # Connect server management buttons
        add_server_btn.clicked.connect(self.add_server)
        edit_server_btn.clicked.connect(self.edit_server)
        remove_server_btn.clicked.connect(self.remove_server)
        self.server_combo.currentTextChanged.connect(self.server_changed)
        
        # Channel list
        channel_label = QLabel("Channels:")
        self.channel_list = QListWidget()
        self.channel_list.itemDoubleClicked.connect(self.play_channel)
        
        # Playback controls
        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.record_button = QPushButton("TVH Record")
        self.record_button.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.local_record_button = QPushButton("Local Record")
        self.local_record_button.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.stop_record_button = QPushButton("Stop Recording")
        self.stop_record_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button = QPushButton("Stop")
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.fullscreen_button = QPushButton("Fullscreen")
        self.fullscreen_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMaxButton))
        
        self.play_button.clicked.connect(self.play_selected)
        self.record_button.clicked.connect(self.record_channel)
        self.stop_record_button.clicked.connect(self.stop_recording)
        self.stop_button.clicked.connect(self.stop_playback)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.local_record_button.clicked.connect(self.start_local_recording)
        
        self.stop_record_button.setEnabled(False)
        
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.record_button)
        controls_layout.addWidget(self.local_record_button)
        controls_layout.addWidget(self.stop_record_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.fullscreen_button)
        
        # Server section
        server_section = QWidget()
        server_layout = QVBoxLayout(server_section)
        server_layout.setContentsMargins(10, 10, 10, 10)
        server_layout.addWidget(server_widget)
        
        # Add server section to main layout
        left_layout.addWidget(server_section)
        
        # Add horizontal line divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("""
            QFrame {
                color: palette(mid);
                margin: 5px 0px;
            }
        """)
        left_layout.addWidget(line)
        
        # Channel section
        channel_section = QWidget()
        channel_layout = QVBoxLayout(channel_section)
        channel_layout.setContentsMargins(10, 10, 10, 10)
        
        channel_label = QLabel("Channels:")
        channel_layout.addWidget(channel_label)
        channel_layout.addWidget(self.channel_list)
        channel_layout.addLayout(controls_layout)
        
        # Add channel section to main layout
        left_layout.addWidget(channel_section)
        
        # Right panel for video
        self.video_frame = QWidget()
        self.video_frame.setMinimumSize(400, 300)
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_frame.mouseDoubleClickEvent = self.video_double_clicked
        
        # Add panels to splitter
        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(self.video_frame)
        self.splitter.setStretchFactor(1, 1)  # Make video panel stretch
        
        main_layout.addWidget(self.splitter)
        
        # Initialize server list
        self.update_server_list()

    def video_double_clicked(self, event):
        self.toggle_fullscreen()

    def toggle_fullscreen(self):
        if not self.is_fullscreen:
            # Store current window state and flags
            self.normal_geometry = self.geometry()
            self.normal_state = self.windowState()
            self.normal_flags = self.windowFlags()
            
            # Hide UI elements except video frame
            self.menuBar().hide()
            self.splitter.hide()
            self.video_frame.setParent(None)
            self.centralWidget().layout().addWidget(self.video_frame)
            
            # Get screen size
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry()
            
            # Make window fullscreen without borders
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.showFullScreen()
            self.setGeometry(screen_geometry)
            
            # Set video frame to maintain aspect ratio
            if self.player:
                video_width = self.player.video_get_width()
                video_height = self.player.video_get_height()
                if video_width and video_height:
                    # Calculate aspect ratio
                    aspect_ratio = video_width / video_height
                    screen_ratio = screen_geometry.width() / screen_geometry.height()
                    
                    if aspect_ratio > screen_ratio:
                        # Video is wider than screen
                        w = screen_geometry.width()
                        h = int(w / aspect_ratio)
                        x = 0
                        y = (screen_geometry.height() - h) // 2
                    else:
                        # Video is taller than screen
                        h = screen_geometry.height()
                        w = int(h * aspect_ratio)
                        x = (screen_geometry.width() - w) // 2
                        y = 0
                    
                    # Set video frame geometry to maintain aspect ratio
                    self.video_frame.setGeometry(x, y, w, h)
                    # Set background color for letterboxing
                    self.setStyleSheet("background-color: black;")
                else:
                    # If can't get video dimensions, fill screen
                    self.video_frame.setGeometry(0, 0, screen_geometry.width(), screen_geometry.height())
            
        else:
            # Restore window flags and state
            self.setStyleSheet("")  # Clear background color
            self.setWindowFlags(self.normal_flags)
            self.showNormal()
            self.setGeometry(self.normal_geometry)
            
            # Restore UI elements
            self.menuBar().show()
            self.video_frame.setParent(None)
            self.centralWidget().layout().removeWidget(self.video_frame)
            self.splitter.insertWidget(1, self.video_frame)
            self.splitter.show()
        
        self.is_fullscreen = not self.is_fullscreen
    
    def show_server_context_menu(self, position):
        menu = QMenu()
        edit_action = menu.addAction("Edit Server")
        remove_action = menu.addAction("Remove Server")
        
        action = menu.exec_(self.server_combo.mapToGlobal(position))
        if action == edit_action:
            self.edit_server()
        elif action == remove_action:
            self.remove_server()

    def add_server(self):
        dialog = ServerDialog(self)
        if dialog.exec_():
            server_info = dialog.get_server_info()
            if server_info['name']:
                self.servers[server_info['name']] = {
                    'url': server_info['url'],
                    'username': server_info['username'],
                    'password': server_info['password']
                }
                self.save_servers()
                
    def edit_server(self):
        current_name = self.server_combo.currentText()
        if not current_name:
            return
            
        dialog = ServerDialog(self)
        current_server = self.servers[current_name]
        dialog.name_edit.setText(current_name)
        dialog.url_edit.setText(current_server['url'])
        dialog.username_edit.setText(current_server['username'])
        dialog.password_edit.setText(current_server['password'])
        
        if dialog.exec_():
            server_info = dialog.get_server_info()
            if server_info['name'] != current_name:
                self.servers.pop(current_name)
            
            self.servers[server_info['name']] = {
                'url': server_info['url'],
                'username': server_info['username'],
                'password': server_info['password']
            }
            self.save_servers()

    def remove_server(self):
        current_server = self.server_combo.currentText()
        if current_server:
            reply = QMessageBox.question(
                self,
                'Remove Server',
                f'Are you sure you want to remove "{current_server}"?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.servers.pop(current_server, None)
                self.save_servers()
                self.current_server = None
                self.channel_list.clear()

    def server_changed(self, server_name):
        if server_name in self.servers:
            self.current_server = self.servers[server_name]
            self.fetch_channels()

    def fetch_channels(self):
        if not self.current_server:
            return
            
        try:
            base_url = self.current_server['url']
            url = f"{base_url}/api/channel/grid"
            
            params = {
                'start': 0,
                'limit': 999999,
                'sort': 'name',
                'dir': 'ASC'
            }
            
            auth = None
            if self.current_server.get('username') and self.current_server.get('password'):
                auth = (self.current_server['username'], self.current_server['password'])
            
            response = requests.get(url, params=params, auth=auth)
            response.raise_for_status()
            
            data = response.json()
            if 'entries' not in data:
                raise ValueError("No channels found in response")
                
            self.channels_data = {channel['name']: channel for channel in data['entries']}
            
            self.channel_list.clear()
            for channel_name in sorted(self.channels_data.keys()):
                self.channel_list.addItem(channel_name)
                
        except requests.exceptions.RequestException as e:
            QMessageBox.warning(self, "Connection Error", 
                              f"Failed to connect to server: {str(e)}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to fetch channels: {str(e)}")

    def play_channel(self, item):
        if not self.current_server or not item:
            return
            
        try:
            channel_name = item.text()
            if channel_name not in self.channels_data:
                raise ValueError("Channel not found")
                
            channel = self.channels_data[channel_name]
            base_url = self.current_server['url']
            stream_url = f"{base_url}/stream/channel/{channel['uuid']}"
            
            if self.current_server.get('username') and self.current_server.get('password'):
                auth_string = f"{self.current_server['username']}:{self.current_server['password']}"
                stream_url = stream_url.replace('://', f'://{auth_string}@')
            
            self.player.stop()
            media = self.instance.media_new(stream_url)
            self.player.set_media(media)
            
            if sys.platform == "win32":
                self.player.set_hwnd(int(self.video_frame.winId()))
            else:
                self.player.set_xwindow(int(self.video_frame.winId()))
                
            self.player.play()
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to play channel: {str(e)}")

    def play_selected(self):
        current_item = self.channel_list.currentItem()
        if current_item:
            self.play_channel(current_item)

    def stop_playback(self):
        self.player.stop()

    def record_channel(self):
        if not self.current_server:
            return
            
        current_item = self.channel_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Error", "Please select a channel to record")
            return
        
        duration_dialog = RecordDurationDialog(self)
        if duration_dialog.exec_():
            duration_minutes = duration_dialog.get_duration_minutes()
            
            try:
                channel_name = current_item.text()
                if channel_name not in self.channels_data:
                    raise ValueError("Channel not found")
                    
                channel = self.channels_data[channel_name]
                start_time = int(time.time())
                stop_time = start_time + (duration_minutes * 60)
                
                conf = {
                    "start": start_time,
                    "stop": stop_time,
                    "channel": channel['uuid'],
                    "title": {"eng": f"Recording - {channel_name}"},
                    "subtitle": {"eng": f"Duration: {duration_minutes} minutes"}
                }
                
                form_data = {'conf': json.dumps(conf)}
                
                base_url = self.current_server['url']
                record_url = f"{base_url}/api/dvr/entry/create"
                
                auth = None
                if self.current_server.get('username') and self.current_server.get('password'):
                    auth = (self.current_server['username'], self.current_server['password'])
                
                response = requests.post(
                    record_url,
                    data=form_data,
                    auth=auth
                )
                
                response.raise_for_status()
                data = response.json()
                self.active_recording = data.get('uuid')
                self.stop_record_button.setEnabled(True)
                
                QMessageBox.information(self, "Success", 
                                      f"Started recording {channel_name} for {duration_minutes} minutes")
                    
            except requests.exceptions.RequestException as e:
                QMessageBox.warning(self, "Connection Error", 
                                  f"Failed to connect to server: {str(e)}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to start recording: {str(e)}")

    def start_local_recording(self):
        if not self.player or not self.player.is_playing():
            QMessageBox.warning(self, "Error", "Please start playing a channel first")
            return
            
        # Show duration dialog
        duration_dialog = RecordDurationDialog(self)
        if duration_dialog.exec_():
            duration_minutes = duration_dialog.get_duration_minutes()
            
            try:
                # Get current channel name for filename
                current_item = self.channel_list.currentItem()
                if not current_item:
                    raise ValueError("No channel selected")
                    
                channel_name = current_item.text()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{channel_name}_{timestamp}.mp4"
                
                # Ask user for save location
                save_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Recording",
                    filename,
                    "Video Files (*.mp4)"
                )
                
                if save_path:
                    # Get the current media URL
                    current_media = self.player.get_media()
                    if not current_media:
                        raise ValueError("No media loaded")
                    
                    media_url = current_media.get_mrl()
                    print(f"Debug - Media URL: {media_url}")  # Debug print
                    
                    # Modified FFmpeg command to handle AAC-LATM audio
                    command = [
                        'ffmpeg',
                        '-y',
                        '-hide_banner',
                        '-loglevel', 'debug',
                        '-i', media_url,
                        '-c:v', 'copy',           # Copy video stream without re-encoding
                        '-c:a', 'aac',            # Convert audio to standard AAC
                        '-b:a', '192k',           # Set audio bitrate
                        '-movflags', '+faststart',
                        '-t', str(duration_minutes * 60),
                        save_path
                    ]
                    
                    print(f"Debug - FFmpeg command: {' '.join(command)}")
                    
                    # Start FFmpeg process
                    self.ffmpeg_process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True
                    )
                    
                    # Start a thread to monitor FFmpeg output
                    def monitor_ffmpeg():
                        while self.ffmpeg_process:
                            output = self.ffmpeg_process.stderr.readline()
                            if output:
                                print(f"FFmpeg: {output.strip()}")
                            if self.ffmpeg_process.poll() is not None:
                                break
                    
                    monitor_thread = threading.Thread(target=monitor_ffmpeg)
                    monitor_thread.daemon = True
                    monitor_thread.start()
                    
                    self.recording_filename = save_path
                    self.local_recording = True
                    self.local_record_button.setEnabled(False)
                    self.stop_record_button.setEnabled(True)
                    
                    # Schedule recording stop
                    QTimer.singleShot(duration_minutes * 60 * 1000, self.stop_local_recording)
                    
                    QMessageBox.information(
                        self,
                        "Recording Started",
                        f"Recording to {save_path}\nDuration: {duration_minutes} minutes"
                    )
            
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to start recording: {str(e)}")
                print(f"Recording error: {str(e)}")
    
    def stop_local_recording(self):
        if self.local_recording and self.ffmpeg_process:
            try:
                # Terminate FFmpeg process
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=5)  # Wait for process to end
                
                self.ffmpeg_process = None
                self.local_recording = False
                self.local_record_button.setEnabled(True)
                self.stop_record_button.setEnabled(False)
                
                if os.path.exists(self.recording_filename):
                    QMessageBox.information(
                        self,
                        "Recording Stopped",
                        f"Recording saved to:\n{self.recording_filename}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Recording Error",
                        "The recording file was not created successfully."
                    )
                
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to stop recording: {str(e)}")
    
    def stop_recording(self):
        if self.local_recording:
            self.stop_local_recording()
        elif self.active_recording:
            # Existing TVHeadend recording stop code
            try:
                base_url = self.current_server['url']
                stop_url = f"{base_url}/api/dvr/entry/stop"
                
                auth = None
                if self.current_server.get('username') and self.current_server.get('password'):
                    auth = (self.current_server['username'], self.current_server['password'])
                
                response = requests.post(
                    stop_url,
                    data={'uuid': self.active_recording},
                    auth=auth
                )
                
                response.raise_for_status()
                self.active_recording = None
                self.stop_record_button.setEnabled(False)
                
                QMessageBox.information(self, "Success", "Recording stopped")
                
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to stop recording: {str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TVHeadendClient()
    window.show()
    sys.exit(app.exec_())
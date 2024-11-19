from datetime import datetime, timedelta
import sys
from tkinter.filedialog import FileDialog
import vlc
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QToolBar, QComboBox, QAction, QSplitter, QFrame,
    QListWidget, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox, QApplication,
    QPushButton, QLabel, QSlider, QStatusBar, QGridLayout, QMenuBar, QRadioButton, QSpinBox, QGraphicsOpacityEffect, QFileDialog
)
from PyQt5.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, QAbstractAnimation
from PyQt5.QtGui import QIcon
import json
import requests
import resources_rc
import time
import subprocess
import os
from pathlib import Path

# Version number
__version__ = "2.0"

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
        # Remove http:// or https:// for validation
        if url.startswith('http://'):
            url = url[7:]
        elif url.startswith('https://'):
            url = url[8:]
            
        # Split host and port
        if ':' in url:
            host, port = url.split(':')
            # Validate port
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    return False, "Port must be between 1 and 65535"
            except ValueError:
                return False, "Invalid port number"
        else:
            host = url
            
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

class TVHeadendClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config_file = os.path.join(str(Path.home()), '.tvhplayer.conf')
        print(f"Debug: Config file location: {self.config_file}")
        self.config = self.load_config()
        print(f"Debug: Current config: {json.dumps(self.config, indent=2)}")
        print("Debug: Initializing TVHeadendClient")
        
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
        
        # Rest of initialization...
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
            raise RuntimeError(f"Failed to initialize VLC: {str(e)}")
        
        # Then setup UI
        self.setup_ui()
        
        # Update to use config for last server
        self.server_combo.setCurrentIndex(self.config.get('last_server', 0))
        
        # Set player window - with proper type conversion
        if sys.platform.startswith('linux'):
            handle = self.video_frame.winId().__int__()
            if handle is not None:
                self.media_player.set_xwindow(handle)
        elif sys.platform == "win32":
            self.media_player.set_hwnd(self.video_frame.winId().__int__())
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(self.video_frame.winId().__int__())
        
    def setup_ui(self):
        print("Debug: Setting up UI")
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
        
        # Create actions
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Create toolbar/ribbon
        # toolbar = QToolBar()
        # self.addToolBar(toolbar)
        # settings_btn = QPushButton("Settings")
        # settings_btn.clicked.connect(lambda: print("Debug: Settings button clicked"))
        # toolbar.addWidget(settings_btn)
        
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
        for server in self.servers:
            self.server_combo.addItem(server['name'])
        
        # Connect server combo box change signal
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        
        manage_servers_btn = QPushButton("Manage Servers")
        manage_servers_btn.clicked.connect(self.manage_servers)
        
        server_layout.addWidget(QLabel("Server:"))
        server_layout.addWidget(self.server_combo)
        manage_servers_btn.setText("⚙️")  # Unicode settings icon
        manage_servers_btn.setFixedWidth(32)  # Width matches other icon buttons
        manage_servers_btn.setFixedHeight(self.server_combo.sizeHint().height())  # Match combobox height
        manage_servers_btn.setToolTip("Manage servers")
        server_layout.addWidget(manage_servers_btn)
        left_layout.addLayout(server_layout)
        
        # Channel list
        self.channel_list = QListWidget()
        left_layout.addWidget(QLabel("Channels"))
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
            background-image: radial-gradient(rgb(40, 40, 40) 1px, transparent 1px);
            background-size: 10px 10px;
        """)
        
        right_layout.addWidget(self.video_frame)
        
        # Player controls
        controls_layout = QHBoxLayout()
        
        # Play button
        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setIcon(QIcon(":/icons/play.svg"))
        self.play_btn.setIconSize(QSize(48, 48))
        self.play_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.play_btn.clicked.connect(lambda: self.play_channel(self.channel_list.currentItem()))
        self.play_btn.setToolTip("Play selected channel")
        controls_layout.addWidget(self.play_btn)
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setFixedSize(48, 48)
        self.stop_btn.setIcon(QIcon(":/icons/stop.svg"))
        self.stop_btn.setIconSize(QSize(48, 48))
        self.stop_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_btn.clicked.connect(self.media_player.stop)
        self.stop_btn.setToolTip("Stop playback")
        controls_layout.addWidget(self.stop_btn)
        
        # Start Record button
        self.start_record_btn = QPushButton()
        self.start_record_btn.setFixedSize(48, 48)
        self.start_record_btn.setIcon(QIcon(":/icons/record.svg"))
        self.start_record_btn.setIconSize(QSize(48, 48))
        self.start_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_record_btn.setToolTip("Start Recording")
        self.start_record_btn.clicked.connect(self.start_recording)
        controls_layout.addWidget(self.start_record_btn)

        # Stop Record button 
        self.stop_record_btn = QPushButton()
        self.stop_record_btn.setFixedSize(48, 48)
        self.stop_record_btn.setIcon(QIcon(":/icons/stoprec.svg"))
        self.stop_record_btn.setIconSize(QSize(48, 48))
        self.stop_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_record_btn.setToolTip("Stop Recording")
        self.stop_record_btn.clicked.connect(self.stop_recording)
        controls_layout.addWidget(self.stop_record_btn)
        # Start Local Record button
        self.start_local_record_btn = QPushButton()
        self.start_local_record_btn.setFixedSize(48, 48)
        self.start_local_record_btn.setIcon(QIcon(":/icons/rec-local.svg"))
        self.start_local_record_btn.setIconSize(QSize(48, 48))
        self.start_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.start_local_record_btn.setToolTip("Start Local Recording")
        self.start_local_record_btn.clicked.connect(lambda: self.start_local_recording(self.channel_list.currentItem().text()))
        controls_layout.addWidget(self.start_local_record_btn)

        # Stop Local Record button
        self.stop_local_record_btn = QPushButton()
        self.stop_local_record_btn.setFixedSize(48, 48)
        self.stop_local_record_btn.setIcon(QIcon(":/icons/stoprec-local.svg"))
        self.stop_local_record_btn.setIconSize(QSize(48, 48))
        self.stop_local_record_btn.setStyleSheet("QPushButton { border-radius: 24px; }")
        self.stop_local_record_btn.setToolTip("Stop Local Recording")
        self.stop_local_record_btn.clicked.connect(self.stop_local_recording)
        controls_layout.addWidget(self.stop_local_record_btn)
        # Volume slider and mute button
        self.mute_btn = QPushButton("🔊")  # Unicode speaker icon
        self.mute_btn.setFixedSize(32, 32)
        self.mute_btn.setCheckable(True)
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.mute_btn.setToolTip("Mute")
        self.mute_btn.setStyleSheet("QPushButton { border: none; }")
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(150)  # Set fixed width to make slider less wide
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        
        # Fullscreen button with icon
        fullscreen_btn = QPushButton("⛶")  # Unicode fullscreen icon
        fullscreen_btn.setFixedSize(32, 32)
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
        
        # Button grid - centered in right pane
        grid_layout = QGridLayout()
        grid_layout.setSpacing(0)  # No spacing between buttons
        grid_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        right_layout.addLayout(grid_layout)  # Add to right pane instead of main layout
        
        # Define button size and style
        BUTTON_SIZE = 48
        ICON_SIZE = 48
        button_style = """
            QPushButton { 
                border: none; 
                padding: 8px;
                border-radius: 24px;  /* Makes the button circular */
                background-color: transparent;
            }
            QPushButton:hover { 
                background-color: rgba(255, 255, 255, 0.1);  /* Subtle hover effect */
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.2);  /* Pressed state */
            }
        """
        
        
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
        self.channel_list.itemDoubleClicked.connect(self.play_channel)
        
        # Add event filter to video frame for double-click
        self.video_frame.installEventFilter(self)
        
        # Add key event filter to main window
        self.installEventFilter(self)
        
    def fetch_channels(self):
        """Fetch channel list from current TVHeadend server"""
        while True:  # Loop for retry functionality
            try:
                if not self.servers:
                    print("Debug: No servers configured")
                    self.statusbar.showMessage("No servers configured")
                    return
                    
                server = self.servers[self.server_combo.currentIndex()]
                print(f"Debug: Fetching channels from server: {server['url']}")
                
                # Update status bar
                self.statusbar.showMessage("Connecting to server...")
                
                # Clean and format the URL properly
                url = server['url']
                if url.startswith('https://') or url.startswith('http://'):
                    base_url = url
                else:
                    base_url = f"http://{url}"
                
                api_url = f'{base_url}/api/channel/grid'
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
                
                self.channel_list.clear()
                for channel in channels:
                    self.channel_list.addItem(channel['name'])
                    print(f"Debug: Added channel: {channel['name']}")
                    
                # Select first channel if list is not empty
                if self.channel_list.count() > 0:
                    self.channel_list.setCurrentRow(0)
                    print("Debug: Selected first channel")
                    
                self.statusbar.showMessage("Channels loaded successfully")
                break  # Success - exit the retry loop
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                print(f"Debug: Connection error: {str(e)}")
                error_msg = "Connection timed out" if isinstance(e, requests.exceptions.Timeout) else "Could not connect to server"
                
                # Show error dialog
                dialog = ConnectionErrorDialog(server['name'], error_msg, self)
                if dialog.exec_() == QDialog.Accepted:  # Retry
                    print("Debug: Retrying connection...")
                    continue
                else:  # Abort
                    print("Debug: Connection attempt aborted by user")
                    self.statusbar.showMessage("Connection aborted")
                    self.channel_list.clear()
                    break
                    
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
                if dialog.exec_() == QDialog.Accepted:  # Retry
                    print("Debug: Retrying connection...")
                    continue
                else:  # Abort
                    print("Debug: Connection attempt aborted by user")
                    self.statusbar.showMessage("Connection aborted")
                    self.channel_list.clear()
                    break
        
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
            api_url = f'http://{server["url"]}/api/channel/grid'
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
            record_url = f'http://{server["url"]}/api/dvr/entry/create'
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
        print(f"Debug: Toggling fullscreen. Current state: {self.is_fullscreen}")
        """Toggle fullscreen mode for VLC player"""
        if not self.is_fullscreen:
            # Store the video frame's original parent and layout position
            self.original_parent = self.video_frame.parent()
            self.original_layout = self.findChild(QVBoxLayout, "right_layout")
            
            # Create a new fullscreen window
            self.fullscreen_window = QWidget()
            self.fullscreen_window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.fullscreen_window.installEventFilter(self)  # Add event filter to fullscreen window
            layout = QVBoxLayout(self.fullscreen_window)
            layout.setContentsMargins(0, 0, 0, 0)
            
            # Move video frame to fullscreen
            self.video_frame.setParent(self.fullscreen_window)
            layout.addWidget(self.video_frame)
            
            # Show fullscreen
            self.fullscreen_window.showFullScreen()
            self.video_frame.show()
            
            # Reset VLC window handle for fullscreen
            if sys.platform.startswith('linux'):
                self.media_player.set_xwindow(self.video_frame.winId().__int__())
            elif sys.platform == "win32":
                self.media_player.set_hwnd(self.video_frame.winId().__int__())
            elif sys.platform == "darwin":
                self.media_player.set_nsobject(self.video_frame.winId().__int__())
        else:
            # Remove from fullscreen layout
            self.fullscreen_window.layout().removeWidget(self.video_frame)
            
            # Find the right pane's layout again (in case it was lost)
            right_layout = self.findChild(QVBoxLayout, "right_layout")
            
            # Restore to right pane
            self.video_frame.setParent(self.original_parent)
            right_layout.insertWidget(0, self.video_frame)
            self.video_frame.show()
            
            # Reset VLC window handle for normal view
            if sys.platform.startswith('linux'):
                self.media_player.set_xwindow(self.video_frame.winId().__int__())
            elif sys.platform == "win32":
                self.media_player.set_hwnd(self.video_frame.winId().__int__())
            elif sys.platform == "darwin":
                self.media_player.set_nsobject(self.video_frame.winId().__int__())
            
            # Close fullscreen window
            self.fullscreen_window.close()
            self.fullscreen_window = None
            
        self.is_fullscreen = not self.is_fullscreen
        print(f"Debug: New fullscreen state: {self.is_fullscreen}")

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
            server = self.servers[self.server_combo.currentIndex()]
            server_url = server['url']
            print(f"Debug: Playing channel from server: {server_url}")
            
            # Create auth string if credentials exist
            auth_string = ''
            auth = None
            if server.get('username') or server.get('password'):
                auth = (server.get('username', ''), server.get('password', ''))
                auth_string = f"{server.get('username', '')}:{server.get('password', '')}@"
                print(f"Debug: Using authentication with username: {server.get('username', '')}")
            
            # Find channel UUID with auth
            api_url = f'http://{server["url"]}/api/channel/grid'
            print(f"Debug: Making request to: {api_url}")
            
            response = requests.get(api_url, auth=auth)
            print(f"Debug: Response status code: {response.status_code}")
            print(f"Debug: Response content: {response.text[:200]}...")  # First 200 chars
            
            channels = response.json()['entries']
            channel_name = item.text()
            print(f"Debug: Looking for channel: {channel_name}")
            
            channel_uuid = None
            for channel in channels:
                if channel['name'] == channel_name:
                    channel_uuid = channel['uuid']
                    print(f"Debug: Found channel UUID: {channel_uuid}")
                    break
            
            if channel_uuid:
                # Create media URL with auth if needed
                stream_url = f'http://{auth_string}{server_url}/stream/channel/{channel_uuid}'
                print(f"Debug: Stream URL: {stream_url}")
                
                media = self.instance.media_new(stream_url)
                self.media_player.set_media(media)
                self.media_player.play()
                print(f"Debug: Started playback")
                self.statusbar.showMessage(f"Playing: {channel_name}")
            else:
                print(f"Debug: Channel not found: {channel_name}")
                self.statusbar.showMessage("Channel not found")
                
        except Exception as e:
            print(f"Debug: Error in play_channel: {str(e)}")
            print(f"Debug: Error type: {type(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            self.statusbar.showMessage(f"Playback error: {str(e)}")

    def on_server_changed(self, index):
        """Handle server change"""
        print(f"Debug: Server changed to index {index}")
        if index >= 0:  # Valid index
            print(f"Debug: Switching to server: {self.servers[index]['name']}")
            # Save the current server index
            try:
                with open('last_server.txt', 'w') as f:
                    f.write(str(index))
                print(f"Debug: Saved server index: {index}")
            except Exception as e:
                print(f"Debug: Error saving server index: {e}")
            # Fetch channels for new server
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
            "TVHplayer\n\n"
            "A simple TVHeadend client application.\n"
            f"Version {__version__}\n\n"
            "Created with Python, PyQt5, and VLC."
        )
        QMessageBox.about(self, "About TVHplayer", about_text)

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
            api_url = f'http://{server["url"]}/api/dvr/entry/grid'
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
                stop_url = f'http://{server["url"]}/api/dvr/entry/stop'
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

    def show_dvr_manager(self):
        pass

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
            api_url = f'http://{server["url"]}/api/channel/grid'
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

    def setup_video_widget(self):
        """Set up the video widget"""
        self.video_widget = QWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        
        # Enable mouse tracking
        self.video_widget.setMouseTracking(True)
        
        # Connect double click signal using mouseDoubleClickEvent
        self.video_widget.mouseDoubleClickEvent = self.video_double_clicked
        
        # Make the widget accept mouse events directly
        self.video_widget.setAttribute(Qt.WA_AcceptTouchEvents)
        self.video_widget.setFocusPolicy(Qt.StrongFocus)

    def video_double_clicked(self, event):
        """Handle double click on video widget"""
        print("Debug: Video double clicked")
        if event.button() == Qt.LeftButton:
            if self.is_fullscreen:
                print("Debug: Exiting fullscreen")
                self.showNormal()
                self.is_fullscreen = False
            else:
                print("Debug: Entering fullscreen")
                self.showFullScreen()
                self.is_fullscreen = True
            event.accept()

class RecordingDurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recording Duration")
        self.setModal(True)
        self.duration = 3600  # Default 1 hour in seconds
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Radio buttons for preset durations
        self.radio_30min = QRadioButton("30 minutes")
        self.radio_1hour = QRadioButton("1 hour")
        self.radio_2hours = QRadioButton("2 hours")
        self.radio_4hours = QRadioButton("4 hours")
        self.radio_custom = QRadioButton("Custom duration")
        
        # Set 1 hour as default
        self.radio_1hour.setChecked(True)
        
        # Custom duration input (initially disabled)
        self.custom_layout = QHBoxLayout()
        self.custom_hours = QSpinBox()
        self.custom_hours.setRange(0, 24)
        self.custom_minutes = QSpinBox()
        self.custom_minutes.setRange(0, 59)
        self.custom_layout.addWidget(QLabel("Hours:"))
        self.custom_layout.addWidget(self.custom_hours)
        self.custom_layout.addWidget(QLabel("Minutes:"))
        self.custom_layout.addWidget(self.custom_minutes)
        
        # Enable/disable custom inputs based on radio selection
        self.radio_custom.toggled.connect(self.toggle_custom_duration)
        
        # Add all widgets to layout
        layout.addWidget(self.radio_30min)
        layout.addWidget(self.radio_1hour)
        layout.addWidget(self.radio_2hours)
        layout.addWidget(self.radio_4hours)
        layout.addWidget(self.radio_custom)
        layout.addLayout(self.custom_layout)
        
        # Add OK/Cancel buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Initially disable custom inputs
        self.toggle_custom_duration(False)
        
    def toggle_custom_duration(self, enabled):
        self.custom_hours.setEnabled(enabled)
        self.custom_minutes.setEnabled(enabled)
        
    def get_duration(self):
        """Returns duration in seconds"""
        if self.radio_30min.isChecked():
            return 30 * 60
        elif self.radio_1hour.isChecked():
            return 60 * 60
        elif self.radio_2hours.isChecked():
            return 2 * 60 * 60
        elif self.radio_4hours.isChecked():
            return 4 * 60 * 60
        else:  # Custom duration
            hours = self.custom_hours.value()
            minutes = self.custom_minutes.value()
            return (hours * 60 * 60) + (minutes * 60)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TVHeadendClient()
    window.show()
    sys.exit(app.exec_())

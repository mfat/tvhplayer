from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QShortcut,
    QMessageBox, QProgressBar, QComboBox, QCheckBox
)
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
import json
import base64
import requests
from datetime import datetime, timedelta

class EPGWindow(QDialog):
    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server
        self.setWindowTitle("Electronic Program Guide")
        self.resize(900, 600)
        self.entries = []
        self.total_count = 0
        self.current_page = 0
        self.page_size = 100  # Reduced from 500 to 100 for faster initial load
        self.network_manager = QNetworkAccessManager()
        self.api_version = None
        self.setup_ui()
        
        # Use a timer to allow the UI to show before fetching data
        QTimer.singleShot(100, self.check_api_version)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Search and filter options at the top
        top_layout = QHBoxLayout()
        
        # Search bar
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search program titles (Ctrl+F)")
        self.search_box.textChanged.connect(self.filter_epg)
        
        # Add search shortcut
        search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        search_shortcut.activated.connect(self.search_box.setFocus)
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        top_layout.addLayout(search_layout, 3)
        
        # Time filter
        time_filter_layout = QHBoxLayout()
        time_filter_label = QLabel("Time Range:")
        self.time_filter = QComboBox()
        self.time_filter.addItem("All", "all")
        self.time_filter.addItem("Now", "now")
        self.time_filter.addItem("Next 3 Hours", "3h")
        self.time_filter.addItem("Next 6 Hours", "6h")
        self.time_filter.addItem("Today", "today")
        self.time_filter.currentIndexChanged.connect(lambda: self.fetch_epg(True))
        
        time_filter_layout.addWidget(time_filter_label)
        time_filter_layout.addWidget(self.time_filter)
        top_layout.addLayout(time_filter_layout, 1)
        
        layout.addLayout(top_layout)
        
        # EPG Table
        self.epg_table = QTableWidget()
        self.epg_table.setColumnCount(5)
        self.epg_table.setHorizontalHeaderLabels(['Channel', 'Start Time', 'End Time', 'Title', 'Description'])
        self.epg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.epg_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.epg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.epg_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.epg_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.epg_table.verticalHeader().setVisible(False)
        self.epg_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.epg_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.epg_table.setSortingEnabled(True)
        self.epg_table.itemDoubleClicked.connect(self.on_epg_item_double_clicked)
        layout.addWidget(self.epg_table)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status bar
        self.status_label = QLabel("Loading EPG data...")
        layout.addWidget(self.status_label)
        
        # Buttons at the bottom
        button_layout = QHBoxLayout()
        
        # Add Schedule Recording button
        self.record_btn = QPushButton("Schedule Recording")
        self.record_btn.setIcon(QIcon("icons/record.svg"))
        self.record_btn.clicked.connect(self.schedule_selected_recording)
        button_layout.addWidget(self.record_btn)
        
        # Add load more button
        self.load_more_btn = QPushButton("Load More")
        self.load_more_btn.clicked.connect(self.load_more)
        self.load_more_btn.setEnabled(False)
        button_layout.addWidget(self.load_more_btn)
        
        # Add refresh and close buttons
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(lambda: self.fetch_epg(True))
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        
        button_layout.addWidget(self.refresh_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)
    
    def check_api_version(self):
        """Check the TVHeadend API version to adjust requests accordingly"""
        if not self.server or self.server.get('type') != 'tvheadend':
            self.fetch_epg()
            return
            
        url = self.server.get('url', '')
        username = self.server.get('username', '')
        password = self.server.get('password', '')
        
        if not url:
            self.fetch_epg()
            return
            
        # Set up authentication
        auth = None
        if username and password:
            auth = (username, password)
            
        try:
            # Try to get server info
            api_url = f"{url}/api/serverinfo"
            print(f"Debug: Checking API version at: {api_url}")
            
            response = requests.get(api_url, auth=auth, timeout=5)
            if response.status_code == 200:
                server_info = response.json()
                self.api_version = server_info.get('api_version', '0')
                print(f"Debug: TVHeadend API version: {self.api_version}")
            else:
                print(f"Debug: Failed to get API version, status code: {response.status_code}")
        except Exception as e:
            print(f"Debug: Error checking API version: {str(e)}")
            
        # Proceed with EPG fetch
        self.fetch_epg()
    
    def fetch_epg(self, reset=False):
        """Fetch EPG data from the TVHeadend server"""
        if reset:
            self.current_page = 0
            self.entries = []
            self.epg_table.setRowCount(0)
            
        self.status_label.setText("Loading EPG data...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Only proceed if we have a valid TVHeadend server
        if not self.server or self.server.get('type') != 'tvheadend':
            self.status_label.setText("EPG is only available for TVHeadend servers")
            self.progress_bar.setVisible(False)
            return
        
        # Get server details
        url = self.server.get('url', '')
        username = self.server.get('username', '')
        password = self.server.get('password', '')
        
        if not url:
            self.status_label.setText("Invalid server URL")
            self.progress_bar.setVisible(False)
            return
        
        # Set up parameters
        params = {
            "limit": self.page_size,
            "start": self.current_page * self.page_size
        }
        
        # Add time filter if selected
        time_filter = self.time_filter.currentData()
        if time_filter != "all":
            now = datetime.now()
            
            if time_filter == "now":
                # Current programs
                params["start_time"] = int(now.timestamp())
                params["end_time"] = int(now.timestamp())
            elif time_filter == "3h":
                # Next 3 hours
                params["start_time"] = int(now.timestamp())
                params["end_time"] = int((now + timedelta(hours=3)).timestamp())
            elif time_filter == "6h":
                # Next 6 hours
                params["start_time"] = int(now.timestamp())
                params["end_time"] = int((now + timedelta(hours=6)).timestamp())
            elif time_filter == "today":
                # Today until midnight
                today_end = now.replace(hour=23, minute=59, second=59)
                params["start_time"] = int(now.timestamp())
                params["end_time"] = int(today_end.timestamp())
        
        # Try all methods in sequence without delays
        self.try_all_fetch_methods(url, username, password, params)
    
    def try_all_fetch_methods(self, url, username, password, params):
        """Try all available fetch methods in sequence"""
        # First try the main endpoint with requests
        try:
            self.status_label.setText("Loading EPG data...")
            self.fetch_epg_with_requests(url, username, password, params)
            return
        except Exception as e:
            print(f"Debug: Main endpoint failed: {str(e)}")
        
        # Then try alternative endpoints
        try:
            self.status_label.setText("Loading EPG data (alternative method)...")
            self.try_alternative_endpoint(url, username, password, params)
            return
        except Exception as e:
            print(f"Debug: Alternative endpoints failed: {str(e)}")
        
        # Finally fall back to QNetworkAccessManager
        self.status_label.setText("Loading EPG data (final attempt)...")
        self.fetch_epg_with_qnetwork(url, username, password, params)
    
    def fetch_epg_with_requests(self, url, username, password, params):
        """Fetch EPG data using the requests library"""
        # Try the main API endpoint first
        api_url = f"{url}/api/epg/events/grid"
        
        # Adjust parameters based on API version
        if self.api_version:
            # For newer versions (4+), we might need to adjust parameters
            if self.api_version.startswith('4') or self.api_version.startswith('5'):
                # Some versions might require different parameter names
                if 'start_time' in params:
                    params['start'] = params.pop('start_time')
                if 'end_time' in params:
                    params['end'] = params.pop('end_time')
        
        # Set up authentication
        auth = None
        if username and password:
            auth = (username, password)
        
        print(f"Debug: Fetching EPG data from: {api_url} with params: {params}")
        
        # Make the request
        try:
            response = requests.get(api_url, params=params, auth=auth, timeout=15)
            
            # Check if request was successful
            if response.status_code == 200:
                try:
                    # Parse JSON response
                    json_data = response.json()
                    self.process_epg_data(json_data)
                except json.JSONDecodeError as e:
                    print(f"Debug: JSON decode error: {str(e)}")
                    print(f"Debug: Response data: {response.text[:200]}")
                    
                    # Try alternative endpoint
                    self.try_alternative_endpoint(url, username, password, params)
            else:
                print(f"Debug: HTTP error: {response.status_code}")
                print(f"Debug: Response: {response.text[:200]}")
                
                # Try alternative endpoint
                self.try_alternative_endpoint(url, username, password, params)
        except requests.exceptions.RequestException as e:
            print(f"Debug: Request exception: {str(e)}")
            
            # Try alternative endpoint
            self.try_alternative_endpoint(url, username, password, params)
    
    def try_alternative_endpoint(self, url, username, password, params):
        """Try an alternative API endpoint for EPG data"""
        # Alternative endpoints to try
        alternative_endpoints = [
            "/api/epg/events/list",  # Some versions use this
            "/api/epg/query"         # Older versions might use this
        ]
        
        # Set up authentication
        auth = None
        if username and password:
            auth = (username, password)
        
        last_error = None
        for endpoint in alternative_endpoints:
            try:
                api_url = f"{url}{endpoint}"
                print(f"Debug: Trying alternative endpoint: {api_url}")
                
                response = requests.get(api_url, params=params, auth=auth, timeout=15)
                
                if response.status_code == 200:
                    try:
                        json_data = response.json()
                        
                        # Check if we got a valid response with entries
                        if 'entries' in json_data or 'events' in json_data:
                            # Normalize the response format
                            if 'events' in json_data and 'entries' not in json_data:
                                json_data['entries'] = json_data['events']
                                
                            print(f"Debug: Alternative endpoint {endpoint} succeeded")
                            self.process_epg_data(json_data)
                            return
                    except json.JSONDecodeError as e:
                        print(f"Debug: Alternative endpoint {endpoint} returned invalid JSON")
                        last_error = e
                else:
                    print(f"Debug: Alternative endpoint {endpoint} failed with status {response.status_code}")
                    last_error = Exception(f"HTTP error {response.status_code}")
            except Exception as e:
                print(f"Debug: Error with alternative endpoint {endpoint}: {str(e)}")
                last_error = e
        
        # If we get here, all alternatives failed
        if last_error:
            raise Exception(f"All alternative endpoints failed: {str(last_error)}")
        else:
            raise Exception("All alternative endpoints failed")
    
    def fetch_epg_with_qnetwork(self, url, username, password, params):
        """Fetch EPG data using QNetworkAccessManager"""
        # Prepare the API endpoint
        api_url = f"{url}/api/epg/events/grid"
        
        # Create a network request
        request = QNetworkRequest(QUrl(api_url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        
        # Add authentication if provided
        if username and password:
            auth_string = f"{username}:{password}"
            auth_bytes = auth_string.encode('utf-8')
            auth_header = b"Basic " + base64.b64encode(auth_bytes)
            request.setRawHeader(b"Authorization", auth_header)
        
        # Convert parameters to query string
        query_items = []
        for key, value in params.items():
            query_items.append(f"{key}={value}")
        query_string = "&".join(query_items)
        
        # Set the final URL with parameters
        final_url = f"{api_url}?{query_string}"
        request.setUrl(QUrl(final_url))
        
        print(f"Debug: Fetching EPG data from: {final_url}")
        
        # Disconnect any previous connections to avoid multiple handlers
        try:
            self.network_manager.finished.disconnect()
        except:
            pass
            
        # Connect to finished signal
        self.network_manager.finished.connect(self.handle_epg_response)
        
        # Send the request
        self.network_manager.get(request)
    
    def handle_epg_response(self, reply):
        """Handle the EPG API response"""
        error = reply.error()
        
        if error == QNetworkReply.NoError:
            # Read the response data
            response_data = reply.readAll().data()
            
            try:
                # Print first 200 characters of response for debugging
                print(f"Debug: Response preview: {response_data[:200]}")
                
                # Parse JSON response
                json_data = json.loads(response_data)
                self.process_epg_data(json_data)
                
            except json.JSONDecodeError as e:
                print(f"Debug: JSON decode error: {str(e)}")
                print(f"Debug: Response data: {response_data}")
                self.status_label.setText("Could not load EPG data. Please try again.")
                self.progress_bar.setVisible(False)
        else:
            error_msg = reply.errorString()
            print(f"Debug: Network error: {error_msg}")
            self.status_label.setText("Could not connect to the server. Please check your connection.")
            self.progress_bar.setVisible(False)
    
    def process_epg_data(self, json_data):
        """Process the EPG data from either fetch method"""
        try:
            new_entries = json_data.get('entries', [])
            self.total_count = json_data.get('totalCount', 0)
            
            print(f"Debug: Received {len(new_entries)} entries, total count: {self.total_count}")
            
            # Add new entries to our list
            self.entries.extend(new_entries)
            
            # Update the progress bar
            loaded_percent = min(100, int((len(self.entries) / max(1, self.total_count)) * 100))
            self.progress_bar.setValue(loaded_percent)
            
            # Update the table with EPG data
            start_row = self.epg_table.rowCount()
            self.epg_table.setRowCount(start_row + len(new_entries))
            
            for i, entry in enumerate(new_entries):
                row = start_row + i
                
                # Channel name
                channel_name = entry.get('channelName', 'Unknown')
                self.epg_table.setItem(row, 0, QTableWidgetItem(channel_name))
                
                # Start time
                start_timestamp = entry.get('start', 0)
                start_time = datetime.fromtimestamp(start_timestamp).strftime('%Y-%m-%d %H:%M')
                self.epg_table.setItem(row, 1, QTableWidgetItem(start_time))
                
                # End time
                stop_timestamp = entry.get('stop', 0)
                stop_time = datetime.fromtimestamp(stop_timestamp).strftime('%Y-%m-%d %H:%M')
                self.epg_table.setItem(row, 2, QTableWidgetItem(stop_time))
                
                # Title
                title = entry.get('title', 'Unknown')
                self.epg_table.setItem(row, 3, QTableWidgetItem(title))
                
                # Description (use summary or subtitle)
                description = entry.get('summary', entry.get('subtitle', ''))
                self.epg_table.setItem(row, 4, QTableWidgetItem(description))
                
                # Store the full entry data in the first column for reference
                self.epg_table.item(row, 0).setData(Qt.UserRole, entry)
            
            # Update status and load more button
            if len(new_entries) > 0:
                self.status_label.setText(f"Loaded {len(self.entries)} of {self.total_count} EPG entries")
                self.load_more_btn.setEnabled(len(self.entries) < self.total_count)
            else:
                self.status_label.setText("No EPG entries found for the selected time range")
                self.load_more_btn.setEnabled(False)
            
            # Apply any existing filter
            if self.search_box.text():
                self.filter_epg()
            
            # Hide progress bar if we've loaded all entries
            if len(self.entries) >= self.total_count:
                self.progress_bar.setVisible(False)
                
        except Exception as e:
            print(f"Debug: Error processing EPG data: {str(e)}")
            self.status_label.setText("Could not load EPG data. Please try again.")
            self.progress_bar.setVisible(False)
    
    def load_more(self):
        """Load more EPG entries"""
        if len(self.entries) < self.total_count:
            self.current_page += 1
            self.fetch_epg()
    
    def filter_epg(self):
        """Filter EPG entries based on search text"""
        search_text = self.search_box.text().lower()
        
        for row in range(self.epg_table.rowCount()):
            match = False
            
            # Check title and description columns
            title_item = self.epg_table.item(row, 3)
            desc_item = self.epg_table.item(row, 4)
            
            if title_item and search_text in title_item.text().lower():
                match = True
            elif desc_item and search_text in desc_item.text().lower():
                match = True
            
            # Show/hide row based on match
            self.epg_table.setRowHidden(row, not match) if search_text else self.epg_table.setRowHidden(row, False)
    
    def on_epg_item_double_clicked(self, item):
        """Handle double-click on EPG item"""
        row = item.row()
        channel_item = self.epg_table.item(row, 0)
        
        if channel_item:
            # Get the full entry data
            entry_data = channel_item.data(Qt.UserRole)
            if entry_data:
                channel_name = entry_data.get('channelName')
                channel_uuid = entry_data.get('channelUuid')
                
                if channel_name and channel_uuid:
                    # Emit signal to play this channel
                    self.parent().play_channel_by_uuid(channel_uuid)
                    self.close()
    
    def schedule_selected_recording(self):
        """Schedule recording for the selected EPG entry"""
        # Get the selected row
        selected_rows = self.epg_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a program to record")
            return
            
        # Get the entry data from the first selected row
        row = selected_rows[0].row()
        channel_item = self.epg_table.item(row, 0)
        
        if channel_item:
            entry = channel_item.data(Qt.UserRole)
            if entry:
                self.schedule_recording(entry)
    
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
                    "eng": entry.get('summary', entry.get('subtitle', ''))
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
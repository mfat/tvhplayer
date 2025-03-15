from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QShortcut,
    QMessageBox
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
import json
import base64
import requests
from datetime import datetime

class EPGWindow(QDialog):
    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server
        self.setWindowTitle("Electronic Program Guide")
        self.resize(900, 600)
        self.setup_ui()
        self.fetch_epg()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Search bar at the top
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
        layout.addLayout(search_layout)
        
        # EPG Table
        self.epg_table = QTableWidget()
        self.epg_table.setColumnCount(5)  # Back to 5 columns
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
        
        # Add refresh and close buttons
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.fetch_epg)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        
        button_layout.addWidget(self.refresh_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)
    
    def fetch_epg(self):
        """Fetch EPG data from the TVHeadend server"""
        self.status_label.setText("Loading EPG data...")
        self.epg_table.setRowCount(0)
        
        # Only proceed if we have a valid TVHeadend server
        if not self.server or self.server.get('type') != 'tvheadend':
            self.status_label.setText("EPG is only available for TVHeadend servers")
            return
        
        # Get server details
        url = self.server.get('url', '')
        username = self.server.get('username', '')
        password = self.server.get('password', '')
        
        if not url:
            self.status_label.setText("Invalid server URL")
            return
        
        # Prepare the API endpoint
        api_url = f"{url}/api/epg/events/grid"
        
        # Create a network request
        request = QNetworkRequest(QUrl(api_url))
        
        # Add authentication if provided
        if username and password:
            auth_string = f"{username}:{password}"
            auth_bytes = auth_string.encode('utf-8')
            auth_header = b"Basic " + base64.b64encode(auth_bytes)
            request.setRawHeader(b"Authorization", auth_header)
        
        # Set up parameters
        params = {
            "limit": 500,  # Fetch up to 500 entries
            "start": 0
        }
        
        # Convert parameters to query string
        query_items = []
        for key, value in params.items():
            query_items.append(f"{key}={value}")
        query_string = "&".join(query_items)
        
        # Set the final URL with parameters
        final_url = f"{api_url}?{query_string}"
        request.setUrl(QUrl(final_url))
        
        # Create network manager and connect to finished signal
        self.network_manager = QNetworkAccessManager()
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
                # Parse JSON response
                json_data = json.loads(response_data)
                entries = json_data.get('entries', [])
                total_count = json_data.get('totalCount', 0)
                
                # Update the table with EPG data
                self.epg_table.setRowCount(len(entries))
                
                for row, entry in enumerate(entries):
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
                
                self.status_label.setText(f"Loaded {len(entries)} of {total_count} EPG entries")
                
            except json.JSONDecodeError:
                self.status_label.setText("Error: Invalid response from server")
        else:
            self.status_label.setText(f"Error: {reply.errorString()}")
    
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
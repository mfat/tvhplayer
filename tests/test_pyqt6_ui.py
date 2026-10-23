import ast
import os
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / 'tvhplayer' / 'tvhplayer.py'


def test_ui_module_parses():
    ast.parse(UI_PATH.read_text(encoding='utf-8'))


def test_ui_module_uses_pyqt6(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setitem(
        sys.modules,
        'vlc',
        types.SimpleNamespace(Instance=lambda *a, **k: None, MediaStats=object, __version__='stub'),
    )
    sys.modules.pop('tvhplayer.tvhplayer', None)

    import tvhplayer.tvhplayer as ui

    assert ui.QAction.__module__ == 'PyQt6.QtGui'
    assert ui.QShortcut.__module__ == 'PyQt6.QtGui'
    assert not hasattr(ui.QApplication, 'exec_')
    assert ui.ConfigStore is not None
    assert ui.LocalRecorder is not None

    from PyQt6.QtWidgets import QApplication, QDialogButtonBox

    app = QApplication.instance() or QApplication([])
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    assert box.buttons()

    duration = ui.RecordingDurationDialog()
    duration.set_duration(1, 30)
    assert duration.get_duration() == 5400

    config_dialog = ui.ServerConfigDialog()
    config_dialog.set_server_config({
        'name': 'local',
        'url': 'http://127.0.0.1:9981',
        'protocol': 'htsp',
        'htsp_port': 9982,
    })
    assert config_dialog.get_server_config()['protocol'] == 'htsp'

    error_dialog = ui.ConnectionErrorDialog('local', 'connection refused')
    assert error_dialog.windowTitle() == 'Connection Error'

    app.processEvents()


class _FakeEvents:
    def __init__(self):
        self.handlers = {}

    def event_attach(self, event_type, callback):
        self.handlers[event_type] = callback


class _FakeVlcPlayer:
    def __init__(self):
        self.key_input = None
        self.mouse_input = None
        self._muted = 0
        self._playing = False
        self._events = _FakeEvents()

    def event_manager(self):
        return self._events

    def set_xwindow(self, handle):
        return None

    def set_hwnd(self, handle):
        return None

    def set_nsobject(self, handle):
        return None

    def set_hardware_decoding(self, value):
        return None

    def video_set_key_input(self, value):
        self.key_input = value

    def video_set_mouse_input(self, value):
        self.mouse_input = value

    def audio_get_mute(self):
        return self._muted

    def audio_set_mute(self, value):
        self._muted = value

    def audio_set_volume(self, value):
        return None

    def is_playing(self):
        return self._playing

    def stop(self):
        self._playing = False

    def play(self):
        self._playing = True

    def set_media(self, media):
        return None

    def get_media(self):
        return None


def _make_player(monkeypatch, tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    fake_player = _FakeVlcPlayer()
    fake_instance = types.SimpleNamespace(
        media_player_new=lambda: fake_player,
        media_new=lambda url: object(),
    )
    monkeypatch.setitem(
        sys.modules,
        'vlc',
        types.SimpleNamespace(
            Instance=lambda *a, **k: fake_instance,
            MediaStats=object,
            EventType=types.SimpleNamespace(
                MediaPlayerPlaying='playing',
                MediaPlayerStopped='stopped',
                MediaPlayerEndReached='ended',
                MediaPlayerEncounteredError='error',
            ),
            __version__='stub',
        ),
    )
    sys.modules.pop('tvhplayer.tvhplayer', None)
    import tvhplayer.tvhplayer as ui

    from tvhplayer.core.config import ConfigStore

    store = ConfigStore(tmp_path / 'tvhplayer.conf')
    monkeypatch.setattr(ui, 'ConfigStore', lambda *a, **k: store)
    monkeypatch.setattr(ui.TVHeadendClient, 'fetch_channels', lambda self: None)

    from PyQt6.QtWidgets import QApplication

    from PyQt6.QtCore import Qt

    app = QApplication.instance() or QApplication([])
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
    window = ui.TVHeadendClient()
    return app, ui, window, fake_player


def test_same_window_fullscreen_hides_chrome(monkeypatch, tmp_path):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        assert fake_player.mouse_input is False
        assert fake_player.key_input is False
        assert window.video_frame.parent() is window.player_container
        assert 'background-image' not in window.video_frame.styleSheet()
        assert window.idle_splash.isVisible()
        assert window.left_pane.isVisible()
        assert window.tasks_pane.isVisible()
        assert window.controls_bar.isVisible()
        assert not window.is_fullscreen
        windowed_frame = window.right_pane.frameStyle()
        windowed_handle = window.splitter.handleWidth()

        window.toggle_fullscreen()
        app.processEvents()

        assert window.is_fullscreen
        assert window.video_frame.parent() is window.player_container
        assert window.idle_splash.isVisible()
        assert not window.left_pane.isVisible()
        assert not window.tasks_pane.isVisible()
        assert not window.controls_bar.isVisible()
        assert not window.menuBar().isVisible()
        assert window.right_pane.frameStyle() == int(ui.QFrame.Shape.NoFrame)
        assert window.right_layout.contentsMargins().left() == 0
        assert window.main_layout.contentsMargins().left() == 0
        assert window.splitter.handleWidth() == 0
        assert window.fullscreen_action.isChecked()
        assert window.fullscreen_action.text() == 'Exit Fullscreen'

        escape = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        window.keyPressEvent(escape)
        app.processEvents()

        assert not window.is_fullscreen
        assert window.left_pane.isVisible()
        assert window.tasks_pane.isVisible()
        assert window.controls_bar.isVisible()
        assert window.menuBar().isVisible()
        assert window.right_pane.frameStyle() == windowed_frame
        assert window.splitter.handleWidth() == windowed_handle
        assert not window.fullscreen_action.isChecked()
        assert window.fullscreen_action.text() == 'Fullscreen'
    finally:
        window.close()
        app.processEvents()


def test_video_context_menu_and_double_click(monkeypatch, tmp_path):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        assert (
            window.video_frame.contextMenuPolicy()
            == ui.Qt.ContextMenuPolicy.CustomContextMenu
        )

        menu = window._video_context_menu()
        labels = [action.text() for action in menu.actions() if not action.isSeparator()]
        assert labels == [
            'Play',
            'Stop',
            'Mute',
            'Fullscreen',
            'Record',
            'Record Locally',
            'Show EPG',
        ]
        enabled = {
            action.text(): action.isEnabled()
            for action in menu.actions()
            if not action.isSeparator()
        }
        assert enabled['Play'] is False
        assert enabled['Stop'] is False
        assert enabled['Mute'] is True
        assert enabled['Fullscreen'] is True

        fake_player._playing = True
        fake_player._muted = 1
        window.is_fullscreen = True
        playing_menu = window._video_context_menu()
        playing_labels = [
            action.text()
            for action in playing_menu.actions()
            if not action.isSeparator()
        ]
        assert 'Unmute' in playing_labels
        assert 'Exit Fullscreen' in playing_labels
        assert playing_menu.actions()[1].isEnabled() is True  # Stop

        click = QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.is_fullscreen = False
        consumed = window.eventFilter(window.video_frame, click)
        app.processEvents()
        assert consumed is True
        assert window.is_fullscreen
        assert window.video_frame.parent() is window.player_container
        assert 'background-image' not in window.video_frame.styleSheet()

        window._protect_video_surface(True)
        app.processEvents()
        assert not window.idle_splash.isVisible()
        assert not window.video_frame.updatesEnabled()
        window.toggle_fullscreen()
        app.processEvents()
        assert not window.idle_splash.isVisible()
        assert not window.video_frame.updatesEnabled()
    finally:
        window.close()
        app.processEvents()


def test_playback_surface_ignores_transient_stop_and_qt_paints(monkeypatch, tmp_path):
    from PyQt6.QtCore import QPoint, QRect, Qt
    from PyQt6.QtGui import QPaintEvent

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        window._protect_video_surface(True)
        assert window._playback_active
        assert not window.idle_splash.isVisible()
        assert not window.video_frame.updatesEnabled()

        paint = QPaintEvent(QRect(0, 0, 10, 10))
        assert window.eventFilter(window.video_frame, paint) is True

        fake_player._events.handlers['stopped'](None)
        app.processEvents()
        assert not window.idle_splash.isVisible()
        assert window._playback_active

        window.show_video_context_menu(QPoint(8, 8))
        app.processEvents()
        menu = window._video_menu
        assert menu is not None
        assert menu.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert bool(menu.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        assert not window.idle_splash.isVisible()
        menu.hide()

        window.stop_playback()
        app.processEvents()
        assert not window._playback_active
        assert window.idle_splash.isVisible()
        assert window.video_frame.updatesEnabled()
    finally:
        window.close()
        app.processEvents()


def test_spinner_shows_until_playback_starts(monkeypatch, tmp_path):
    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        assert window.idle_splash.isVisible()
        assert not window.playback_spinner.isVisible()

        class Backend:
            def stream_url(self, channel):
                return 'http://tv.example/stream'

        window.get_backend = lambda: Backend()
        window.play_channel_by_data(ui.Channel(uuid='news', name='News'))
        app.processEvents()

        assert window._awaiting_playback
        assert window.playback_spinner.isVisible()
        assert window.playback_spinner._timer.isActive()
        assert window.idle_splash.isVisible()
        assert window.status_label.text() == 'Starting: News'
        image = window.playback_spinner.grab().toImage()
        assert image.width() > 0
        assert any(
            image.pixelColor(x, image.height() // 2).red() > 200
            for x in range(image.width())
        )

        fake_player._events.handlers['playing'](None)
        app.processEvents()

        assert not window._awaiting_playback
        assert not window.playback_spinner.isVisible()
        assert not window.playback_spinner._timer.isActive()
        assert not window.idle_splash.isVisible()
        assert window.status_label.text() == 'Playing: News'

        window.play_channel_by_data(ui.Channel(uuid='news', name='News'))
        app.processEvents()
        assert window.playback_spinner.isVisible()
        fake_player._events.handlers['error'](None)
        app.processEvents()

        assert not window.playback_spinner.isVisible()
        assert window.idle_splash.isVisible()
        assert window.status_label.text() == 'Playback failed'
    finally:
        window.close()
        app.processEvents()


def _channel_row(table, name):
    for row in range(table.rowCount()):
        item = table.item(row, 1)
        if item is not None and item.text() == name:
            return row
    return -1


def test_channel_list_marks_the_playing_channel(monkeypatch, tmp_path):
    from PyQt6.QtCore import Qt

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        news = ui.Channel(uuid='news', name='News', number=1)
        sport = ui.Channel(uuid='sport', name='Sport', number=2)

        class Backend:
            def get_channels(self):
                return [news, sport]

            def stream_url(self, channel):
                return f'http://tv.example/stream/{channel.uuid}'

        window.get_backend = lambda: Backend()
        window.servers = [{
            'name': 'local',
            'url': 'http://127.0.0.1:9981',
            'protocol': 'http',
        }]
        window.server_combo.blockSignals(True)
        window.server_combo.addItem('local')
        window.server_combo.setCurrentIndex(0)
        window.server_combo.blockSignals(False)

        monkeypatch.undo()
        window.fetch_channels()
        app.processEvents()

        news_row = _channel_row(window.channel_list, 'News')
        sport_row = _channel_row(window.channel_list, 'Sport')
        assert news_row >= 0 and sport_row >= 0
        assert window.channel_list.item(news_row, 2).text() == ""
        assert window.channel_list.item(sport_row, 2).text() == ""

        window.play_channel_by_data(sport)
        app.processEvents()

        assert window.channel_list.currentRow() == sport_row
        assert window.channel_list.item(sport_row, 2).text() == "Playing"
        assert window.channel_list.item(sport_row, 2).data(
            Qt.ItemDataRole.AccessibleTextRole
        ) == "Playing"
        assert "Playing." in window.channel_list.item(sport_row, 1).data(
            Qt.ItemDataRole.AccessibleDescriptionRole
        )
        assert window.channel_list.item(news_row, 2).text() == ""
        colors = ui.row_emphasis('playing')
        if colors is not None:
            assert window.channel_list.item(sport_row, 1).background().color().name() == colors[0].name()
            assert window.channel_list.item(sport_row, 0).foreground().color().name() == colors[1].name()

        window.channel_list.setCurrentCell(news_row, 1)
        app.processEvents()
        assert window.channel_list.item(sport_row, 2).text() == "Playing"
        assert window.channel_list.item(news_row, 2).text() == ""

        window.fetch_channels()
        app.processEvents()
        sport_row = _channel_row(window.channel_list, 'Sport')
        news_row = _channel_row(window.channel_list, 'News')
        assert window.channel_list.item(sport_row, 2).text() == "Playing"
        assert window.channel_list.currentRow() == sport_row

        window.stop_playback()
        app.processEvents()
        assert window.channel_list.item(sport_row, 2).text() == ""
        assert window.channel_list.item(sport_row, 1).background().style() == Qt.BrushStyle.NoBrush
        assert "Playing." not in window.channel_list.item(sport_row, 1).data(
            Qt.ItemDataRole.AccessibleDescriptionRole
        )

        window.play_channel_by_data(news)
        app.processEvents()
        news_row = _channel_row(window.channel_list, 'News')
        assert window.channel_list.item(news_row, 2).text() == "Playing"
        fake_player._events.handlers['error'](None)
        app.processEvents()
        assert window.channel_list.item(news_row, 2).text() == ""
    finally:
        window.close()
        app.processEvents()


def test_dvr_status_dialog_stops_selected_recording(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setitem(
        sys.modules,
        'vlc',
        types.SimpleNamespace(Instance=lambda *a, **k: None, MediaStats=object, __version__='stub'),
    )
    sys.modules.pop('tvhplayer.tvhplayer', None)

    import tvhplayer.tvhplayer as ui
    from PyQt6.QtWidgets import QApplication, QWidget
    from tvhplayer.core.models import DvrEntry

    app = QApplication.instance() or QApplication([])

    class FakeBackend:
        def __init__(self):
            self.stopped = []
            self.entries = [
                DvrEntry(
                    uuid='soon', title='Later', channel_name='BBC', start=100, duration=60,
                    status='Scheduled', sched_status='scheduled',
                ),
                DvrEntry(
                    uuid='run', title='News', channel_name='IRINN', start=200, duration=60,
                    status='Running', sched_status='recording', htsp_id=7,
                ),
                DvrEntry(
                    uuid='done', title='Old', channel_name='BBC', start=50, duration=60,
                    status='Completed',
                ),
            ]

        def list_dvr_entries(self):
            return list(self.entries)

        def stop_dvr_entry(self, entry):
            self.stopped.append(entry.uuid)
            self.entries = [item for item in self.entries if item.uuid != entry.uuid]

    class Parent(QWidget):
        def __init__(self):
            super().__init__()
            self.is_recording = True
            self.cleared = False
            self.local_recorder = types.SimpleNamespace(is_running=False)
            self.messages = []
            self.statusbar = types.SimpleNamespace(showMessage=self.messages.append)

        def stop_recording_indicator(self):
            self.is_recording = False
            self.cleared = True

    backend = FakeBackend()
    parent = Parent()
    dialog = ui.DVRStatusDialog(backend, parent)
    dialog.update_timer.stop()
    try:
        assert dialog.upcoming_table.rowCount() == 2
        assert dialog.stop_btn.isEnabled() is False

        dialog.upcoming_table.selectRow(0)
        app.processEvents()
        assert dialog.stop_btn.isEnabled() is False
        dialog.stop_selected()
        assert backend.stopped == []

        dialog.upcoming_table.selectRow(1)
        app.processEvents()
        assert dialog.stop_btn.isEnabled() is True
        dialog.stop_selected()
        assert backend.stopped == ['run']
        assert 'News' in dialog.action_label.text()
        assert dialog.upcoming_table.rowCount() == 1
        assert dialog.stop_btn.isEnabled() is False
        assert parent.cleared is True
        assert parent.messages == ['Recording stopped']

        dialog.tabs.setCurrentWidget(dialog.finished_table)
        dialog.finished_table.selectRow(0)
        app.processEvents()
        assert dialog.stop_btn.isEnabled() is False
        assert dialog.upcoming_table.accessibleName() == "Upcoming and current recordings"
    finally:
        dialog.close()
        parent.close()
        app.processEvents()


def _column_widths_fill_viewport(table):
    header = table.horizontalHeader()
    widths = sum(header.sectionSize(column) for column in range(table.columnCount()))
    return abs(widths - table.viewport().width()) <= 2


def test_status_dialogs_fill_window_width(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setitem(
        sys.modules,
        'vlc',
        types.SimpleNamespace(Instance=lambda *a, **k: None, MediaStats=object, __version__='stub'),
    )
    sys.modules.pop('tvhplayer.tvhplayer', None)
    import tvhplayer.tvhplayer as ui
    from PyQt6.QtWidgets import QApplication, QHeaderView

    app = QApplication.instance() or QApplication([])

    class Backend:
        def __init__(self):
            self.server = types.SimpleNamespace(to_dict=lambda: {
                "name": "local",
                "url": "http://127.0.0.1:9981",
                "protocol": "http",
            })

        def list_dvr_entries(self):
            return []

        def get_server_info(self):
            raise RuntimeError("offline")

        def get_inputs(self):
            return []

        def get_connections(self):
            return []

        def get_subscriptions(self):
            return []

    backend = Backend()
    dvr = ui.DVRStatusDialog(backend, None)
    server = ui.ServerStatusDialog(backend, None)
    dvr.update_timer.stop()
    server.update_timer.stop()
    try:
        for dialog in (dvr, server):
            dialog.resize(900, 500)
            dialog.show()
        app.processEvents()

        assert dvr.upcoming_table.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
        assert dvr.finished_table.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
        assert dvr.failed_table.horizontalHeader().sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch
        assert server.subscriptions_table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
        assert server.signal_table.horizontalHeader().sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch

        for table in (
            dvr.upcoming_table,
            dvr.finished_table,
            dvr.failed_table,
            server.subscriptions_table,
            server.signal_table,
        ):
            assert table.viewport().width() > 100
            assert _column_widths_fill_viewport(table)
    finally:
        dvr.close()
        server.close()
        app.processEvents()


def test_accessibility_names_keyboard_and_contrast(monkeypatch, tmp_path):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    from tvhplayer.core.models import Channel, EpgEvent

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        window.show()
        app.processEvents()

        assert app.applicationName() == "TVHplayer"
        assert window.play_btn.accessibleName() == "Play"
        assert window.play_btn.toolTip() == "Play the selected channel (P)"
        assert window.play_btn.statusTip() == ""
        assert window.stop_btn.accessibleName() == "Stop"
        assert window.stop_btn.toolTip() == "Stop playback (Ctrl+.)"
        assert window.stop_btn.statusTip() == ""
        assert window.start_record_btn.toolTip() == "Record on the server (Ctrl+R)"
        assert window.start_record_btn.statusTip() == ""
        assert window.stop_record_btn.toolTip() == "Stop the server recording (Ctrl+E)"
        assert window.start_local_record_btn.toolTip() == "Record on this computer (Ctrl+Shift+R)"
        assert window.stop_local_record_btn.toolTip() == "Stop the recording on this computer (Ctrl+Shift+E)"
        assert window.mute_btn.toolTip() == "Mute (M)"
        assert window.volume_slider.toolTip() == "Volume"
        assert window.fullscreen_btn.toolTip() == "Fullscreen (F11)"
        assert window.fullscreen_btn.statusTip() == ""
        assert window.video_frame.toolTip() == ""
        assert window.video_frame.statusTip() == ""
        assert window.channel_list.toolTip() == ""
        assert window.channel_list.statusTip() == ""
        assert window.search_box.toolTip() == ""
        assert window.search_box.statusTip() == ""
        assert window.server_combo.statusTip() == ""
        assert window.status_label.toolTip() == ""
        assert window.status_label.statusTip() == ""
        assert window.start_record_btn.accessibleName() == "Record on server"
        assert window.stop_record_btn.accessibleName() == "Stop server recording"
        assert window.start_local_record_btn.accessibleName() == "Record locally"
        assert window.stop_local_record_btn.accessibleName() == "Stop local recording"
        assert window.mute_btn.accessibleName() == "Mute"
        assert window.fullscreen_btn.accessibleName() == "Fullscreen"
        assert window.manage_servers_btn.accessibleName() == "Manage servers"
        assert window.volume_slider.accessibleName() == "Volume"
        assert window.video_frame.accessibleName() == "Video player"
        assert window.channel_list.accessibleName() == "Channels"
        assert window.channel_list.horizontalHeaderItem(0).text() == "Number"
        assert window.channel_list.horizontalHeaderItem(2).text() == "Status"
        assert window.splitter.accessibleName() == "Channels, player, and tasks"
        assert window.splitter.handle(2).accessibleName() == "Resize player and tasks"
        assert window.tasks_pane.accessibleName() == "Tasks"
        assert window.tasks_pane.search_box.accessibleName() == "Filter tasks"
        assert window.tasks_pane.status_combo.accessibleName() == "Task status"
        assert window.tasks_pane.status_combo.currentText() == "Active"
        assert [
            window.tasks_pane.status_combo.itemText(index)
            for index in range(window.tasks_pane.status_combo.count())
        ] == ["Active", "All", "Recording", "Scheduled", "Completed"]
        assert window.tasks_pane.task_table.accessibleName() == "Tasks"
        assert window.tasks_pane.task_table.isVisible()
        assert window.tasks_pane.task_table.rowCount() == 0
        assert window.tasks_pane.task_table.horizontalHeaderItem(0).text() == "Kind"
        assert window.tasks_pane.task_table.horizontalHeaderItem(4).text() == "Size"
        assert window.tasks_pane.task_table.horizontalHeaderItem(5).text() == "Detail"
        assert window.tasks_pane.task_table.accessibleDescription() == "No tasks"
        assert window.tasks_pane.action_btn.accessibleName() == "Stop"
        assert window.tasks_pane.action_btn.isEnabled() is False
        assert window.tasks_pane.reveal_btn.accessibleName() == "Reveal in File Manager"
        assert window.tasks_pane.reveal_btn.isEnabled() is False
        assert window.tasks_action.isChecked() is True
        assert any(label.buddy() is window.tasks_pane.search_box for label in window.findChildren(ui.QLabel))
        assert any(label.buddy() is window.tasks_pane.status_combo for label in window.findChildren(ui.QLabel))
        focus_chain = []
        focus_widget = window.fullscreen_btn
        for _ in range(40):
            focus_widget = focus_widget.nextInFocusChain()
            if focus_widget is window.fullscreen_btn:
                break
            focus_chain.append(focus_widget)
        search_at = focus_chain.index(window.tasks_pane.search_box)
        status_at = focus_chain.index(window.tasks_pane.status_combo)
        list_at = focus_chain.index(window.tasks_pane.task_table)
        action_at = focus_chain.index(window.tasks_pane.action_btn)
        reveal_at = focus_chain.index(window.tasks_pane.reveal_btn)
        assert search_at < status_at < list_at < action_at < reveal_at
        assert "focus" in window.play_btn.styleSheet()
        assert window.fullscreen_action.shortcut().toString() == "F11"
        assert any(label.buddy() is window.search_box for label in window.findChildren(ui.QLabel))
        assert any(label.buddy() is window.server_combo for label in window.findChildren(ui.QLabel))
        assert window.search_box.accessibleDescription()

        help_labels = []
        view_labels = []
        for action in window.menuBar().actions():
            menu = action.menu()
            if menu and menu.title().replace("&", "") == "Help":
                help_labels = [item.text().replace("&", "") for item in menu.actions()]
            if menu and menu.title().replace("&", "") == "View":
                view_labels = [item.text().replace("&", "") for item in menu.actions()]
        assert "Keyboard Shortcuts" in help_labels
        assert "Tasks" in view_labels

        shortcuts = ui.ShortcutHelpDialog()
        help_body = shortcuts.help_text.toPlainText()
        assert "Enter" in help_body
        assert "Ctrl+F" in help_body
        assert shortcuts.help_text.accessibleName() == "Keyboard shortcuts"
        shortcuts.close()

        window.statusbar.showMessage("Playing: News")
        window.statusbar.showMessage("Playing: News")
        assert window.status_label.text() == "Playing: News"
        assert window.status_label.accessibleName() == "Playing: News"

        window.video_frame.setFocus()
        app.processEvents()
        mute = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M, Qt.KeyboardModifier.NoModifier)
        window.keyPressEvent(mute)
        app.processEvents()
        assert fake_player.audio_get_mute()
        assert window.mute_btn.isChecked() is True
        assert window.mute_btn.accessibleName() == "Unmute"
        assert window.status_label.accessibleName() == "Muted"

        window.channel_list.setFocus()
        app.processEvents()
        focus = app.focusWidget()
        assert focus is window.channel_list or window.channel_list.isAncestorOf(focus)
        letter_f = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier)
        window.keyPressEvent(letter_f)
        assert window.is_fullscreen is False

        window.video_frame.setFocus()
        app.processEvents()
        search = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier)
        window.keyPressEvent(search)
        app.processEvents()
        assert app.focusWidget() is window.search_box

        typed = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier)
        window.keyPressEvent(typed)
        assert window.search_box.text() == ""

        louder = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Up,
            Qt.KeyboardModifier.ControlModifier,
        )
        window.keyPressEvent(louder)
        assert window.volume_slider.value() == 55
        assert window.status_label.text() == "Volume 55"

        window.channel_list.setSortingEnabled(False)
        window.channel_list.insertRow(0)
        number = ui.QTableWidgetItem()
        number.setData(Qt.ItemDataRole.DisplayRole, 4)
        name = ui.QTableWidgetItem("News")
        name.setData(Qt.ItemDataRole.UserRole, {"uuid": "abc", "name": "News", "number": 4})
        window.channel_list.setItem(0, 0, number)
        window.channel_list.setItem(0, 1, name)
        window.channel_list.setCurrentCell(0, 1)
        enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        assert window.eventFilter(window.channel_list, enter) is True
        assert "Playback error" in window.status_label.text()

        window.start_recording_indicator()
        assert window.recording_indicator.text() == "REC"
        assert window.recording_indicator.isVisible()
        assert "Recording" in window.recording_indicator.accessibleName()
        window.stop_recording_indicator()
        assert window.recording_indicator.text() == ""
        assert window.recording_indicator.accessibleName() == "Not recording"

        window.toggle_fullscreen()
        app.processEvents()
        assert window.video_frame.accessibleName() == "Fullscreen video player"
        assert window.fullscreen_btn.accessibleName() == "Exit fullscreen"
        window.toggle_fullscreen()
        app.processEvents()
        assert window.video_frame.accessibleName() == "Video player"

        duration = ui.RecordingDurationDialog()
        assert duration.hours_spin.accessibleName() == "Hours"
        assert duration.minutes_spin.accessibleName() == "Minutes"
        assert any(label.buddy() is duration.hours_spin for label in duration.findChildren(ui.QLabel))
        duration.close()

        config = ui.ServerConfigDialog()
        assert config.password_input.echoMode() == ui.QLineEdit.EchoMode.Password
        assert any(label.buddy() is config.password_input for label in config.findChildren(ui.QLabel))
        assert any(label.buddy() is config.url_input for label in config.findChildren(ui.QLabel))
        config.close()

        channel = Channel(uuid="c", name="News", number=1)
        event = EpgEvent(
            start=1_700_000_000,
            stop=1_700_003_600,
            title="Evening News",
            description="Headlines tonight",
        )
        guide = ui.EPGDialog(channel, [event], None)
        button_names = [button.accessibleName() for button in guide.findChildren(ui.QPushButton)]
        assert any("Evening News" in button_name for button_name in button_names)
        assert any("Evening News" in label.text() for label in guide.findChildren(ui.QLabel))
        guide.close()

        class _StatusBackend:
            def __init__(self):
                self.server = types.SimpleNamespace(to_dict=lambda: {
                    "name": "local",
                    "url": "http://127.0.0.1:9981",
                    "protocol": "http",
                })

            def get_server_info(self):
                raise RuntimeError("offline")

            def get_inputs(self):
                return []

            def get_connections(self):
                return []

            def get_subscriptions(self):
                return []

        status = ui.ServerStatusDialog(_StatusBackend(), None)
        status.update_timer.stop()
        good = ui.QTableWidgetItem("80.0%")
        status.color_code_cell(good, 52428, 1, "signal")
        assert good.text() == "80.0% (good)"
        poor = ui.QTableWidgetItem("1.0%")
        status.color_code_cell(poor, 655, 1, "signal")
        assert poor.text().endswith("(poor)")
        assert poor.foreground().color().name() == "#ffffff"
        status.close()

        assert ui.prefers_high_contrast() is False
    finally:
        window.close()
        app.processEvents()


def _task_texts(panel):
    rows = []
    for row in range(panel.task_table.rowCount()):
        rows.append(" ".join(
            panel.task_table.item(row, column).text()
            for column in range(panel.task_table.columnCount())
        ))
    return rows


def _select_task(panel, needle):
    for row, text in enumerate(_task_texts(panel)):
        if needle in text:
            panel.task_table.selectRow(row)
            return
    raise AssertionError(needle)


def test_tasks_panel_lists_filters_and_controls_jobs(monkeypatch, tmp_path):
    from tvhplayer.core.models import Channel, DvrEntry

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    window.tasks_pane.update_timer.stop()

    class FakeBackend:
        def __init__(self):
            self.stopped = []
            self.cancelled = []
            self.entries = [
                DvrEntry(
                    uuid='soon', title='Later', channel_name='BBC', start=300, duration=60,
                    status='Scheduled', sched_status='scheduled',
                ),
                DvrEntry(
                    uuid='run', title='News', channel_name='IRINN', start=200, duration=3600,
                    status='Running', sched_status='recording', htsp_id=7,
                    raw={
                        'dataSize': 12 * 1024 * 1024,
                        'files': [{'filename': '/news.ts', 'size': 23688}],
                    },
                ),
                DvrEntry(
                    uuid='done', title='Old', channel_name='BBC', start=50, duration=60,
                    status='Completed',
                    raw={'filesize': 4096},
                ),
                DvrEntry(
                    uuid='older', title='Archive', channel_name='BBC', start=10, duration=30,
                    status='Completed',
                ),
            ]

        def list_dvr_entries(self):
            return list(self.entries)

        def stop_dvr_entry(self, entry):
            self.stopped.append(entry.uuid)
            self.entries = [item for item in self.entries if item.uuid != entry.uuid]

        def cancel_dvr_entry(self, entry):
            self.cancelled.append(entry.uuid)
            self.entries = [item for item in self.entries if item.uuid != entry.uuid]

    class FakeRecorder:
        def __init__(self):
            self.running = True
            self.started_at = 50
            self.file_path = '/tmp/recording_irinn.ts'
            self.stall_count = 6
            self.stopped = False

        @property
        def is_running(self):
            return self.running

        def stop(self):
            self.running = False
            self.stopped = True

    backend = FakeBackend()
    recorder = FakeRecorder()
    window.get_backend = lambda: backend
    window.current_server = lambda: {'name': 'tv', 'url': 'http://tv'}
    window.local_recorder = recorder
    window._recording_channel = Channel(uuid='c', name='IRINN')
    try:
        window.show()
        app.processEvents()
        panel = window.tasks_pane
        panel.refresh()

        texts = _task_texts(panel)
        assert panel.status_combo.currentText() == 'Active'
        assert len(texts) == 3
        assert 'Local' in texts[0] and 'recording_irinn.ts' in texts[0] and 'stalled' in texts[0]
        assert panel.task_table.item(0, 4).text().endswith('B')
        assert 'News' in texts[1] and 'Recording' in texts[1]
        from tvhplayer.tvhplayer import _entry_filesize
        assert _entry_filesize(DvrEntry(
            uuid='http', title='Http', channel_name='IRINN', start=1, duration=1,
            status='Running', raw={'filesize': 2048},
        )) == 2048
        assert _entry_filesize(DvrEntry(
            uuid='both', title='Both', channel_name='IRINN', start=1, duration=1,
            status='Running', raw={'dataSize': 0, 'filesize': 4096},
        )) == 4096
        assert panel.task_table.item(1, 4).text() == '12.0 MB'
        assert panel.task_table.item(1, 4).toolTip() == '12.0 MB'
        assert panel.task_table.item(1, 2).toolTip() == panel.task_table.item(1, 2).text()
        assert panel.task_table.item(1, 5).toolTip() == panel.task_table.item(1, 5).text()
        assert 'Started' in panel.task_table.item(1, 5).toolTip()
        assert panel.task_table.item(2, 4).text() == ''
        assert 'Later' in texts[2] and 'Scheduled' in texts[2]
        assert all('Old' not in text and 'Archive' not in text for text in texts)
        assert panel.action_btn.isEnabled() is False
        assert panel.reveal_btn.isEnabled() is False

        panel.search_box.setText('Later')
        assert _task_texts(panel) == [texts[2]]
        panel.search_box.clear()
        panel.status_combo.setCurrentText('Recording')
        shown = _task_texts(panel)
        assert len(shown) == 2
        assert all('Later' not in text for text in shown)
        panel.search_box.setText('News')
        shown = _task_texts(panel)
        assert len(shown) == 1 and 'News' in shown[0]
        panel.status_combo.setCurrentText('Scheduled')
        assert panel.task_table.rowCount() == 0
        assert panel.task_table.isVisible()
        assert panel.task_table.accessibleDescription() == 'No matching tasks'
        panel.search_box.clear()
        assert len(_task_texts(panel)) == 1 and 'Later' in _task_texts(panel)[0]
        panel.status_combo.setCurrentText('All')
        panel.search_box.setText('Old')
        assert panel.task_table.rowCount() == 1
        assert 'Old' in _task_texts(panel)[0]
        _select_task(panel, 'Old')
        assert panel.reveal_btn.isEnabled() is False
        panel.search_box.clear()
        panel.status_combo.setCurrentText('Completed')
        shown = _task_texts(panel)
        assert [text for text in shown if 'Old' in text or 'Archive' in text]
        assert shown[0].index('Old') >= 0
        assert 'Archive' in shown[1]
        assert 'Completed' in shown[0] and 'Finished' in shown[0]
        assert panel.task_table.item(0, 4).text() == '4.0 KB'
        _select_task(panel, 'Old')
        assert panel.action_btn.isEnabled() is False
        assert panel.reveal_btn.isEnabled() is False
        _select_task(panel, 'Archive')
        assert panel.reveal_btn.isEnabled() is False
        panel.status_combo.setCurrentText('All')
        assert panel.task_table.rowCount() == 5

        class Down:
            def list_dvr_entries(self):
                raise RuntimeError('offline')

        window.get_backend = lambda: Down()
        panel.refresh()
        assert panel.error_label.text() == "Couldn't refresh server recordings"
        assert panel.task_table.rowCount() == 5
        assert any('Old' in text for text in _task_texts(panel))
        window.get_backend = lambda: backend
        panel.refresh()
        assert panel.error_label.text() == ''
        assert panel.task_table.rowCount() == 5

        _select_task(panel, 'News')
        assert panel.action_btn.accessibleName() == 'Stop'
        assert panel.action_btn.isEnabled() is True
        assert panel.reveal_btn.isEnabled() is False
        panel.run_action()
        assert backend.stopped == ['run']
        assert recorder.running is True
        assert window.is_recording is True
        assert all('News' not in text for text in _task_texts(panel))

        _select_task(panel, 'Local')
        assert 'local recording' in panel.action_btn.accessibleDescription()
        assert panel.reveal_btn.isEnabled() is True
        recording = tmp_path / 'recording_irinn.ts'
        recording.write_bytes(b'ts')
        recorder.file_path = str(recording)
        panel.refresh()
        _select_task(panel, 'Local')
        revealed = []

        def fake_show(path, platform=None):
            revealed.append(os.path.abspath(path))
            return os.path.isfile(path)

        monkeypatch.setattr(ui, 'show_in_file_manager', fake_show)
        panel.reveal_selected()
        assert revealed == [str(recording)]
        assert window.status_label.text() == 'Showing recording_irinn.ts in the file manager'
        revealed.clear()

        def show_folder(path, platform=None):
            revealed.append(os.path.abspath(path))
            return os.path.isdir(path)

        monkeypatch.setattr(ui, 'show_in_file_manager', show_folder)
        recorder.file_path = str(tmp_path / 'not-written.ts')
        panel.refresh()
        _select_task(panel, 'Local')
        panel.reveal_selected()
        assert revealed == [
            str(tmp_path / 'not-written.ts'),
            str(tmp_path),
        ]
        revealed.clear()
        monkeypatch.setattr(ui, 'show_in_file_manager', lambda path, platform=None: False)
        panel.reveal_selected()
        assert window.status_label.text() == "Couldn't show the recording in the file manager"
        labels = []

        def capture_menu(menu, *_args, **_kwargs):
            labels.extend(action.text() for action in menu.actions())
            return None

        monkeypatch.setattr(ui.QMenu, 'exec', capture_menu)
        panel._show_task_menu(panel.task_table.visualItemRect(panel.task_table.item(0, 0)).center())
        assert labels == ['Reveal in File Manager']
        recorder.file_path = str(recording)
        panel.refresh()
        _select_task(panel, 'Local')
        panel.run_action()
        assert recorder.stopped is True
        assert window.is_recording is False
        finished_local = [text for text in _task_texts(panel) if 'Local' in text]
        assert len(finished_local) == 1
        assert 'Completed' in finished_local[0]
        _select_task(panel, 'Local')
        assert panel.reveal_btn.isEnabled() is True
        assert panel.action_btn.isEnabled() is False

        window.start_recording_indicator()
        _select_task(panel, 'Later')
        assert panel.reveal_btn.isEnabled() is False
        assert panel.action_btn.accessibleName() == 'Cancel'
        assert panel.action_btn.text() == 'Cancel'
        panel.run_action()
        assert backend.cancelled == ['soon']
        assert window.is_recording is True
        assert any('Old' in text for text in _task_texts(panel))
        assert panel.task_table.isVisible()
        _select_task(panel, 'Old')
        assert panel.reveal_btn.isEnabled() is False
        _select_task(panel, 'Local')
        assert panel.reveal_btn.isEnabled() is True

        window.tasks_action.setChecked(False)
        window._toggle_tasks_pane(False)
        window.toggle_fullscreen()
        app.processEvents()
        assert not panel.isVisible()
        window.toggle_fullscreen()
        app.processEvents()
        assert not panel.isVisible()
        assert window.tasks_action.isChecked() is False
    finally:
        window.close()
        app.processEvents()


def test_stalled_local_recording_is_left_running(monkeypatch, tmp_path):
    from tvhplayer.core.recorder import RecorderStatus

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    stopped = []

    class Recorder:
        def status(self):
            return RecorderStatus(
                file_path='/tmp/a.ts',
                exists=True,
                size=10,
                elapsed=30,
                running=True,
                stalled=True,
                return_code=None,
            )

        def stop(self):
            stopped.append(True)

    def dialog(*_args, **_kwargs):
        raise AssertionError('dialog')

    monkeypatch.setattr(ui.QMessageBox, 'warning', dialog)
    monkeypatch.setattr(ui.QMessageBox, 'critical', dialog)
    monkeypatch.setattr(ui.QFileDialog, 'getSaveFileName', dialog)
    window.local_recorder = Recorder()
    try:
        window.check_recording_status()
        window.check_recording_status()
        assert stopped == []
        assert window.status_label.text() == 'Local recording stalled'
    finally:
        window.close()
        app.processEvents()

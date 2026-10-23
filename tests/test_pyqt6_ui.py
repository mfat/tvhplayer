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
        assert window.stop_btn.accessibleName() == "Stop"
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
        assert "focus" in window.play_btn.styleSheet()
        assert window.fullscreen_action.shortcut().toString() == "F11"
        assert any(label.buddy() is window.search_box for label in window.findChildren(ui.QLabel))
        assert any(label.buddy() is window.server_combo for label in window.findChildren(ui.QLabel))
        assert window.search_box.accessibleDescription()

        help_labels = []
        for action in window.menuBar().actions():
            menu = action.menu()
            if menu and menu.title().replace("&", "") == "Help":
                help_labels = [item.text().replace("&", "") for item in menu.actions()]
        assert "Keyboard Shortcuts" in help_labels

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

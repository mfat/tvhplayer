import ast
import os
import sys
import time
import types
from pathlib import Path

import pytest


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

    server_dialog = ui.ServerDialog()
    server_dialog.load_servers([{
        'name': 'local',
        'url': 'http://127.0.0.1:9981',
        'protocol': 'htsp',
        'htsp_port': 9982,
    }])
    assert server_dialog.protocol_combo.currentData() == 'htsp'
    assert server_dialog.htsp_port_input.value() == 9982

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

    def audio_get_track_description(self):
        return getattr(self, 'audio', [])

    def audio_get_track(self):
        return getattr(self, 'audio_id', -1)

    def audio_set_track(self, track_id):
        self.audio_id = track_id

    def video_get_spu_description(self):
        return getattr(self, 'spu', [])

    def video_get_spu(self):
        return getattr(self, 'spu_id', -1)

    def video_set_spu(self, track_id):
        self.spu_id = track_id

    def video_set_deinterlace(self, mode):
        self.deinterlace = mode

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
    monkeypatch.setattr(ui.TVHeadendClient, 'fetch_channels', lambda self, keep_place=False: None)

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
        # The controls float over the picture, in a window of their own.
        assert window.floating_bar.bar is window.controls_bar
        window.floating_bar.poke()
        app.processEvents()
        assert window.controls_bar.isVisible()
        assert window.floating_bar.isVisible()
        assert window.floating_bar.geometry().bottom() <= window.geometry().bottom()
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
        assert window.controls_bar.parent() is window.right_pane
        assert not window.floating_bar.isVisible()
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
            'Show in TV Guide',
            'Go to Playing Channel',
            '&Audio Track',
            '&Subtitles',
            '&Deinterlace',
        ]
        enabled = {
            action.text(): action.isEnabled()
            for action in menu.actions()
            if not action.isSeparator()
        }
        assert enabled['Play'] is False
        assert enabled['Go to Playing Channel'] is False
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
        window.servers = []
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


def _wait_for_channels(app, window, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while window._channel_fetch is not None:
        assert time.monotonic() < deadline, "channel fetch did not finish"
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_channel_list_shows_loading_empty_and_error_states(monkeypatch, tmp_path):
    import threading
    import time

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        news = ui.Channel(uuid='news', name='News', number=1)
        gate = threading.Event()
        answers = []
        finished = []

        class Backend:
            def __init__(self, answer):
                self.answer = answer

            def get_channels(self):
                gate.wait(5)
                finished.append(self.answer)
                if isinstance(self.answer, Exception):
                    raise self.answer
                return self.answer

        # Each fetch takes its answer when it starts, so the order is fixed.
        window._open_channel_backend = lambda server: Backend(answers.pop(0))
        window.servers = [{'name': 'Home', 'url': 'http://127.0.0.1:9981', 'protocol': 'http'}]
        window.server_combo.blockSignals(True)
        window.server_combo.addItem('Home')
        window.server_combo.setCurrentIndex(0)
        window.server_combo.blockSignals(False)
        monkeypatch.undo()
        state = window.channel_state

        # First load: a spinner page stands in for the list.
        answers.append(OSError('Connection refused'))
        window.fetch_channels()
        assert window.channel_stack.currentWidget() is state
        assert not state.ring.isHidden()
        assert state.retry_btn.isHidden()
        assert "Loading channels from Home" in state.message.text()
        gate.set()
        _wait_for_channels(app, window)

        # Failure: the message and a Retry button, no dialog.
        assert window.channel_stack.currentWidget() is state
        assert state.ring.isHidden()
        assert not state.retry_btn.isHidden()
        assert "Could not connect to Home" in state.message.text()
        assert "Connection refused" in state.message.text()

        answers.append([news])
        state.retry_btn.click()
        _wait_for_channels(app, window)
        assert window.channel_stack.currentWidget() is window.channel_list
        assert _channel_row(window.channel_list, 'News') >= 0

        # Reload of the same server: the list stays and a thin bar runs.
        gate.clear()
        answers.append(OSError('timed out'))
        window.fetch_channels()
        assert window.channel_stack.currentWidget() is window.channel_list
        assert not window.channel_busy.isHidden()
        gate.set()
        _wait_for_channels(app, window)
        assert window.channel_busy.isHidden()
        assert window.channel_stack.currentWidget() is window.channel_list
        assert _channel_row(window.channel_list, 'News') >= 0

        # A fetch replaced by a newer one is ignored when it ends.
        gate.clear()
        finished.clear()
        answers.extend([[ui.Channel(uuid='old', name='Old', number=9)], []])
        window.fetch_channels()
        window.fetch_channels()
        gate.set()
        _wait_for_channels(app, window)
        deadline = time.monotonic() + 5
        while len(finished) < 2 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        for _ in range(20):
            app.processEvents()
            time.sleep(0.01)
        assert _channel_row(window.channel_list, 'Old') == -1
        assert window.channel_stack.currentWidget() is state
        assert "no channels" in state.message.text()
    finally:
        window.close()
        app.processEvents()


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
        window._open_channel_backend = lambda server: Backend()
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
        _wait_for_channels(app, window)

        news_row = _channel_row(window.channel_list, 'News')
        sport_row = _channel_row(window.channel_list, 'Sport')
        assert news_row >= 0 and sport_row >= 0
        assert window.channel_list.item(news_row, 2).text() == ""
        assert window.channel_list.item(sport_row, 2).text() == ""

        window.play_channel_by_data(sport)
        app.processEvents()

        assert window.channel_list.currentRow() == sport_row
        assert window.windowTitle() == "Sport – TVHplayer"
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

        # Go to Playing Channel clears a search that hides the row and selects it.
        window.search_box.setText("News")
        app.processEvents()
        assert window.channel_list.isRowHidden(sport_row)
        window.go_to_playing_action.trigger()
        app.processEvents()
        assert window.search_box.text() == ""
        assert not window.channel_list.isRowHidden(sport_row)
        assert window.channel_list.currentRow() == sport_row
        window.channel_list.setCurrentCell(news_row, 1)

        window.fetch_channels()
        _wait_for_channels(app, window)
        sport_row = _channel_row(window.channel_list, 'Sport')
        news_row = _channel_row(window.channel_list, 'News')
        assert window.channel_list.item(sport_row, 2).text() == "Playing"
        assert window.channel_list.currentRow() == sport_row

        window.stop_playback()
        app.processEvents()
        assert window.windowTitle() == "TVHplayer"
        window.show_playing_channel()
        assert window.status_label.text() == "Nothing is playing"
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
            self.local_recording_running = lambda: False
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
        assert window.play_btn.toolTip() == "Play / Stop (P)"
        assert window.play_btn.statusTip() == ""
        assert window.record_btn.toolTip() == "Record (Ctrl+R / Ctrl+Shift+R)"
        assert window.record_btn.statusTip() == ""
        assert window.record_btn.isVisible()
        assert not window.stop_record_btn.isVisible()
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
        assert window.record_btn.accessibleName() == "Record"
        assert window.stop_record_btn.accessibleName() == "Stop recording"
        assert window.record_more_btn.accessibleName() == "Start another recording"
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
        assert window.tasks_pane.task_table.columnCount() == 7
        assert window.tasks_pane.task_table.horizontalHeaderItem(0).text() == ""
        assert window.tasks_pane.task_table.horizontalHeaderItem(0).data(
            Qt.ItemDataRole.AccessibleTextRole
        ) == "Status icon"
        assert window.tasks_pane.task_table.horizontalHeaderItem(1).text() == "Kind"
        assert window.tasks_pane.task_table.horizontalHeaderItem(4).text() == "Status"
        assert window.tasks_pane.task_table.horizontalHeaderItem(5).text() == "Size"
        assert window.tasks_pane.task_table.horizontalHeaderItem(6).text() == "Detail"
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
        close_at = focus_chain.index(window.tasks_pane.close_btn)
        assert search_at < status_at < list_at < action_at < reveal_at < close_at
        assert window.tasks_pane.close_btn.accessibleName() == "Close Tasks"
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
        window.servers = []
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
        assert duration.custom_spin.accessibleName() == "Length"
        assert duration.preset_buttons['60'].accessibleName() == "1 h"
        assert any(label.buddy() is duration.preset_buttons['30'] for label in duration.findChildren(ui.QLabel))
        duration.close()

        config = ui.ServerDialog()
        assert config.password_input.echoMode() == ui.QLineEdit.EchoMode.Password
        assert any(label.buddy() is config.password_input for label in config.findChildren(ui.QLabel))
        assert any(label.buddy() is config.url_input for label in config.findChildren(ui.QLabel))
        assert any(label.buddy() is config.server_list for label in config.findChildren(ui.QLabel))
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


def _status_icon_center_offset(table, row):
    """How far the painted status glyph sits from the middle of its cell."""
    rect = table.visualItemRect(table.item(row, 0))
    image = table.viewport().grab(rect).toImage()
    background = image.pixelColor(1, 1)
    xs = []
    ys = []
    for y in range(1, image.height() - 1):
        for x in range(1, image.width() - 1):
            color = image.pixelColor(x, y)
            if (
                abs(color.red() - background.red())
                + abs(color.green() - background.green())
                + abs(color.blue() - background.blue())
            ) > 80:
                xs.append(x)
                ys.append(y)
    assert xs, "status icon was not painted"
    return (
        sum(xs) / len(xs) - image.width() / 2,
        sum(ys) / len(ys) - image.height() / 2,
    )


def _select_task(panel, needle):
    for row, text in enumerate(_task_texts(panel)):
        if needle in text:
            panel.task_table.selectRow(row)
            return
    raise AssertionError(needle)


def _wait_for_tasks(app, panel, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while panel._fetching:
        assert time.monotonic() < deadline, "task fetch did not finish"
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_tasks_panel_reads_the_server_without_blocking(monkeypatch, tmp_path):
    import threading
    import time

    from tvhplayer.core.models import DvrEntry

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    window.tasks_pane.update_timer.stop()
    gate = threading.Event()

    class SlowBackend:
        def __init__(self, title):
            self.title = title

        def list_dvr_entries(self):
            gate.wait(5)
            return [DvrEntry(
                uuid=self.title, title=self.title, channel_name='BBC', start=int(time.time()) + 600,
                duration=60, status='Scheduled', sched_status='scheduled',
            )]

        def close(self):
            pass

    servers = {'name': 'old', 'url': 'http://old'}
    window.current_server = lambda: servers
    window._server_requests_ready = lambda: True
    panel = window.tasks_pane
    panel.open_backend = lambda server: SlowBackend(server['name'])
    try:
        started = time.monotonic()
        panel.refresh()
        assert time.monotonic() - started < 1
        assert panel._fetching
        assert panel.task_table.rowCount() == 0

        # The server changes while the old one is still answering.
        servers = {'name': 'new', 'url': 'http://new'}
        panel.clear_server_tasks()
        gate.set()
        deadline = time.monotonic() + 5
        while not any('new' in text for text in _task_texts(panel)):
            assert time.monotonic() < deadline, "the new server's recordings never showed"
            app.processEvents()
            time.sleep(0.01)
        assert all('old' not in text for text in _task_texts(panel))
        _wait_for_tasks(app, panel)
    finally:
        window.close()
        app.processEvents()


def test_tasks_panel_goes_to_the_task_channel(monkeypatch, tmp_path):
    from tvhplayer.core.models import DvrEntry

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    window.tasks_pane.update_timer.stop()
    news = ui.Channel(uuid='news', name='News', number=1, htsp_id=7)
    sport = ui.Channel(uuid='sport', name='Sport', number=2, htsp_id=8)
    try:
        panel = window.tasks_pane
        shown = []
        window.show_channel_in_list = lambda channel=None, matches=None: shown.append(
            [name for name in ('News', 'Sport')
             if (matches or (lambda listed: window._channels_match(listed, channel)))(
                 news if name == 'News' else sport)]
        )
        entry = DvrEntry(uuid='e', title='Match', channel_name='Sport', start=1, duration=1, raw={'channel': 8})
        panel.selected_task = lambda: {'kind': 'Server', 'entry': entry, 'channel': 'Sport'}
        panel.show_selected_channel()
        job = types.SimpleNamespace(channel=news)
        panel.selected_task = lambda: {'kind': 'Local', 'entry': None, 'job': job, 'channel': 'News'}
        panel.show_selected_channel()
        assert shown == [['Sport'], ['News']]
    finally:
        window.close()
        app.processEvents()


def test_tasks_panel_lists_filters_and_controls_jobs(monkeypatch, tmp_path):
    from tvhplayer.core.models import Channel, DvrEntry

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    window.tasks_pane.update_timer.stop()

    class FakeBackend:
        def __init__(self):
            self.stopped = []
            self.cancelled = []
            self.offline = False
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
            if self.offline:
                raise RuntimeError('offline')
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
    window.tasks_pane.open_backend = lambda server: backend
    window.current_server = lambda: {'name': 'tv', 'url': 'http://tv'}
    window.local_jobs = [ui.LocalJob(recorder, Channel(uuid='c', name='IRINN'))]
    try:
        window.show()
        app.processEvents()
        panel = window.tasks_pane
        panel.refresh()
        _wait_for_tasks(app, panel)

        texts = _task_texts(panel)
        assert panel.status_combo.currentText() == 'Active'
        assert len(texts) == 3
        assert 'Local' in texts[0] and 'recording_irinn.ts' in texts[0] and 'stalled' in texts[0]
        assert panel.task_table.item(0, 0).text() == ''
        assert panel.task_table.item(0, 0).icon().isNull() is False
        assert panel.task_table.item(0, 0).toolTip() == 'Recording'
        assert panel.task_table.item(1, 0).toolTip() == 'Recording'
        assert panel.task_table.item(0, 0).icon().cacheKey() == panel.task_table.item(1, 0).icon().cacheKey()
        assert panel.task_table.item(2, 0).toolTip() == 'Scheduled'
        assert panel.task_table.item(0, 0).icon().cacheKey() != panel.task_table.item(2, 0).icon().cacheKey()
        app.processEvents()
        icon_dx, icon_dy = _status_icon_center_offset(panel.task_table, 2)
        assert abs(icon_dx) <= 2
        assert abs(icon_dy) <= 2
        assert panel.task_table.item(0, 5).text().endswith('B')
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
        assert panel.task_table.item(1, 5).text() == '12.0 MB'
        assert panel.task_table.item(1, 5).toolTip() == '12.0 MB'
        assert panel.task_table.item(1, 3).toolTip() == panel.task_table.item(1, 3).text()
        assert panel.task_table.item(1, 6).toolTip() == panel.task_table.item(1, 6).text()
        assert 'Started' in panel.task_table.item(1, 6).toolTip()
        assert panel.task_table.item(2, 5).text() == ''
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
        from tvhplayer.tvhplayer import _task_status_icon
        assert panel.task_table.item(0, 0).toolTip() == 'Completed'
        assert panel.task_table.item(0, 0).icon().cacheKey() == _task_status_icon('Completed').cacheKey()
        assert panel.task_table.item(0, 5).text() == '4.0 KB'
        _select_task(panel, 'Old')
        assert panel.action_btn.isEnabled() is False
        assert panel.reveal_btn.isEnabled() is False
        _select_task(panel, 'Archive')
        assert panel.reveal_btn.isEnabled() is False
        panel.status_combo.setCurrentText('All')
        assert panel.task_table.rowCount() == 5

        opened = []
        panel.open_backend = lambda server: opened.append(server) or backend
        backend.offline = True
        panel.refresh()
        _wait_for_tasks(app, panel)
        assert panel.error_label.text() == "Couldn't refresh server recordings"
        assert panel.task_table.rowCount() == 5
        assert any('Old' in text for text in _task_texts(panel))
        backend.offline = False
        panel.refresh()
        _wait_for_tasks(app, panel)
        # A failed read drops the connection, and the next one connects again.
        assert len(opened) == 1
        assert panel.error_label.text() == ''
        assert panel.task_table.rowCount() == 5

        _select_task(panel, 'News')
        assert panel.action_btn.accessibleName() == 'Stop'
        assert panel.action_btn.isEnabled() is True
        assert panel.reveal_btn.isEnabled() is False
        panel.run_action()
        _wait_for_tasks(app, panel)
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
        _wait_for_tasks(app, panel)
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
        _wait_for_tasks(app, panel)
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
            labels.extend((action.text(), action.isEnabled()) for action in menu.actions() if not action.isSeparator())
            return None

        monkeypatch.setattr(ui.QMenu, 'exec', capture_menu)
        panel._show_task_menu(panel.task_table.visualItemRect(panel.task_table.item(0, 0)).center())
        # A recording still going cannot be converted yet.
        assert labels == [
            ('Stop Recording', True), ('Reveal in File Manager', True), ('Convert for Editing', False),
            ('Go to Channel', True),
        ]
        labels.clear()
        _select_task(panel, 'Scheduled')
        row = panel.task_table.currentRow()
        panel._show_task_menu(panel.task_table.visualItemRect(panel.task_table.item(row, 0)).center())
        assert labels[0] == ('Cancel Scheduled Recording', True)
        recorder.file_path = str(recording)
        panel.refresh()
        _wait_for_tasks(app, panel)
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

        panel.close_btn.click()
        app.processEvents()
        assert not panel.isVisible()
        assert window.tasks_action.isChecked() is False
        window.tasks_action.trigger()
        app.processEvents()
        assert panel.isVisible()

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
        # A failed check can leave the recording running; do not wait on the quit question.
        window._confirm_quit = lambda: True
        window.close()
        app.processEvents()


def test_stalled_local_recording_is_left_running(monkeypatch, tmp_path):
    from tvhplayer.core.recorder import RecorderStatus

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    stopped = []

    class Recorder:
        is_running = True

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
    window.local_jobs = [ui.LocalJob(Recorder(), None)]
    try:
        window.check_recording_status()
        window.check_recording_status()
        assert stopped == []
        assert window.status_label.text() == 'Local recording stalled'
    finally:
        window._confirm_quit = lambda: True
        window.close()
        app.processEvents()


def test_local_recording_saves_to_the_settings_folder_and_stops_on_time(monkeypatch, tmp_path):
    from tvhplayer.core.models import Channel

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    started, options = [], []

    class Recorder:
        is_running = False
        file_path = None

        def start(self, url, path, _user, _password, extra_options):
            started.append(path)
            options.append(extra_options)
            self.is_running = True
            self.file_path = path

        def stop(self):
            self.is_running = False

    class Dialog:
        def __init__(self, _parent, _channel, _event, save_dir=None):
            assert save_dir == str(tmp_path / 'videos')

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_duration(self):
            return 1800

        def programme_event(self):
            return None

    monkeypatch.setattr(ui, 'RecordingDurationDialog', Dialog)
    monkeypatch.setattr(ui.QFileDialog, 'getSaveFileName', lambda *_a, **_k: pytest.fail('asked for a file'))
    window.get_backend = lambda: types.SimpleNamespace(stream_url=lambda _c: 'http://tv/stream')
    window._programme_on_now = lambda _c: None
    window.new_local_recorder = Recorder
    window.set_local_recording_dir(str(tmp_path / 'videos'))
    try:
        window.start_local_recording(Channel(uuid='c', name='BBC/News'))
        assert len(started) == 1
        path = Path(started[0])
        assert path.parent == tmp_path / 'videos' and path.parent.is_dir()
        assert path.name.startswith('recording_BBC_News_') and path.suffix == '.ts'
        job = window.local_jobs[0]
        assert job.timer.interval() == 1800 * 1000
        job.timer.timeout.emit()
        assert job.recorder.is_running is False
        assert job.timer is None
        assert options == [[]]

        window.set_recording_format('mp4')
        window.set_recording_ffmpeg_options('-b:a 128k -metadata "title=Evening news"')
        window.start_local_recording(Channel(uuid='c', name='BBC/News'))
        assert Path(started[1]).suffix == '.mp4'
        assert options[1] == ['-b:a', '128k', '-metadata', 'title=Evening news']
        window.stop_local_recording()

        # Options that do not parse stop before anything starts.
        warnings = []
        monkeypatch.setattr(ui.QMessageBox, 'warning', lambda *a: warnings.append(a[2]))
        window.set_recording_ffmpeg_options('-metadata "title=unclosed')
        window.start_local_recording(Channel(uuid='c', name='BBC/News'))
        assert len(started) == 2 and 'cannot be read' in warnings[0]
    finally:
        window.close()
        app.processEvents()


def test_several_channels_record_to_this_computer_at_once(monkeypatch, tmp_path):
    from tvhplayer.core.models import Channel

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    started = []

    class Recorder:
        is_running = False
        file_path = None

        def start(self, url, path, *_rest):
            started.append(url)
            self.is_running = True
            self.file_path = path

        def stop(self):
            self.is_running = False

    class Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_duration(self):
            return 600

        def programme_event(self):
            return None

    monkeypatch.setattr(ui, 'RecordingDurationDialog', Dialog)
    window.get_backend = lambda: types.SimpleNamespace(stream_url=lambda c: f'http://tv/{c.uuid}')
    window._programme_on_now = lambda _c: None
    window.new_local_recorder = Recorder
    window.set_local_recording_dir(str(tmp_path / 'videos'))
    one, two = Channel(uuid='a', name='One'), Channel(uuid='b', name='Two')
    try:
        window.start_local_recording(one)
        window.active_channel = lambda: two
        window._sync_record_controls()
        assert window.controls_bar.record_local_action.isEnabled() is True
        window.start_local_recording(two)
        assert started == ['http://tv/a', 'http://tv/b']
        assert [job.is_running for job in window.local_jobs] == [True, True]
        assert window.controls_bar.record_local_action.isEnabled() is False

        # The same channel twice would only make a second copy.
        window.start_local_recording(one)
        assert len(started) == 2
        assert 'already recording' in window.status_label.text()

        # Stop ends the active channel's recording; the other keeps going.
        window.stop_local_recording()
        assert [job.is_running for job in window.local_jobs] == [True, False]
        assert window.recording_monitor is not None
        window.local_jobs[0].timer.timeout.emit()
        assert window.local_recording_running() is False
        assert window.recording_monitor is None
    finally:
        window._confirm_quit = lambda: True
        window.close()
        app.processEvents()


def test_local_recordings_default_to_the_videos_folder(monkeypatch, tmp_path):
    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    window.config.pop('local_recording_dir', None)
    assert window.local_recording_dir() == ui.default_recording_dir()
    window.close()
    app.processEvents()


def test_flatpak_asks_for_the_recordings_folder_once(monkeypatch, tmp_path):
    from tvhplayer.core.models import Channel

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    videos = tmp_path / 'Videos'
    monkeypatch.setattr(ui.QStandardPaths, 'writableLocation', lambda _kind: str(videos))
    monkeypatch.setattr(ui, 'in_flatpak', lambda: True)
    # Without access, the Videos folder is not there; never make it in the sandbox.
    assert ui.default_recording_dir() == ''
    assert not ui.ensure_recording_dir(str(videos))
    assert not videos.exists()

    started, asked, prompts = [], [], []
    chosen = tmp_path / 'portal'
    chosen.mkdir()

    class Recorder:
        is_running = False
        file_path = None

        def start(self, _url, path, *_auth):
            started.append(path)

        def stop(self):
            pass

    class Box(ui.QMessageBox):
        # Choose Folder… is the default button: "click" it without a modal loop.
        def exec(self):
            prompts.append(self.text())

        def clickedButton(self):
            return self.defaultButton()

    class Dialog:
        def __init__(self, _parent, _channel, _event, save_dir=None):
            assert save_dir == str(chosen)

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_duration(self):
            return 60

        def programme_event(self):
            return None

    monkeypatch.setattr(ui, 'QMessageBox', Box)
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *_a: asked.append(1) or str(chosen))
    monkeypatch.setattr(ui, 'RecordingDurationDialog', Dialog)
    window.get_backend = lambda: types.SimpleNamespace(stream_url=lambda _c: 'http://tv/stream')
    window._programme_on_now = lambda _c: None
    window.new_local_recorder = Recorder
    window.config.pop('local_recording_dir', None)
    try:
        assert window.local_recording_dir() == ''
        window.start_local_recording(Channel(uuid='c', name='One'))
        window.stop_local_recording()
        window.start_local_recording(Channel(uuid='c', name='One'))
        window.stop_local_recording()
        assert len(asked) == 1 and len(prompts) == 1
        assert 'from now on' in prompts[0]
        assert window.config_store.data['local_recording_dir'] == str(chosen)
        assert [Path(path).parent for path in started] == [chosen, chosen]
    finally:
        window._confirm_quit = lambda: True
        window.close()
        app.processEvents()


def test_conversions_show_in_tasks_and_follow_a_recording(monkeypatch, tmp_path):
    from tvhplayer.core import convert

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(convert.Conversion, 'start', lambda self: started.append(self) or setattr(self, 'status', convert.CONVERTING))
    monkeypatch.setattr(window, 'conversion_problem', lambda _text: '')
    recording = tmp_path / 'recording_One.ts'
    recording.write_bytes(b'ts data')

    class Recorder:
        is_running = True
        file_path = str(recording)
        started_at = time.time()
        stall_count = 0

        def stop(self):
            self.is_running = False

    window.local_jobs = [ui.LocalJob(Recorder(), None)]
    window.set_converts_after_recording(True)
    window.set_deletes_converted_original(True)
    window.current_server = lambda: None
    try:
        window.show()
        app.processEvents()
        window.stop_local_recording()
        assert len(window.conversions) == 1
        job = window.conversions[0]
        assert job.target == str(tmp_path / 'recording_One_edit.mp4')
        assert job.delete_original is True
        assert job.options == convert.parse_ffmpeg_options(convert.DEFAULT_CONVERT_OPTIONS)
        assert started == [job]

        # A second one waits for the first.
        manual = window.convert_for_editing(str(recording))
        assert manual.delete_original is False and manual.status == convert.WAITING
        assert manual.target == str(tmp_path / 'recording_One_edit_2.mp4')

        panel = window.tasks_pane
        panel.status_combo.setCurrentText('Active')
        panel.refresh(server=False)
        rows = {panel.task_table.item(r, 4).text(): r for r in range(panel.task_table.rowCount())}
        assert 'Converting' in rows and 'Waiting' in rows
        job.progress = 0.42
        panel.refresh(server=False)
        row = next(r for r in range(panel.task_table.rowCount()) if panel.task_table.item(r, 4).text() == 'Converting')
        assert panel.task_table.item(row, 6).text().endswith('42%')
        panel.task_table.selectRow(row)
        assert panel.action_btn.text() == 'Cancel' and panel.action_btn.isEnabled()

        # The first is done: the next one starts and the finish is told.
        job.status = convert.DONE
        window._tick_conversions()
        assert started == [job, manual]
        assert 'Converted recording_One.ts for editing' in window.status_label.text()

        # Cancel from Tasks.
        panel.refresh(server=False)
        row = next(r for r in range(panel.task_table.rowCount()) if panel.task_table.item(r, 4).text() == 'Converting')
        panel.task_table.selectRow(row)
        menus = []
        monkeypatch.setattr(ui.QMenu, 'exec', lambda menu, *_a: menus.append(menu.actions()))
        panel._show_task_menu(panel.task_table.visualItemRect(panel.task_table.item(row, 0)).center())
        assert menus[0][0].text() == 'Cancel Conversion' and menus[0][0].isEnabled()
        menus[0][0].trigger()
        assert manual._cancelled
        assert 'original is kept' in window.status_label.text()
    finally:
        for job in window.conversions:
            job.status = convert.DONE
        window._confirm_quit = lambda: True
        window.close()
        app.processEvents()


def test_conversion_is_refused_when_ffmpeg_cannot_encode(monkeypatch, tmp_path):
    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(ui.QMessageBox, 'warning', lambda *a: warnings.append(a[2]))
    monkeypatch.setattr(window, 'conversion_problem', lambda _text: 'This ffmpeg has no libx264 encoder.')
    try:
        assert window.convert_for_editing(str(tmp_path / 'a.ts')) is None
        assert window.conversions == []
        assert 'no libx264 encoder' in warnings[0] and 'Settings' in warnings[0]
    finally:
        window.close()
        app.processEvents()


def test_quit_asks_while_recording_to_this_computer(monkeypatch, tmp_path):
    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    window.builtin = None
    recorder = types.SimpleNamespace(is_running=True, file_path='/tmp/rec_One.ts', stop=lambda: None)
    window.local_jobs = [ui.LocalJob(recorder, types.SimpleNamespace(name='One'))]
    messages = []
    monkeypatch.setattr(
        ui.QMessageBox, 'question',
        lambda _parent, _title, text, *a: messages.append(text) or ui.QMessageBox.StandardButton.No,
    )
    assert window._confirm_quit() is False
    assert 'One (rec_One.ts)' in messages[0]
    recorder.is_running = False
    assert window._confirm_quit() is True
    app.processEvents()


def test_quit_asks_the_builtin_server_even_when_another_is_selected(monkeypatch, tmp_path):
    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    from tvhplayer.core.models import DvrEntry

    window.servers = [
        {'name': 'NAS', 'url': 'http://nas:9981', 'protocol': 'http'},
        {
            'name': 'Built-in Server', 'url': 'http://127.0.0.1:24111', 'protocol': 'http',
            'username': 'tvhplayer', 'password': 'secret-secret-secret', 'builtin': True,
        },
    ]
    window.server_combo.blockSignals(True)
    window.server_combo.clear()
    window.server_combo.addItems(['NAS', 'Built-in Server'])
    window.server_combo.setCurrentIndex(0)
    window.server_combo.blockSignals(False)
    window.builtin = types.SimpleNamespace(
        is_running=lambda: True, username='tvhplayer', password='secret-secret-secret',
        stop=lambda: None,
    )

    asked = []

    class _Backend:
        def __init__(self, server):
            asked.append(server)

        def list_dvr_entries(self):
            return [DvrEntry(
                uuid='1', title='News Hour', channel_name='One', start=0, duration=60,
                status='Running', sched_status='recording',
            )]

        def close(self):
            pass

    monkeypatch.setattr(ui, 'create_backend', _Backend)
    messages = []
    monkeypatch.setattr(
        ui.QMessageBox, 'question',
        lambda _parent, _title, text, *a: messages.append(text) or ui.QMessageBox.StandardButton.No,
    )
    assert window._confirm_quit() is False
    assert [server['name'] for server in asked] == ['Built-in Server']
    assert 'News Hour' in messages[0]
    app.processEvents()


def test_status_is_repeated_on_the_picture_only_while_a_channel_shows(monkeypatch, tmp_path):
    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    from tvhplayer.core.models import Channel

    shown = []
    monkeypatch.setattr(window.player, 'show_message', lambda text, duration_ms=3000: shown.append(text))

    window._playback_active = False
    window.on_volume_changed(30)
    assert shown == []

    window._playback_channel = Channel(uuid='c1', name='News One', number=5)
    window._on_playback_started()
    assert shown == ['5  News One']

    window.on_volume_changed(40)
    window.toggle_mute()
    window.toggle_mute()
    assert shown[1:] == ['Volume 40', 'Muted', 'Sound on']
    app.processEvents()


def test_channel_list_reloads_at_most_every_30_seconds_during_a_playlist_check(monkeypatch, tmp_path):
    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        reloads = []
        server = {'name': 'Built-in Server', 'url': 'http://127.0.0.1:1', 'builtin': True}
        monkeypatch.setattr(window, 'is_current_server', lambda candidate: candidate is server)
        monkeypatch.setattr(window, 'current_server', lambda: server)
        # The reload keeps the selected row and scroll place.
        monkeypatch.setattr(window, 'fetch_channels', lambda keep_place=False: keep_place and reloads.append(server))
        clock = [1000.0]
        monkeypatch.setattr(ui.time, 'monotonic', lambda: clock[0])

        window.playlist_channels_changed(server)
        window._channel_reload_timer.timeout.emit()
        window._channel_reload_timer.stop()
        assert reloads == [server]

        clock[0] += 10
        window.playlist_channels_changed(server)
        assert window._channel_reload_timer.remainingTime() > 19000
        window.playlist_channels_changed(server)
        window.playlist_channels_changed({'url': 'http://other'})
        window._channel_reload_timer.stop()
        assert reloads == [server]
    finally:
        window.close()


def test_spinner_sits_above_the_video_and_shows_the_server_status(monkeypatch, tmp_path):
    import time

    from tvhplayer.core.models import Channel, SubscriptionStatus
    from tvhplayer.core.playback_status import RETRYING, STARTING, WAITING

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        spinner = window.playback_spinner
        assert spinner.testAttribute(ui.Qt.WidgetAttribute.WA_NativeWindow)
        assert not window.player_container.testAttribute(ui.Qt.WidgetAttribute.WA_NativeWindow)

        states = iter(['Testing', 'Bad', 'Testing'])

        class FakeBackend:
            def get_subscriptions(self):
                state = next(states, 'Testing')
                return [SubscriptionStatus(channel='TBN', title='HTTP', state=state, start=1, raw={'in': 0})]

            def close(self):
                pass

        monkeypatch.setattr(ui, 'create_backend', lambda _server: FakeBackend())
        monkeypatch.setattr(window, 'current_server', lambda: {'url': 'http://127.0.0.1:1'})
        window._playback_channel = Channel.from_raw({'name': 'TBN', 'uuid': 'u1'})
        window._show_playback_wait()
        assert spinner._caption == STARTING
        captions = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and RETRYING not in captions:
            app.processEvents()
            if not captions or captions[-1] != spinner._caption:
                captions.append(spinner._caption)
            time.sleep(0.02)
        assert [text for text in captions if text != STARTING][:2] == [WAITING, RETRYING]
        assert window.status_label.text() == f'TBN: {RETRYING}'

        window._on_playback_started()
        assert window._start_watch is None
    finally:
        window.close()


def test_startup_refresh_moves_on_when_a_playlist_reaches_its_stream_test(monkeypatch, tmp_path):
    from PyQt6.QtCore import QObject, pyqtSignal

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        started = []

        class FakeJob(QObject):
            checking = pyqtSignal()
            finished = pyqtSignal(str, object)
            failed = pyqtSignal(str)

            def __init__(self, _host, source, server, parent=None):
                super().__init__(parent)
                self.source = source
                self.server = server

            def start(self):
                started.append(self)

        server = {'name': 'Built-in Server', 'url': 'http://127.0.0.1:1', 'builtin': True}
        monkeypatch.setattr(ui, 'PlaylistJob', FakeJob)
        monkeypatch.setattr(ui, 'find_builtin_server', lambda _servers: server)
        monkeypatch.setattr(window, '_playlist_refreshed', lambda *_args: None)
        sources = [ui.PlaylistSource(name, f'http://x/{name}.m3u', 'builtin') for name in ('eng', 'fas', 'ar')]
        monkeypatch.setattr(window, 'playlist_sources', lambda: sources)

        window._refresh_builtin_playlists()
        assert [job.source.name for job in started] == ['eng']
        started[0].checking.emit()
        assert [job.source.name for job in started] == ['eng', 'fas']
        started[0].finished.emit('done', [])
        assert len(started) == 2
        # 'ar' was removed while it waited; it is skipped, not imported again.
        sources.pop()
        started[1].failed.emit('Could not reach it.')
        assert [job.source.name for job in started] == ['eng', 'fas']
    finally:
        window.close()


def test_last_channel_plays_at_start_when_asked(monkeypatch, tmp_path):
    from tvhplayer.core.models import Channel

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        played = []
        monkeypatch.setattr(window, 'save_config', lambda: None)
        news, sport = Channel(uuid='u1', name='News'), Channel(uuid='u2', name='Sport')
        window._channels = [news, sport]
        window._channels_server = 'builtin'
        window._remember_channel(sport)
        assert window.config['last_channel'] == {'server': 'builtin', 'key': 'u2', 'name': 'Sport'}

        monkeypatch.setattr(window, 'play_channel_by_data', played.append)
        window._playback_channel = None
        window._play_last_channel('http://other')
        assert played == []
        window._play_last_channel('builtin')
        assert played == [sport]

        window.set_plays_on_start(True)
        assert window.plays_on_start()
    finally:
        window.close()


def _channel_list_window(monkeypatch, tmp_path, backend):
    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    window.get_backend = lambda: backend
    window._open_channel_backend = lambda server: backend
    window.servers = [{'name': 'local', 'url': 'http://127.0.0.1:9981', 'protocol': 'http'}]
    window.server_combo.blockSignals(True)
    window.server_combo.addItem('local')
    window.server_combo.setCurrentIndex(0)
    window.server_combo.blockSignals(False)
    window.logo_loader = ui.LogoLoader(window, cache_dir=tmp_path / 'cache')
    window.logo_loader.loaded.connect(window._on_logo_loaded)
    monkeypatch.undo()
    return app, ui, window


class _ExtrasBackend:
    def __init__(self, now):
        from tvhplayer.core.channel_info import NowNext
        from tvhplayer.core.models import Channel, ChannelTag, EpgEvent

        self.news = Channel(uuid='news', name='News', number=1, tag_ids=['t-news'],
                               raw={'icon_public_url': 'imagecache/1'})
        self.sport = Channel(uuid='sport', name='Sport', number=2, tag_ids=['t-hd'])
        self.off = Channel(uuid='off', name='Off', number=3, enabled=False)
        self.tags = [ChannelTag(uuid='t-news', name='News'), ChannelTag(uuid='t-hd', name='HDTV')]
        headline = EpgEvent(start=now - 600, stop=now + 600, title='Headlines', channel_uuid='news', event_id=1)
        weather = EpgEvent(start=now + 600, stop=now + 1200, title='Weather', channel_uuid='news', event_id=2)
        self.now_next = {'news': NowNext(headline, weather)}
        self.now_next_calls = 0
        self.service_calls = 0
        self.image_requests = []

    def get_channels(self):
        return [self.news, self.sport, self.off]

    def list_channel_tags(self):
        return self.tags

    def list_channel_services(self):
        self.service_calls += 1
        return [{'channel': ['news'], 'dvb_servicetype': 2, 'encrypted': True}]

    def get_now_next(self, channels):
        self.now_next_calls += 1
        return self.now_next

    def image_url(self, reference):
        self.image_requests.append(reference)
        return f'http://127.0.0.1:9981/{reference}'

    def stream_url(self, channel):
        return f'http://tv.example/stream/{channel.uuid}'


def test_channel_list_columns_and_options_are_user_settings(monkeypatch, tmp_path):
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt6.QtGui import QColor, QPixmap

    from tvhplayer.channel_view import logo_image
    from tvhplayer.core.models import DvrEntry

    now = int(time.time())
    backend = _ExtrasBackend(now)
    requested = []
    app, ui, window = _channel_list_window(monkeypatch, tmp_path, backend)
    window.logo_loader.request = lambda server, reference, url: requested.append((reference, url))
    try:
        table = window.channel_list
        header = table.horizontalHeader()
        window.fetch_channels()
        _wait_for_channels(app, window)

        # Defaults: number, name, now, and status show; disabled channels are left out.
        assert [table.item(row, ui.COL_NAME).text() for row in range(table.rowCount())] == ['News', 'Sport']
        assert not header.isSectionHidden(ui.COL_NOW)
        assert header.isSectionHidden(ui.COL_NEXT) and header.isSectionHidden(ui.COL_TYPE)
        news_row = _channel_row(table, 'News')
        now_item = table.item(news_row, ui.COL_NOW)
        assert now_item.text() == 'Headlines'
        assert 'min left' in now_item.toolTip()
        assert abs(now_item.data(ui.PROGRESS_ROLE) - 0.5) < 0.01
        assert table.item(news_row, ui.COL_NEXT).text().endswith('Weather')
        assert 'Now: Headlines.' in table.item(news_row, ui.COL_NAME).data(Qt.ItemDataRole.AccessibleDescriptionRole)
        assert backend.service_calls == 0
        assert requested == [('imagecache/1', 'http://127.0.0.1:9981/imagecache/1')]

        # A logo that arrives later is drawn next to the name.
        image = QPixmap(80, 40)
        image.fill(Qt.GlobalColor.red)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        window._on_logo_loaded('imagecache/1', logo_image(bytes(data)))
        window._logo_timer.timeout.emit()
        icon = table.item(news_row, ui.COL_NAME).icon().pixmap(80, 40).toImage()
        assert icon.pixelColor(icon.width() // 2, icon.height() // 2) == QColor(Qt.GlobalColor.red)

        # Columns: the menu shows and hides them, and the choice is saved.
        window._channel_column_actions['type'].setChecked(True)
        assert not header.isSectionHidden(ui.COL_TYPE)
        assert backend.service_calls == 1
        assert table.item(_channel_row(table, 'News'), ui.COL_TYPE).text() == 'Radio, Encrypted'
        assert table.item(_channel_row(table, 'Sport'), ui.COL_TYPE).text() == 'HD'
        window._channel_column_actions['now'].setChecked(False)
        assert header.isSectionHidden(ui.COL_NOW)
        saved = window.config_store.load()['channel_list']
        assert saved['columns']['type'] is True and saved['columns']['now'] is False

        # Dragging a column saves the new order.
        header.moveSection(header.visualIndex(ui.COL_STATUS), 0)
        assert window.config_store.load()['channel_list']['order'][0] == 'status'

        # Options: progress bar, disabled channels, and the group filter.
        window._channel_option_actions['now_progress'].setChecked(False)
        assert table.item(_channel_row(table, 'News'), ui.COL_NOW).data(ui.PROGRESS_ROLE) is None
        window._channel_option_actions['hide_disabled'].setChecked(False)
        assert _channel_row(table, 'Off') >= 0
        assert window.tag_row.isVisibleTo(window)
        window.tag_combo.setCurrentIndex(window.tag_combo.findData('t-hd'))
        visible = [table.item(row, ui.COL_NAME).text() for row in range(table.rowCount()) if not table.isRowHidden(row)]
        assert visible == ['Sport']
        assert window.config_store.load()['channel_list']['tag'] == 't-hd'
        window._channel_option_actions['tag_filter'].setChecked(False)
        assert not window.tag_row.isVisibleTo(window)
        assert all(not table.isRowHidden(row) for row in range(table.rowCount()))

        # Recording marks come from the tasks pane's DVR read.
        entry = DvrEntry(uuid='r', title='T', channel_name='Sport', start=now, duration=60,
                         sched_status='recording', raw={'channel': 'sport'})
        window.channel_recordings_changed([entry])
        sport_row = _channel_row(table, 'Sport')
        assert table.item(sport_row, ui.COL_STATUS).text() == 'Recording'
        window.play_channel_by_data(backend.sport)
        assert table.item(_channel_row(table, 'Sport'), ui.COL_STATUS).text() == 'Playing, Recording'
        window._channel_option_actions['recording_status'].setChecked(False)
        assert table.item(_channel_row(table, 'Sport'), ui.COL_STATUS).text() == 'Playing'

        # Reset brings the defaults back.
        window._reset_channel_list_layout()
        assert header.visualIndex(ui.COL_NUMBER) == 0
        assert not header.isSectionHidden(ui.COL_NOW) and header.isSectionHidden(ui.COL_TYPE)
        assert _channel_row(table, 'Off') < 0
        assert window._channel_option_actions['tag_filter'].isChecked()
        assert window.config_store.load()['channel_list']['tag'] == ''
    finally:
        window.close()
        app.processEvents()


def test_now_next_is_fetched_again_when_a_programme_ends(monkeypatch, tmp_path):
    now = int(time.time())
    backend = _ExtrasBackend(now)
    app, ui, window = _channel_list_window(monkeypatch, tmp_path, backend)
    window.logo_loader.request = lambda *args: None
    try:
        window.fetch_channels()
        _wait_for_channels(app, window)
        assert backend.now_next_calls == 1
        window._tick_now_next()
        assert backend.now_next_calls == 1
        backend.now_next['news'].now.stop = now - 1
        window._now_next_fetched -= 61
        window._tick_now_next()
        assert backend.now_next_calls == 2
        news_row = _channel_row(window.channel_list, 'News')
        assert window.channel_list.item(news_row, ui.COL_NOW).text() == ''
    finally:
        window.close()
        app.processEvents()


def test_record_dialog_offers_the_programme_on_now(monkeypatch, tmp_path):
    import time

    from tvhplayer.core.models import Channel, EpgEvent

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    window.close()
    now = int(time.time())
    event = EpgEvent(start=now - 600, stop=now + 1800, title='Newsday', event_id=42)
    dialog = ui.RecordingDurationDialog(channel=Channel(uuid='c', name='BBC News'), event=event)
    try:
        assert dialog.windowTitle() == "Record on Server"
        assert list(dialog.preset_buttons) == ['prog', '30', '60', '120', '240', 'custom']
        assert dialog.preset_buttons['prog'].isChecked()
        assert dialog.programme_event() is event
        assert 1790 <= dialog.get_duration() <= 1800
        assert "stops when Newsday ends" in dialog.summary_label.text()
        assert dialog.custom_row.isHidden()

        dialog.preset_buttons['120'].setChecked(True)
        assert dialog.programme_event() is None
        assert dialog.get_duration() == 7200
        assert "2 h" in dialog.summary_label.text()

        dialog.preset_buttons['custom'].setChecked(True)
        assert not dialog.custom_row.isHidden()
        assert dialog.custom_spin.text() == "1 h 30 min"
        dialog.more_btn.click()
        assert dialog.get_duration() == 105 * 60
        dialog.less_btn.click()
        dialog.less_btn.click()
        assert dialog.custom_spin.text() == "1 h 15 min"
        dialog.set_duration(0, 30)
        assert dialog.preset_buttons['30'].isChecked()
    finally:
        dialog.close()

    # Without guide data, or once the programme is over, there is nothing to offer.
    ended = EpgEvent(start=now - 3600, stop=now - 60, title='Old', event_id=7)
    for given in (None, ended):
        dialog = ui.RecordingDurationDialog(event=given)
        assert 'prog' not in dialog.preset_buttons
        assert dialog.preset_buttons['60'].isChecked()
        assert dialog.get_duration() == 3600
        dialog.close()
    app.processEvents()


def test_player_bar_play_stop_and_record_controls(monkeypatch, tmp_path):
    import time

    from tvhplayer.core.models import Channel, DvrEntry

    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)

    class FakeRecorder:
        is_running = False
        file_path = ''

        def stop(self):
            self.is_running = False

    try:
        window.show()
        app.processEvents()
        bar = window.controls_bar
        assert window.play_btn.accessibleName() == "Play"

        played = []
        stopped = []
        window.play_channel_by_data = lambda channel: played.append(channel)
        real_stop = window.stop_playback
        window.stop_playback = lambda: (stopped.append(True), real_stop())
        window.play_btn.click()
        assert played and not stopped

        window._show_playback_wait()
        assert window.play_btn.accessibleName() == "Stop"
        window._on_playback_started()
        assert window.play_btn.accessibleName() == "Stop"
        window.play_btn.click()
        assert stopped == [True]
        assert window.play_btn.accessibleName() == "Play"

        recorder = FakeRecorder()
        channel = Channel(uuid='c', name='BBC News')
        window.local_jobs = [ui.LocalJob(recorder, channel)]
        window.active_channel = lambda: channel
        recording = DvrEntry(
            uuid='r', title='Newsday', channel_name='BBC News', raw={'channel': 'c'},
            start=int(time.time()) - 60, duration=600, status='Running', sched_status='recording',
        )
        assert recording.category() == 'recording'

        # Recording on the server: the red pill stops it straight away.
        window.channel_recordings_changed([recording])
        assert not window.record_btn.isVisible()
        assert window.stop_record_btn.isVisible()
        assert bar.record_server_action.isEnabled() is False
        assert bar.record_local_action.isEnabled() is True
        calls = []
        window.stop_recording = lambda: calls.append('server')
        window.stop_local_recording = lambda: calls.append('local')
        window.stop_record_btn.click()
        assert calls == ['server']

        # Both kinds: Stop asks which, and the menu can stop both.
        recorder.is_running = True
        window._sync_record_controls()
        assert bar.record_local_action.isEnabled() is False
        assert "BBC News" in bar._stop_detail.text()
        window.stop_record_btn.click()
        app.processEvents()
        assert bar.stop_menu.isVisible()
        bar.stop_menu.hide()
        assert calls == ['server']
        bar.stop_both_action.trigger()
        assert calls == ['server', 'server', 'local']

        # Only this computer: Stop ends the local recording.
        window.channel_recordings_changed([])
        window.stop_record_btn.click()
        assert calls[-1] == 'local'

        recorder.is_running = False
        window._sync_record_controls()
        assert window.record_btn.isVisible()
        assert not window.stop_record_btn.isVisible()
        window.record_btn.click()
        app.processEvents()
        assert bar.record_menu.isVisible()
        bar.record_menu.hide()
    finally:
        window.close()
        app.processEvents()


def test_tv_guide_opens_from_the_view_menu_at_the_selected_channel(monkeypatch, tmp_path):
    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        import tvhplayer.guide_view as guide_view

        actions = {action.text(): action for menu in window.menuBar().findChildren(ui.QMenu) for action in menu.actions()}
        guide_action = actions['TV &Guide']
        assert guide_action.shortcut().toString() == 'Ctrl+G'
        channels = [ui.Channel(uuid='a', name='Alpha', number=1), ui.Channel(uuid='b', name='Bravo', number=2)]
        window._channels = channels
        monkeypatch.setattr(window, 'selected_channel', lambda: channels[1])
        monkeypatch.setattr(window, '_server_requests_ready', lambda: False)
        guide_action.trigger()
        guide = window._guide
        assert isinstance(guide, guide_view.GuideWindow)
        assert guide.isVisible()
        assert [channel.name for channel in guide.grid.channels] == ['Alpha', 'Bravo']
        assert guide.grid.current_channel().name == 'Bravo'
        # Without a server there is nothing to read, and the grid says why.
        assert 'server' in guide.grid.message
        window.channel_recordings_changed([])
        assert guide.grid.recordings == {}
        assert window.guide_btn.accessibleName() == 'TV guide'
        assert window.guide_btn.text() == 'TV Guide'
        window.selected_channel = lambda: channels[0]
        window.guide_btn.click()
        assert window._guide is guide
        assert guide.grid.current_channel().name == 'Alpha'
        window.show_guide(channels[0])
        assert window._guide is guide
        assert guide.grid.current_channel().name == 'Alpha'
    finally:
        guide = getattr(window, '_guide', None)
        if guide is not None:
            guide.shutdown()
            guide.close()
        window.close()
        app.processEvents()


def test_playback_menu_lists_tracks_and_deinterlace(monkeypatch, tmp_path):
    app, ui, window, fake_player = _make_player(monkeypatch, tmp_path)
    try:
        fake_player.audio = [(-1, b'Disable'), (1, b'Track 1 - [English]'), (2, b'Track 2 - [Deutsch]')]
        fake_player.audio_id = 1
        fake_player.spu = [(-1, b'Disable'), (5, b'DVB subtitles')]
        menu = window.playback_menu
        window._fill_playback_menu(menu)
        submenus = {action.text(): action.menu() for action in menu.actions()}
        audio = submenus['&Audio Track']
        assert [a.text() for a in audio.actions()] == ['Track 1 - [English]', 'Track 2 - [Deutsch]']
        assert audio.actions()[0].isChecked()
        audio.actions()[1].trigger()
        assert fake_player.audio_id == 2

        subtitles = submenus['&Subtitles']
        assert [a.text() for a in subtitles.actions()] == ['Off', 'DVB subtitles']
        assert subtitles.actions()[0].isChecked()
        subtitles.actions()[1].trigger()
        assert fake_player.spu_id == 5

        deinterlace = submenus['&Deinterlace']
        assert [a.isChecked() for a in deinterlace.actions()] == [True, False, False]
        deinterlace.actions()[1].trigger()
        assert window.config['deinterlace'] == 'on'
        assert fake_player.deinterlace == 'yadif2x'
        deinterlace.actions()[2].trigger()
        assert fake_player.deinterlace == ''
        # Filled again when it opens, so the list follows the stream.
        window._fill_playback_menu(menu)
        assert len(menu.actions()) == 3
    finally:
        window.close()
        app.processEvents()


def test_spinner_shows_tuner_signal(monkeypatch, tmp_path):
    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        spinner = ui.PlaybackSpinner()
        spinner.resize(400, 300)
        spinner.set_caption('Waiting for channel')
        spinner.set_signal('poor', 'Signal too weak (SNR 5 dB): check the aerial, dish, or cable')
        assert spinner.accessibleName() == (
            'Waiting for channel Signal too weak (SNR 5 dB): check the aerial, dish, or cable'
        )
        assert not spinner.grab().isNull()
        spinner.set_signal('', '')
        assert spinner.accessibleName() == 'Waiting for channel'

        window._awaiting_playback = True
        watch = types.SimpleNamespace(stop=lambda: None)
        window._start_watch = watch
        window._on_start_signal(watch, 'none', 'No signal: check the aerial, dish, or cable')
        window._on_start_given_up(watch)
        assert window.status_label.text() == (
            'This channel is not working right now. No signal: check the aerial, dish, or cable.'
        )
    finally:
        window.close()
        app.processEvents()


def test_conflict_dialog_makes_the_chosen_recording_important(monkeypatch, tmp_path):
    from tvhplayer.core.models import DvrEntry

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        entries = [
            DvrEntry(uuid='a', title='News', channel_name='BBC ONE', start=1_800_000_000, duration=3600),
            DvrEntry(uuid='b', title='Film', channel_name='ITV', start=1_800_001_800, duration=7200),
        ]
        dialog = ui.RecordingConflictDialog(entries, 1, window)
        assert dialog.list.count() == 2
        assert dialog.list.item(1).text().startswith('Film on ITV, ')
        dialog.list.setCurrentRow(1)
        updates = []
        backend = types.SimpleNamespace(update_dvr_entry=lambda entry, update: updates.append((entry, update)))
        monkeypatch.setattr(window, 'get_backend', lambda: backend)
        window._conflict_answered(dialog, ui.QDialog.DialogCode.Accepted)
        assert updates[0][0] is entries[1]
        assert updates[0][1].priority == 0
        window._conflict_answered(dialog, ui.QDialog.DialogCode.Rejected)
        assert len(updates) == 1
    finally:
        window.close()
        app.processEvents()


def test_channels_without_a_logo_use_a_picon(monkeypatch, tmp_path):
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QColor, QPixmap

    from tvhplayer.core.models import Channel
    from tvhplayer.core.picons import PiconIndex

    app, ui, window, _fake_player = _make_player(monkeypatch, tmp_path)
    try:
        pixmap = QPixmap(10, 6)
        pixmap.fill(QColor('red'))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, 'PNG')
        (tmp_path / 'bbcone.png').write_bytes(bytes(buffer.data()))
        window.picons = PiconIndex(tmp_path)
        plain = Channel(uuid='1', name='BBC One HD')
        reference = window.channel_logo_reference(plain)
        assert reference == f"picon:{tmp_path / 'bbcone.png'}"
        # The file is read off the UI thread; the logo is there once it arrives.
        assert window._logo_for(reference, None) is None
        deadline = time.monotonic() + 5
        while window._logo_for(reference, None) is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert window._logo_for(reference, None) is not None
        served = Channel(uuid='2', name='BBC One', icon='imagecache/7')
        assert window.channel_logo_reference(served) == 'imagecache/7'
        assert window.channel_logo_reference(Channel(uuid='3', name='Nothing')) == ''
        window.picons = None
        assert window.channel_logo_reference(plain) == ''
    finally:
        window.close()
        app.processEvents()

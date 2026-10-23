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


class _FakeVlcPlayer:
    def __init__(self):
        self.key_input = None
        self.mouse_input = None
        self._muted = 0
        self._playing = False

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

    app = QApplication.instance() or QApplication([])
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
        assert window.video_frame.parent() is window.right_pane
        assert window.left_pane.isVisible()
        assert window.controls_bar.isVisible()
        assert not window.is_fullscreen

        window.toggle_fullscreen()
        app.processEvents()

        assert window.is_fullscreen
        assert window.video_frame.parent() is window.right_pane
        assert not window.left_pane.isVisible()
        assert not window.controls_bar.isVisible()
        assert not window.menuBar().isVisible()
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
        assert window.video_frame.parent() is window.right_pane
    finally:
        window.close()
        app.processEvents()

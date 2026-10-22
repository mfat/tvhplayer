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

import builtins
import sys
import types

from tvhplayer.core.engine import mpv_missing


def test_mpv_missing_is_empty_when_libmpv_loads(monkeypatch):
    monkeypatch.setitem(sys.modules, 'mpv', types.ModuleType('mpv'))
    pyqt6 = types.ModuleType('PyQt6')
    pyqt6.QtOpenGLWidgets = types.ModuleType('PyQt6.QtOpenGLWidgets')
    monkeypatch.setitem(sys.modules, 'PyQt6', pyqt6)
    monkeypatch.setitem(sys.modules, 'PyQt6.QtOpenGLWidgets', pyqt6.QtOpenGLWidgets)
    assert mpv_missing() == ''


def test_mpv_missing_reports_import_failure(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'mpv' or (isinstance(name, str) and name.startswith('mpv.')):
            raise ImportError('Cannot find libmpv')
        return real_import(name, *args, **kwargs)

    sys.modules.pop('mpv', None)
    monkeypatch.setattr(builtins, '__import__', fake_import)
    assert 'Cannot find libmpv' in mpv_missing()

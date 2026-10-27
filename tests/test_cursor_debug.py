import os

from tvhplayer import cursor_debug


def test_off_unless_asked(monkeypatch):
    monkeypatch.delenv(cursor_debug.DEBUG_ENV, raising=False)
    assert cursor_debug.level() == 0
    monkeypatch.setenv(cursor_debug.DEBUG_ENV, '0')
    assert cursor_debug.level() == 0
    monkeypatch.setenv(cursor_debug.DEBUG_ENV, '1')
    assert cursor_debug.level() == 1
    monkeypatch.setenv(cursor_debug.DEBUG_ENV, '2')
    assert cursor_debug.level() == 2


def test_level_two_adds_wayland_logging_to_existing_rules(monkeypatch):
    monkeypatch.setenv(cursor_debug.DEBUG_ENV, '2')
    monkeypatch.setenv('QT_LOGGING_RULES', 'qt.multimedia*=true')
    cursor_debug.prepare()
    assert os.environ['QT_LOGGING_RULES'] == f'qt.multimedia*=true;{cursor_debug.WAYLAND_RULES}'


def test_level_one_leaves_qt_logging_alone(monkeypatch):
    monkeypatch.setenv(cursor_debug.DEBUG_ENV, '1')
    monkeypatch.delenv('QT_LOGGING_RULES', raising=False)
    cursor_debug.prepare()
    assert 'QT_LOGGING_RULES' not in os.environ

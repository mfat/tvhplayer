from PyQt6.QtCore import QByteArray, QRect, QSize
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QMainWindow


def _close(*windows):
    for window in windows:
        window.close()
        window.deleteLater()
    QApplication.instance().processEvents()

from tvhplayer.window_frame import restore_window_placement, save_window_placement


class _Placement:
    """A window whose frame inset is the one measured on Windows.

    pos() is the frame. geometry() and normalGeometry() are the client.
    While maximized the client fills the screen and the normal client
    rectangle is the size the window had before.
    """

    def __init__(self, maximized=False, fullscreen=False, minimized=False, normal=True):
        self._maximized = maximized
        self._fullscreen = fullscreen
        self._minimized = minimized
        self._normal = normal
        self.saved = QByteArray(b'placement')

    def isFullScreen(self):
        return self._fullscreen

    def isMinimized(self):
        return self._minimized

    def isMaximized(self):
        return self._maximized

    def saveGeometry(self):
        return QByteArray(self.saved)

    def x(self):
        return 0 if self._maximized else 220

    def y(self):
        return -8 if self._maximized else 160

    def width(self):
        return 2560 if self._maximized else 800

    def height(self):
        return 1377 if self._maximized else 600

    def geometry(self):
        if self._maximized:
            return QRect(0, 23, 2560, 1377)
        return QRect(220, 191, 800, 600)

    def normalGeometry(self):
        if not self._normal:
            return QRect()
        return QRect(220, 191, 800, 600)


def test_maximized_window_keeps_its_normal_frame_placement():
    # Frame top is y=160; the client starts 31px lower. The screen size must
    # not become the size restored when the window is not maximized.
    window = _Placement(maximized=True)
    config = {}
    save_window_placement(window, config)
    assert config['window_geometry'] == dict(x=220, y=160, width=800, height=600)
    assert config['window_placement']
    save_window_placement(window, config)
    assert config['window_geometry'] == dict(x=220, y=160, width=800, height=600)


def test_normal_window_stores_the_frame_position_and_client_size():
    window = _Placement()
    config = {}
    save_window_placement(window, config)
    assert config['window_geometry'] == dict(x=220, y=160, width=800, height=600)


def test_fullscreen_and_minimized_do_not_replace_a_saved_placement():
    kept = {'window_geometry': dict(x=1, y=2, width=3, height=4), 'window_placement': 'kept'}
    for window in (_Placement(fullscreen=True), _Placement(minimized=True)):
        config = dict(kept)
        config['window_geometry'] = dict(kept['window_geometry'])
        save_window_placement(window, config)
        assert config == {'window_geometry': dict(x=1, y=2, width=3, height=4), 'window_placement': 'kept'}


def test_maximized_window_with_no_normal_size_does_not_store_the_screen():
    window = _Placement(maximized=True, normal=False)
    config = {'window_geometry': dict(x=5, y=6, width=7, height=8)}
    save_window_placement(window, config)
    assert config['window_geometry'] == dict(x=5, y=6, width=7, height=8)
    assert config['window_placement']


def test_saved_placement_is_restored_without_the_old_position(qapp):
    original = QMainWindow()
    other = QMainWindow()
    third = QMainWindow()
    try:
        original.resize(640, 480)
        original.move(40, 50)
        config = {}
        save_window_placement(original, config)
        restore_window_placement(other, dict(x=9, y=9, width=100, height=100), config['window_placement'])
        assert (other.x(), other.y(), other.width(), other.height()) == (40, 50, 640, 480)
        # A second launch reads what the first wrote.
        again = {}
        save_window_placement(other, again)
        restore_window_placement(third, dict(x=1, y=1, width=2, height=2), again['window_placement'])
        assert (third.x(), third.y(), third.width(), third.height()) == (40, 50, 640, 480)
    finally:
        _close(original, other, third)


def test_old_position_is_applied_with_move_and_not_round_tripped(qapp):
    window = QMainWindow()

    def rejected(blob):
        return False

    def not_saved():
        raise AssertionError('the old position must not be saved and restored before the window is shown')

    window.restoreGeometry = rejected
    window.saveGeometry = not_saved
    try:
        restore_window_placement(window, dict(x=120, y=80, width=640, height=480), saved='@@@')
        assert (window.x(), window.y(), window.width(), window.height()) == (120, 80, 640, 480)
        # The same point again does not walk.
        restore_window_placement(window, dict(x=120, y=80, width=640, height=480), saved=None)
        assert (window.x(), window.y(), window.width(), window.height()) == (120, 80, 640, 480)
    finally:
        _close(window)


def test_a_placement_from_a_removed_monitor_comes_back_on_screen(qapp):
    window = QMainWindow()
    try:
        restore_window_placement(window, dict(x=-100000, y=-100000, width=800, height=600), saved='')
        screens = QGuiApplication.screens()
        assert screens
        pos = window.pos()
        assert any(screen.availableGeometry().contains(pos) for screen in screens)
        # A position already on a screen stays there.
        home = QRect(screens[0].availableGeometry().topLeft(), QSize(400, 300))
        restore_window_placement(
            window, dict(x=home.x(), y=home.y(), width=home.width(), height=home.height()), saved=None,
        )
        assert (window.x(), window.y(), window.width(), window.height()) == (
            home.x(), home.y(), home.width(), home.height(),
        )
    finally:
        _close(window)


def test_placement_that_is_not_text_falls_back_to_the_old_position(qapp):
    window = QMainWindow()
    try:
        restore_window_placement(window, dict(x=30, y=40, width=500, height=400), saved='not ascii \u2603')
        assert (window.x(), window.y(), window.width(), window.height()) == (30, 40, 500, 400)
    finally:
        _close(window)

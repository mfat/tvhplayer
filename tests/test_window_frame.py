from PyQt6.QtCore import QMargins, QPoint, QSize, Qt
from PyQt6.QtWidgets import QMainWindow, QMenuBar, QWidget

from tvhplayer.window_frame import (
    SHADOW_MARGINS,
    TITLE_BAR_HEIGHT,
    WindowFrame,
    cursor_for,
    edges_at,
    kde_button_layout,
    kwin_button_layout,
    parse_button_layout,
    wants_own_title_bar,
)

GNOME = {'XDG_CURRENT_DESKTOP': 'ubuntu:GNOME'}
KDE = {'XDG_CURRENT_DESKTOP': 'KDE'}


def test_gnome_and_kde_can_have_the_apps_title_bar():
    assert wants_own_title_bar('wayland', GNOME)
    assert wants_own_title_bar('wayland', {'XDG_CURRENT_DESKTOP': 'GNOME'})
    assert wants_own_title_bar('wayland', KDE)
    # GNOME draws the title bar of X11 windows, and other desktops keep theirs.
    assert not wants_own_title_bar('xcb', GNOME)
    assert not wants_own_title_bar('wayland', {'XDG_CURRENT_DESKTOP': 'XFCE'})
    assert not wants_own_title_bar('wayland', {})
    assert not wants_own_title_bar('cocoa', KDE)


def test_kde_on_x11_needs_a_compositor_for_the_shadow():
    assert wants_own_title_bar('xcb', KDE, compositing=True)
    assert not wants_own_title_bar('xcb', KDE, compositing=False)
    # Under XWayland, as with VLC in a Wayland session, the compositor is always there.
    assert wants_own_title_bar('xcb', {**KDE, 'WAYLAND_DISPLAY': 'wayland-0'}, compositing=False)


def test_kwin_button_order_is_followed(tmp_path):
    assert kwin_button_layout() == ':minimize,maximize,close'
    assert parse_button_layout(kwin_button_layout('XAI', 'M')) == (['close', 'maximize', 'minimize'], [])
    (tmp_path / 'kwinrc').write_text(
        '[org.kde.kdecoration2]\nButtonsOnLeft=X\nButtonsOnRight=IA\n', encoding='utf-8'
    )
    assert kde_button_layout({'XDG_CONFIG_HOME': str(tmp_path)}) == 'close:minimize,maximize'
    assert kde_button_layout({'XDG_CONFIG_HOME': str(tmp_path / 'none')}) == ':minimize,maximize,close'


def test_button_layout_keeps_the_window_buttons_on_their_sides():
    assert parse_button_layout('icon:minimize,maximize,close') == ([], ['minimize', 'maximize', 'close'])
    assert parse_button_layout('appmenu:close') == ([], ['close'])
    assert parse_button_layout('close,minimize:') == (['close', 'minimize'], [])
    assert parse_button_layout('') == ([], [])


def test_edges_and_corners_resize_as_expected():
    size, m = QSize(800, 600), QMargins(14, 10, 14, 18)
    assert edges_at(QPoint(400, 2), size, m) == Qt.Edge.TopEdge
    assert edges_at(QPoint(2, 300), size, m) == Qt.Edge.LeftEdge
    assert edges_at(QPoint(795, 300), size, m) == Qt.Edge.RightEdge
    assert edges_at(QPoint(400, 595), size, m) == Qt.Edge.BottomEdge
    # Near a corner, on either side of it, both edges move.
    assert edges_at(QPoint(20, 2), size, m) == Qt.Edge.LeftEdge | Qt.Edge.TopEdge
    assert edges_at(QPoint(2, 20), size, m) == Qt.Edge.LeftEdge | Qt.Edge.TopEdge
    assert edges_at(QPoint(790, 590), size, m) == Qt.Edge.RightEdge | Qt.Edge.BottomEdge
    assert cursor_for(Qt.Edge.LeftEdge | Qt.Edge.TopEdge) == Qt.CursorShape.SizeFDiagCursor
    assert cursor_for(Qt.Edge.RightEdge | Qt.Edge.TopEdge) == Qt.CursorShape.SizeBDiagCursor
    assert cursor_for(Qt.Edge.TopEdge) == Qt.CursorShape.SizeVerCursor


def test_frame_holds_the_menus_and_makes_room_for_the_shadow(qapp):
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    menubar.addMenu('&File')
    frame = WindowFrame(window, menubar, button_layout='icon:minimize,maximize,close')
    try:
        assert window.menuWidget() is frame.title_bar
        assert menubar.parent() is frame.title_bar
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert window.contentsMargins() == SHADOW_MARGINS
        assert set(frame.title_bar.buttons) == {'minimize', 'maximize', 'close'}
        assert frame.title_bar.height() == TITLE_BAR_HEIGHT
        window.setWindowState(Qt.WindowState.WindowMaximized)
        qapp.processEvents()
        assert window.contentsMargins() == QMargins()
        assert frame.title_bar.buttons['maximize'].accessibleName() == 'Restore'
    finally:
        window.deleteLater()
        qapp.processEvents()

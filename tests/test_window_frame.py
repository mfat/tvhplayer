from pathlib import Path

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
    # Under XWayland the compositor is always there.
    assert wants_own_title_bar('xcb', {**KDE, 'WAYLAND_DISPLAY': 'wayland-0'}, compositing=False)


def test_kwin_button_order_is_followed(tmp_path, monkeypatch):
    assert kwin_button_layout() == ':minimize,maximize,close'
    assert parse_button_layout(kwin_button_layout('XAI', 'M')) == (['close', 'maximize', 'minimize'], [])
    (tmp_path / 'kwinrc').write_text(
        '[org.kde.kdecoration2]\nButtonsOnLeft=X\nButtonsOnRight=IA\n', encoding='utf-8'
    )
    assert kde_button_layout({'XDG_CONFIG_HOME': str(tmp_path)}) == 'close:minimize,maximize'
    # In Flatpak XDG_CONFIG_HOME is the sandbox's; the host's kwinrc is shared in ~/.config.
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    no_portal = lambda: None  # noqa: E731
    assert kde_button_layout({'XDG_CONFIG_HOME': str(tmp_path / 'none')}, no_portal) == ':minimize,maximize,close'
    (tmp_path / 'home' / '.config').mkdir(parents=True)
    (tmp_path / 'kwinrc').rename(tmp_path / 'home' / '.config' / 'kwinrc')
    assert kde_button_layout({'XDG_CONFIG_HOME': str(tmp_path / 'sandbox')}) == 'close:minimize,maximize'


def test_flatpak_on_kde_reads_the_button_order_from_the_portal(tmp_path, monkeypatch):
    # The Flatpak cannot read kwinrc. Plasma's portal answers the GNOME key,
    # which Plasma keeps in step with KWin's order.
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    sandbox = {'XDG_CONFIG_HOME': str(tmp_path / 'sandbox')}
    assert kde_button_layout(sandbox, lambda: 'close:minimize,maximize') == 'close:minimize,maximize'
    # A kwinrc that can be read wins: the app outside Flatpak.
    (tmp_path / 'sandbox').mkdir()
    (tmp_path / 'sandbox' / 'kwinrc').write_text(
        '[org.kde.kdecoration2]\nButtonsOnLeft=\nButtonsOnRight=X\n', encoding='utf-8'
    )
    assert kde_button_layout(sandbox, lambda: 'close:minimize,maximize') == ':close'


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


def test_styles_that_ask_for_the_menu_bar_keep_the_title_bar(qapp):
    # Breeze asks every main window for its menu bar; one that is no menu bar
    # would be replaced by a new empty one and the title bar deleted.
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    menubar.addMenu('&File')
    frame = WindowFrame(window, menubar, button_layout='icon:minimize,maximize,close')
    try:
        assert window.menuBar() is frame.title_bar
        assert window.menuWidget() is frame.title_bar
        assert not frame.title_bar.isNativeMenuBar()
        frame.title_bar.sync_state()
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_title_follows_a_palette_change_while_the_window_is_open(qapp):
    # Switching light to dark while the app runs left the title in the old,
    # dark ink on the new dark title bar.
    from PyQt6.QtGui import QColor, QPalette

    def palette(window, ink):
        p = QPalette(qapp.palette())
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            p.setColor(group, QPalette.ColorRole.Window, QColor(window))
            p.setColor(group, QPalette.ColorRole.WindowText, QColor(ink))
        return p

    saved = qapp.palette()
    qapp.setPalette(palette('#f6f5f4', '#1d1d20'))
    window = QMainWindow()
    window.setWindowTitle('TVHplayer')
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    menubar.addMenu('&File')
    frame = WindowFrame(window, menubar, button_layout='icon:minimize,maximize,close')
    try:
        window.resize(800, 600)
        window.show()
        qapp.processEvents()
        qapp.setPalette(palette('#1d1d20', '#f6f5f4'))
        qapp.processEvents()
        title = frame.title_bar.title
        ink = title.palette().color(QPalette.ColorRole.WindowText)
        assert ink.red() > 200, title.styleSheet()
    finally:
        qapp.setPalette(saved)
        window.deleteLater()
        qapp.processEvents()


def _framer(qapp):
    from tvhplayer.window_frame import DialogFramer

    return DialogFramer(qapp, button_layout='icon:minimize,maximize,close')


def test_dialogs_get_the_apps_title_bar_too(qapp):
    # Only the main window had it; dialogs kept the desktop's pale stand-in.
    from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    parent = QWidget()
    dialog = QDialog(parent)
    dialog.setWindowTitle('Settings')
    QVBoxLayout(dialog).addWidget(QLabel('Hello'))
    try:
        dialog.resize(400, 300)
        dialog.show()
        qapp.processEvents()
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert dialog.windowHandle().flags() & Qt.WindowType.FramelessWindowHint
        bar = dialog.findChild(TitleBar)
        assert bar is not None and bar.menubar is None
        m = SHADOW_MARGINS
        assert dialog.contentsMargins() == m + QMargins(0, TITLE_BAR_HEIGHT, 0, 0)
        assert bar.geometry().topLeft() == QPoint(m.left(), m.top())
        # The content keeps the size it was given.
        assert dialog.size() == QSize(400 + m.left() + m.right(), 300 + m.top() + m.bottom() + TITLE_BAR_HEIGHT)
        # A dialog of another window is not minimized on its own.
        assert set(bar.buttons) == {'maximize', 'close'}
        assert bar.title.text() == 'Settings'
    finally:
        framer.deleteLater()
        parent.deleteLater()
        qapp.processEvents()


def test_message_boxes_get_it_without_maximize(qapp):
    from PyQt6.QtWidgets import QMessageBox

    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    box = QMessageBox(QMessageBox.Icon.Warning, 'Oops', 'Something went wrong.')
    try:
        box.show()
        qapp.processEvents()
        bar = box.findChild(TitleBar)
        assert bar is not None
        assert box.minimumSize() == box.maximumSize()
        assert bar.buttons['maximize'].isHidden()
        assert not bar.buttons['close'].isHidden()
        assert box.contentsMargins().top() == SHADOW_MARGINS.top() + TITLE_BAR_HEIGHT
    finally:
        framer.deleteLater()
        box.deleteLater()
        qapp.processEvents()


def test_menus_and_marked_windows_keep_their_frame(qapp):
    from PyQt6.QtWidgets import QMenu

    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    menu = QMenu()
    menu.addAction('One')
    plain = QWidget()
    plain.setProperty('systemFrame', True)
    try:
        assert not framer.wants(menu)
        assert not framer.wants(plain)
        plain.show()
        qapp.processEvents()
        assert plain.findChild(TitleBar) is None
    finally:
        framer.deleteLater()
        menu.deleteLater()
        plain.deleteLater()
        qapp.processEvents()


def test_a_restored_size_is_not_grown_again(qapp):
    from PyQt6.QtWidgets import QDialog

    from PyQt6.QtWidgets import QLabel, QVBoxLayout

    framer = _framer(qapp)
    dialog = QDialog()
    dialog.setProperty('geometryRestored', True)
    QVBoxLayout(dialog).addWidget(QLabel('Guide'))
    try:
        dialog.resize(700, 500)
        dialog.show()
        qapp.processEvents()
        assert dialog.size() == QSize(700, 500)
        # Each further window of its own, not a dialog of another, can be minimized.
        from tvhplayer.window_frame import TitleBar

        assert 'minimize' in dialog.findChild(TitleBar).buttons
    finally:
        framer.deleteLater()
        dialog.deleteLater()
        qapp.processEvents()


def _right_click(qapp, widget):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent

    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, widget.mapToGlobal(pos), Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(widget, event)


from PyQt6.QtCore import QEvent  # noqa: E402


def test_right_click_asks_the_desktop_for_its_window_menu(qapp, monkeypatch):
    # The title bar ignored right clicks: GNOME's window menu was gone.
    from tvhplayer import window_frame

    asked = []
    monkeypatch.setattr(window_frame.window_menu, 'show', lambda window, pos, global_pos: asked.append(pos) or True)
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    menubar.addMenu('&File')
    frame = WindowFrame(window, menubar, button_layout='icon:minimize,maximize,close')
    try:
        window.resize(800, 600)
        window.show()
        qapp.processEvents()
        _right_click(qapp, frame.title_bar)
        assert len(asked) == 1
        # Where the press was, in the window: the title bar sits inside the shadow margins.
        assert asked[0].y() >= SHADOW_MARGINS.top()
        assert qapp.activePopupWidget() is None
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_right_click_shows_the_apps_menu_where_the_desktop_has_none(qapp, monkeypatch):
    from tvhplayer import window_frame

    monkeypatch.setattr(window_frame.window_menu, 'show', lambda *args: False)
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    menubar.addMenu('&File')
    frame = WindowFrame(window, menubar, button_layout='icon:minimize,maximize,close')
    try:
        window.resize(800, 600)
        window.show()
        qapp.processEvents()
        menu = frame.title_bar.fallback_menu()
        names = [action.text() for action in menu.actions() if not action.isSeparator()]
        assert names == ['Mi&nimize', 'Ma&ximize', '&Close']
        menu.deleteLater()
        _right_click(qapp, frame.title_bar)
        qapp.processEvents()
        popup = qapp.activePopupWidget()
        assert popup is not None
        popup.close()
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_window_menu_is_not_asked_for_where_it_cannot_be(qapp):
    from tvhplayer import window_menu

    # The tests run offscreen: neither Wayland nor X11.
    assert window_menu.show(QWidget(), QPoint(1, 1), QPoint(1, 1)) is False


def test_dialogs_are_see_through_from_the_start(qapp):
    # A native window takes its see-through background only as it is made.
    # Dialogs were framed when shown, after it was made: their shadow was black.
    from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QVBoxLayout

    framer = _framer(qapp)
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(QLabel('Hello'))
    # As QMessageBox.warning() makes one: built and shown at once.
    box = QMessageBox(QMessageBox.Icon.Warning, 'Oops', 'Something went wrong.')
    try:
        for window in (dialog, box):
            window.show()
            qapp.processEvents()
            assert window.windowHandle().format().alphaBufferSize() == 8, type(window).__name__
    finally:
        framer.deleteLater()
        dialog.deleteLater()
        box.deleteLater()
        qapp.processEvents()


def test_a_window_made_before_it_could_be_prepared_keeps_the_system_frame(qapp):
    from PyQt6.QtWidgets import QDialog

    from tvhplayer.window_frame import TitleBar

    dialog = QDialog()
    dialog.winId()  # its native window is made before the framer sees it
    framer = _framer(qapp)
    try:
        dialog.show()
        qapp.processEvents()
        assert dialog.findChild(TitleBar) is None
        assert not dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    finally:
        framer.deleteLater()
        dialog.deleteLater()
        qapp.processEvents()

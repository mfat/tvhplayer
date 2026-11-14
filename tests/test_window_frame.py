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
    own_title_bar_by_default,
    uses_own_title_bar,
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


def test_only_gnome_on_wayland_has_it_until_chosen():
    assert own_title_bar_by_default('wayland', GNOME)
    assert own_title_bar_by_default('wayland-egl', {'XDG_CURRENT_DESKTOP': 'GNOME'})
    # KDE draws a title bar of its own; elsewhere the app cannot draw one.
    assert not own_title_bar_by_default('wayland', KDE)
    assert not own_title_bar_by_default('xcb', GNOME)
    assert not own_title_bar_by_default('windows', {})
    assert not own_title_bar_by_default('cocoa', {})
    assert uses_own_title_bar(None, 'wayland', GNOME)
    assert not uses_own_title_bar(None, 'wayland', KDE)
    # A choice made in Settings wins where the switch is offered.
    assert not uses_own_title_bar(False, 'wayland', GNOME)
    assert uses_own_title_bar(True, 'wayland', KDE)
    # And is ignored where it is not.
    assert not uses_own_title_bar(True, 'xcb', GNOME)
    assert not uses_own_title_bar(True, 'windows', {})


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

    framer = DialogFramer(qapp, button_layout='icon:minimize,maximize,close')
    # deleteLater() alone left it watching: processEvents() does not run deferred deletes.
    framer.deleteLater = lambda: qapp.removeEventFilter(framer)
    return framer


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


def test_widgets_built_alone_and_then_placed_in_a_window_stay_plain(qapp):
    # The main window's parts are built without a parent, so for a moment they
    # are windows of their own: each got a title bar inside the main window.
    from PyQt6.QtWidgets import QLabel, QVBoxLayout

    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    host = QWidget()
    QVBoxLayout(host)
    part = QWidget()
    QVBoxLayout(part).addWidget(QLabel('Channels'))
    part.setWindowTitle('TVHplayer')
    # A main window is prepared while it is built, then put inside another window.
    inner = QMainWindow()
    inner.setCentralWidget(QLabel('Guide'))
    inner.setWindowTitle('Guide')
    try:
        assert inner.property('_tvhFramePrepared') is not None
        assert part.property('_tvhFramePrepared') is None
        host.layout().addWidget(part)
        host.layout().addWidget(inner)
        assert inner.property('_tvhFramePrepared') is None
        host.show()
        qapp.processEvents()
        for widget in (part, inner):
            assert widget.findChild(TitleBar) is None
            assert not widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            assert not widget.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
            assert not widget.windowFlags() & Qt.WindowType.FramelessWindowHint
            assert widget.contentsMargins() == QMargins()
    finally:
        framer.deleteLater()
        host.deleteLater()
        qapp.processEvents()


# --- the native window menu is tried only where it is known to be safe ---


def test_native_window_menu_only_on_checked_qt_versions():
    from tvhplayer.window_menu import verified_qt

    assert not verified_qt((6, 4, 2))  # no native interface yet
    assert verified_qt((6, 5, 0))
    assert verified_qt((6, 10, 2))
    assert verified_qt((6, 11, 3))
    # Not checked yet: the app's own menu until it is.
    assert not verified_qt((6, 12, 0))
    assert not verified_qt((7, 0, 0))


def test_a_crash_while_trying_turns_the_native_menu_off_for_good(tmp_path):
    from tvhplayer.window_menu import CrashGuard

    path = tmp_path / 'window-menu.json'
    guard = CrashGuard(path, (6, 10, 2))
    assert guard.begin()
    assert guard.state() == 'trying'
    # The app crashed in the try: the next start finds it unfinished.
    again = CrashGuard(path, (6, 10, 2))
    assert not again.begin()
    assert again.state() == 'crashed'
    assert not CrashGuard(path, (6, 10, 2)).begin()
    # Another Qt version is tried on its own.
    other = CrashGuard(path, (6, 11, 3))
    assert other.begin()
    other.done()
    assert CrashGuard(path, (6, 11, 3)).begin()
    assert CrashGuard(path, (6, 11, 3)).state() == 'ok'


def test_without_a_note_on_disk_the_native_menu_is_not_tried(tmp_path):
    from tvhplayer.window_menu import CrashGuard

    blocked = tmp_path / 'file'
    blocked.write_text('')
    # Its folder is a file: nothing can be written, so a crash would go unnoticed.
    assert not CrashGuard(blocked / 'window-menu.json', (6, 10, 2)).begin()


def test_the_private_call_is_made_only_after_the_note_is_written(tmp_path):
    from tvhplayer.window_menu import CrashGuard, _Wayland

    path = tmp_path / 'window-menu.json'
    calls = []
    backend = object.__new__(_Wayland)
    backend.guard = CrashGuard(path, (6, 10, 2))
    backend.trusted = False
    backend.toplevel = lambda window: calls.append(CrashGuard(path, (6, 10, 2)).state())
    backend._app_interface = lambda: None
    assert backend.show(None, QPoint(1, 1)) is False
    assert calls == ['trying']
    assert backend.trusted and backend.guard.state() == 'ok'
    # Known to work: no more notes.
    backend.show(None, QPoint(1, 1))
    assert calls == ['trying', 'ok']

    crashed = object.__new__(_Wayland)
    crashed.guard = CrashGuard(tmp_path / 'other.json', (6, 10, 2))
    crashed.guard._write('crashed')
    crashed.trusted = False
    crashed.toplevel = lambda window: calls.append('called')
    assert crashed.show(None, QPoint(1, 1)) is False
    assert 'called' not in calls


def test_wayland_menu_needs_a_guard_and_a_checked_qt(monkeypatch, tmp_path):
    from tvhplayer import window_menu

    monkeypatch.setattr(window_menu, '_Wayland', lambda guard: ('backend', guard.version))
    monkeypatch.setattr(window_menu, 'qt_version', lambda: (6, 10, 2))
    window_menu.set_guard_path(None)
    assert window_menu._backend_for('wayland') is None
    window_menu.set_guard_path(tmp_path / 'window-menu.json')
    assert window_menu._backend_for('wayland') == ('backend', '6.10.2')
    monkeypatch.setattr(window_menu, 'qt_version', lambda: (6, 12, 0))
    window_menu.set_guard_path(tmp_path / 'window-menu.json')
    assert window_menu._backend_for('wayland') is None
    window_menu.set_guard_path(None)


def test_fallback_menu_offers_what_the_window_can_do_whatever_buttons_show(qapp, monkeypatch):
    # A desktop layout of only a close button took Minimize and Maximize out of the menu.
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    frame = WindowFrame(window, menubar, button_layout=':close')
    try:
        assert set(frame.title_bar.buttons) == {'close'}
        menu = frame.title_bar.fallback_menu()
        names = [action.text() for action in menu.actions() if not action.isSeparator()]
        assert names == ['Mi&nimize', 'Ma&ximize', '&Close']
        menu.deleteLater()
    finally:
        window.deleteLater()
        qapp.processEvents()


# --- dialogs of every kind ---


def test_dialog_kept_off_screen_is_not_framed(qapp):
    # As a dialog that shows the desktop's own in its place, such as a portal file chooser.
    from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(QLabel('Hello'))
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    try:
        dialog.show()
        qapp.processEvents()
        assert dialog.findChild(TitleBar) is None
    finally:
        framer.deleteLater()
        dialog.deleteLater()
        qapp.processEvents()


def test_qt_file_dialog_fixed_size_and_modal_dialogs_are_framed_and_close(qapp):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QLabel, QVBoxLayout

    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    parent = QWidget()
    seen = {}

    def finish(name, dialog):
        bar = dialog.findChild(TitleBar)
        seen[name] = (
            bar is not None, dialog.windowHandle().format().alphaBufferSize(),
            bar is not None and not bar.buttons['maximize'].isHidden(),
        )
        dialog.reject()

    try:
        files = QFileDialog(parent, 'Recordings folder')
        files.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        files.setFileMode(QFileDialog.FileMode.Directory)
        QTimer.singleShot(50, lambda: finish('file', files))
        assert files.exec() == QDialog.DialogCode.Rejected

        fixed = QDialog(parent)
        QVBoxLayout(fixed).addWidget(QLabel('Fixed'))
        fixed.setFixedSize(300, 120)
        QTimer.singleShot(50, lambda: finish('fixed', fixed))
        fixed.exec()
        # The frame is added around it: its content keeps the fixed size.
        assert fixed.contentsRect().size() == QSize(300, 120)
        assert fixed.minimumSize() == fixed.maximumSize()

        modal = QDialog(parent)
        layout = QVBoxLayout(modal)
        layout.addWidget(QLabel('Modal'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(modal.reject)
        layout.addWidget(buttons)
        modal.setModal(True)
        QTimer.singleShot(50, lambda: finish('modal', modal))
        modal.exec()
        assert seen == {'file': (True, 8, True), 'fixed': (True, 8, False), 'modal': (True, 8, True)}
    finally:
        framer.deleteLater()
        parent.deleteLater()
        qapp.processEvents()


def test_main_window_is_framed_once_while_the_dialog_framer_runs(qapp, monkeypatch):
    # A framer running already prepared the main window as it was given its
    # frame, and framed it a second time as a dialog when shown.
    from tvhplayer.window_frame import TitleBar

    framer = _framer(qapp)
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    frame = WindowFrame(window, QMenuBar(window), button_layout=':close')
    try:
        window.show()
        qapp.processEvents()
        assert window.findChildren(TitleBar) == [frame.title_bar]
    finally:
        framer.deleteLater()
        window.deleteLater()
        qapp.processEvents()


def test_compositor_is_told_where_the_shadow_ends(qapp, monkeypatch):
    # GNOME snapped and tiled the window by its shadow: a gap was left at the
    # screen's edge. It is told the shadow's margins, none while maximized.
    from tvhplayer import window_frame

    told = []
    monkeypatch.setattr(
        window_frame.window_menu, 'set_shadow_margins', lambda window, margins: told.append(QMargins(margins)) or True,
    )
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    menubar = QMenuBar(window)
    frame = WindowFrame(window, menubar, button_layout=':close')
    try:
        assert told == []  # no native window yet
        window.resize(600, 400)
        window.show()
        qapp.processEvents()
        assert told == [SHADOW_MARGINS]
        assert window.size() == QSize(600, 400)
        window.setWindowState(Qt.WindowState.WindowMaximized)
        qapp.processEvents()
        assert told[-1] == QMargins()
        window.setWindowState(Qt.WindowState.WindowNoState)
        qapp.processEvents()
        assert told[-1] == SHADOW_MARGINS
        # Told only when they change.
        count = len(told)
        frame._sync()
        assert len(told) == count
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_shadow_margins_are_only_told_on_wayland(qapp):
    from tvhplayer import window_menu

    assert window_menu.set_shadow_margins(QWidget(), QMargins(1, 1, 1, 1)) is False


def test_frames_of_dialogs_qt_makes_itself_are_kept_alive(qapp):
    # Nothing in Python held the frame of a message box Qt made: its Python
    # half was thrown away while Qt still used it, and its next event failed.
    import gc

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QMessageBox

    framer = _framer(qapp)
    parent = QWidget()
    seen = []

    def check():
        box = qapp.activeModalWidget()
        gc.collect()
        seen.extend(type(child).__name__ for child in box.children())
        box.close()

    try:
        QTimer.singleShot(50, check)
        QMessageBox.warning(parent, 'Oops', 'Something went wrong.')
        assert 'DialogFrame' in seen and 'TitleBar' in seen, seen
    finally:
        framer.deleteLater()
        parent.deleteLater()
        qapp.processEvents()


QUIT_SCRIPT = r'''
import atexit
import sys
calls = []
# Registered before PyQt is imported, so it runs after PyQt's own exit cleanup.
atexit.register(lambda: print('FILTER CALLS AFTER EXIT', len(calls), flush=True))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QMenu, QSplitter, QVBoxLayout, QWidget
from tvhplayer import window_frame

app = QApplication(sys.argv)
filter_events = window_frame.DialogFramer.eventFilter
def counted(self, obj, event):
    calls.append(event.type())
    return filter_events(self, obj, event)
window_frame.DialogFramer.eventFilter = counted
window = QMainWindow()
window._framer = window_frame.DialogFramer(app, 'icon:minimize,maximize,close')
split = QSplitter(window)
for _ in range(5):
    page = QWidget()
    QVBoxLayout(page).addWidget(QLabel('channel'))
    split.addWidget(page)
window.setCentralWidget(split)
menu = window.menuBar().addMenu('File')
for name in ('Open', 'Save', 'Quit'):
    menu.addAction(name)
window.show()
QTimer.singleShot(50, window.close)
code = app.exec()
calls.clear()
# PyQt tears the window down at exit; the framer's Python filter must not run
# then, or new wrappers are made while PyQt walks them (a crash on Wayland).
sys.exit(code)
'''


def test_dialog_framer_stops_watching_once_the_app_quits(tmp_path):
    # Closing TVHplayer crashed on GNOME Wayland: the framer still filtered
    # every event while PyQt deleted the window at exit.
    import os
    import subprocess
    import sys

    script = tmp_path / 'quit.py'
    script.write_text(QUIT_SCRIPT, encoding='utf-8')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert 'FILTER CALLS AFTER EXIT 0' in result.stdout, result.stdout + result.stderr

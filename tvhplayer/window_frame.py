"""TVHplayer's own title bar and window frame, for GNOME and KDE.

GNOME leaves the title bar of a Wayland window to the app, and Qt's stand-in
is pale and has no shadow, so on a white page the window has no edge. There,
and on KDE by choice, the main window drops the system frame and draws its
own: a title bar that holds the menus, the title and the window buttons, a
shadow, and an outline. Moving and resizing are handed to the window manager,
which is the only way a Wayland window can be moved and keeps its snapping.
The shadow needs a compositor, so on X11 the frame is used only while one
runs. Elsewhere the desktop draws the title bar and nothing here is used.
"""

from __future__ import annotations

import ctypes
import os
from configparser import ConfigParser
from pathlib import Path

from PyQt6.QtCore import QEvent, QMargins, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QMenuBar, QWidget

try:
    from . import ui_theme
    from .system_color_scheme import PORTAL_PATH, PORTAL_SERVICE, PORTAL_SETTINGS_INTERFACE, _unwrap
except ImportError:
    import ui_theme
    from system_color_scheme import PORTAL_PATH, PORTAL_SERVICE, PORTAL_SETTINGS_INTERFACE, _unwrap

# Room for the shadow around the window; it falls a little downwards, as GNOME's does.
SHADOW_MARGINS = QMargins(14, 10, 14, 18)
SHADOW_OFFSET = 3
CORNER_RADIUS = 10
# How far from a corner the pointer resizes both edges at once.
CORNER_GRAB = 20
DEFAULT_BUTTON_LAYOUT = ':minimize,maximize,close'
BUTTONS = ('minimize', 'maximize', 'close')
# GNOME's header bars are 46 pixels and a line under them.
TITLE_BAR_HEIGHT = 47


def _desktops(environ):
    return environ.get('XDG_CURRENT_DESKTOP', '').lower().split(':')


def wants_own_title_bar(platform_name, environ=None, compositing=None) -> bool:
    """True where the app can draw its window's title bar: GNOME and KDE on
    Wayland, and KDE on X11 while a compositor shows the shadow."""
    environ = os.environ if environ is None else environ
    desktops = _desktops(environ)
    if platform_name.startswith('wayland'):
        return 'gnome' in desktops or 'kde' in desktops
    if platform_name == 'xcb' and 'kde' in desktops:
        # Under XWayland the Wayland compositor shows every window.
        if environ.get('WAYLAND_DISPLAY'):
            return True
        return x11_compositing() if compositing is None else compositing
    return False


def x11_compositing() -> bool:
    """True while an X11 compositor runs: it owns the _NET_WM_CM_S<screen> selection."""
    try:
        xlib = ctypes.CDLL('libX11.so.6')
    except OSError:
        return False
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    xlib.XGetSelectionOwner.restype = ctypes.c_ulong
    xlib.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = xlib.XOpenDisplay(None)
    if not display:
        return False
    try:
        atom = xlib.XInternAtom(display, f'_NET_WM_CM_S{xlib.XDefaultScreen(display)}'.encode(), 0)
        return bool(xlib.XGetSelectionOwner(display, atom))
    finally:
        xlib.XCloseDisplay(display)


def parse_button_layout(layout):
    """GNOME's ``button-layout``, e.g. "icon:minimize,maximize,close", as the
    window buttons (left, right). Names other than the three buttons are left out."""
    left, _, right = (layout or '').partition(':')

    def buttons(side):
        names = [name.strip() for name in side.split(',')]
        return [name for name in names if name in BUTTONS]

    return buttons(left), buttons(right)


# KWin's button letters: I minimize, A maximize, X close. The others are left out.
KWIN_BUTTONS = {'I': 'minimize', 'A': 'maximize', 'X': 'close'}


def kwin_button_layout(left='MS', right='HIAX'):
    """KWin's ButtonsOnLeft and ButtonsOnRight, given in its letters, as a GNOME-style layout."""

    def names(letters):
        return ','.join(KWIN_BUTTONS[letter] for letter in letters if letter in KWIN_BUTTONS)

    return f'{names(left)}:{names(right)}'


def kde_button_layout(environ=None):
    """The window buttons as KWin places them, from kwinrc, or KWin's default.

    Flatpak points XDG_CONFIG_HOME into the sandbox; the manifest shares the
    host's kwinrc read-only, where it is on the host: ~/.config."""
    environ = os.environ if environ is None else environ
    folders = [environ.get('XDG_CONFIG_HOME'), str(Path.home() / '.config')]
    paths = [Path(folder) / 'kwinrc' for folder in folders if folder]
    path = next((path for path in paths if path.is_file()), None)
    parser = ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        if path is not None:
            parser.read(path, encoding='utf-8')
    except Exception:
        return kwin_button_layout()
    section = parser['org.kde.kdecoration2'] if parser.has_section('org.kde.kdecoration2') else {}
    return kwin_button_layout(section.get('ButtonsOnLeft', 'MS'), section.get('ButtonsOnRight', 'HIAX'))


def desktop_button_layout(environ=None):
    environ = os.environ if environ is None else environ
    if 'kde' in _desktops(environ):
        return kde_button_layout(environ)
    return portal_button_layout()


def portal_button_layout():
    """The desktop's title bar button layout from the portal, or GNOME's default."""
    try:
        from PyQt6.QtDBus import QDBusConnection, QDBusInterface
    except ImportError:
        return DEFAULT_BUTTON_LAYOUT
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return DEFAULT_BUTTON_LAYOUT
    interface = QDBusInterface(PORTAL_SERVICE, PORTAL_PATH, PORTAL_SETTINGS_INTERFACE, bus)
    if not interface.isValid():
        return DEFAULT_BUTTON_LAYOUT
    for method in ('ReadOne', 'Read'):
        reply = interface.call(method, 'org.gnome.desktop.wm.preferences', 'button-layout')
        arguments = reply.arguments() if reply is not None else []
        if arguments:
            value = _unwrap(arguments[0])
            if isinstance(value, str) and ':' in value:
                return value
    return DEFAULT_BUTTON_LAYOUT


def edges_at(pos, size, margins, grab=CORNER_GRAB):
    """The window edges a press at ``pos`` resizes: one edge, or two near a corner."""
    x, y, width, height = pos.x(), pos.y(), size.width(), size.height()
    edges = Qt.Edge(0)
    if x < margins.left() + grab and (y < margins.top() or y >= height - margins.bottom() or x < margins.left()):
        edges |= Qt.Edge.LeftEdge
    if x >= width - margins.right() - grab and (
        y < margins.top() or y >= height - margins.bottom() or x >= width - margins.right()
    ):
        edges |= Qt.Edge.RightEdge
    if y < margins.top() + grab and (x < margins.left() or x >= width - margins.right() or y < margins.top()):
        edges |= Qt.Edge.TopEdge
    if y >= height - margins.bottom() - grab and (
        x < margins.left() or x >= width - margins.right() or y >= height - margins.bottom()
    ):
        edges |= Qt.Edge.BottomEdge
    return edges


def cursor_for(edges):
    if edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
        return Qt.CursorShape.SizeFDiagCursor
    if edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
        return Qt.CursorShape.SizeBDiagCursor
    if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
        return Qt.CursorShape.SizeHorCursor
    if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


def _is_dark(palette):
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


class WindowButton(QAbstractButton):
    """A round minimize, maximize or close button, as on GNOME's title bars."""

    NAMES = {'minimize': 'Minimize', 'maximize': 'Maximize', 'close': 'Close'}

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.restore = False
        self.setFixedSize(30, 30)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAccessibleName(self.NAMES[kind])
        self.setToolTip(self.NAMES[kind])

    def set_restore(self, restore):
        if self.kind == 'maximize' and restore != self.restore:
            self.restore = restore
            name = 'Restore' if restore else 'Maximize'
            self.setAccessibleName(name)
            self.setToolTip(name)
            self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        circle = QColor(ink)
        circle.setAlphaF(0.22 if self.isDown() else 0.15 if self.underMouse() else 0.08)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(circle)
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.drawEllipse(center, 12, 12)
        glyph = QColor(ink)
        if not self.window().isActiveWindow():
            glyph.setAlphaF(0.55)
        pen = QPen(glyph, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = center.x(), center.y()
        if self.kind == 'minimize':
            painter.drawLine(QPointF(cx - 4, cy + 3.5), QPointF(cx + 4, cy + 3.5))
        elif self.kind == 'maximize' and self.restore:
            painter.drawRoundedRect(QRectF(cx - 4.5, cy - 2.5, 7, 7), 1, 1)
            painter.drawPolyline([QPointF(cx - 2.5, cy - 4.5), QPointF(cx + 4.5, cy - 4.5), QPointF(cx + 4.5, cy + 2.5)])
        elif self.kind == 'maximize':
            painter.drawRoundedRect(QRectF(cx - 4, cy - 4, 8, 8), 1, 1)
        else:
            painter.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
            painter.drawLine(QPointF(cx + 4, cy - 4), QPointF(cx - 4, cy + 4))


class TitleBar(QMenuBar):
    """The menus, the window title in the middle, and the window buttons.

    A drag on any empty part moves the window; a double click maximizes it.

    It is a menu bar without menus of its own: some styles, such as Breeze, ask
    the window for its menu bar, and a window whose menu widget is no menu bar
    then gets a new empty one in place of this title bar."""

    def __init__(self, window, menubar, button_layout=DEFAULT_BUTTON_LAYOUT):
        super().__init__(window)
        self._window = window
        self.menubar = menubar
        # Never handed to a global menu, which would hide the title bar.
        self.setNativeMenuBar(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setProperty('titlebar', True)
        self.setAccessibleName('Title bar')
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        # The theme leaves the line under this menu bar to the title bar.
        menubar.setProperty('titlebar', True)
        menubar.style().unpolish(menubar)
        menubar.style().polish(menubar)
        left, right = parse_button_layout(button_layout)
        self.buttons = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 1)
        layout.setSpacing(2)
        for kind in left:
            layout.addWidget(self._button(kind), 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(menubar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        for kind in right:
            layout.addWidget(self._button(kind), 0, Qt.AlignmentFlag.AlignVCenter)
        self.title = QLabel(self)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setAccessibleName('Window title')
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        menubar.installEventFilter(self)
        window.windowTitleChanged.connect(self._place_title)
        self.sync_state()

    def _button(self, kind):
        button = WindowButton(kind, self)
        actions = {
            'minimize': self._window.showMinimized,
            'maximize': self.toggle_maximized,
            'close': self._window.close,
        }
        button.clicked.connect(actions[kind])
        self.buttons[kind] = button
        return button

    def toggle_maximized(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def sync_state(self):
        """Follow the window: maximized or not, active or not."""
        button = self.buttons.get('maximize')
        if button is not None:
            button.set_restore(self._window.isMaximized())
        for button in self.buttons.values():
            button.update()
        self._place_title()

    def _place_title(self, *_args):
        """Center the title on the window, moved aside or shortened where the menus or buttons are."""
        text = self._window.windowTitle()
        lefts = [self.menubar.geometry().right()] + [
            button.geometry().right() for button in self.buttons.values() if button.x() < self.menubar.x()
        ]
        rights = [button.x() for button in self.buttons.values() if button.x() > self.menubar.x()]
        start = max(lefts) + 12
        end = (min(rights) if rights else self.width() - 8) - 12
        if end <= start:
            self.title.hide()
            return
        metrics = self.title.fontMetrics()
        width = min(metrics.horizontalAdvance(text) + 4, end - start)
        x = round(self.width() / 2 - width / 2)
        x = min(max(x, start), end - width)
        self.title.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))
        self.title.setGeometry(x, 0, width, self.height())
        color = self.palette().color(QPalette.ColorRole.WindowText)
        if not self._window.isActiveWindow():
            color.setAlphaF(0.55)
        self.title.setStyleSheet(f'color: {color.name(QColor.NameFormat.HexArgb)};')
        self.title.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_title()

    def _start_move(self):
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def _empty_menubar_spot(self, event):
        return self.menubar.actionAt(event.position().toPoint()) is None

    def sizeHint(self):
        return QSize(super().sizeHint().width(), TITLE_BAR_HEIGHT)

    def minimumSizeHint(self):
        return QSize(0, TITLE_BAR_HEIGHT)

    def heightForWidth(self, _width):
        return TITLE_BAR_HEIGHT

    def eventFilter(self, obj, event):
        # Not passed on to QMenuBar, which watches the window for the Alt key:
        # the menus inside answer it.
        if obj is self.menubar and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if event.button() == Qt.MouseButton.LeftButton and self._empty_menubar_spot(event):
                if event.type() == QEvent.Type.MouseButtonDblClick:
                    self.toggle_maximized()
                else:
                    self._start_move()
                return True
        elif obj is self.menubar and event.type() == QEvent.Type.Resize:
            self._place_title()
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_move()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event):
        # The TVHplayer theme draws a line under its menu bar; carry it across the title bar.
        if ui_theme.is_active():
            painter = QPainter(self)
            painter.fillRect(QRect(0, self.height() - 1, self.width(), 1), ui_theme.color('rule'))


class _ResizeGrip(QWidget):
    """An invisible strip over one side of the shadow that resizes the window."""

    def __init__(self, frame):
        super().__init__(frame.window)
        self._frame = frame
        self.setMouseTracking(True)

    def _edges(self, event):
        window = self._frame.window
        return edges_at(self.mapTo(window, event.position().toPoint()), window.size(), self._frame.margins)

    def mouseMoveEvent(self, event):
        self.setCursor(cursor_for(self._edges(event)))

    def mousePressEvent(self, event):
        edges = self._edges(event)
        handle = self._frame.window.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and edges and handle is not None:
            handle.startSystemResize(edges)
            event.accept()


class WindowFrame(QObject):
    """Turns a main window into one that draws its own frame and title bar.

    Call before the window is first shown: the window drops the system frame
    and becomes see-through outside its content, where the shadow is drawn."""

    def __init__(self, window, menubar, button_layout=None):
        super().__init__(window)
        self.window = window
        self.margins = QMargins(SHADOW_MARGINS)
        self._shadow = None
        self._shadow_key = None
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.title_bar = TitleBar(
            window, menubar, desktop_button_layout() if button_layout is None else button_layout
        )
        window.setMenuWidget(self.title_bar)
        self.grips = [_ResizeGrip(self) for _ in range(4)]
        window.installEventFilter(self)
        self._sync()

    def _bare(self):
        """Maximized and fullscreen windows have no shadow, outline or rounded corners."""
        state = self.window.windowState()
        return bool(state & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen))

    def _sync(self):
        self.margins = QMargins() if self._bare() else QMargins(SHADOW_MARGINS)
        # The fullscreen view sets its own margins and puts them back after.
        if not self.window.isFullScreen():
            self.window.setContentsMargins(self.margins)
        self._place_grips()
        self.title_bar.sync_state()
        self.window.update()

    def _place_grips(self):
        m, w, h = self.margins, self.window.width(), self.window.height()
        rects = (
            QRect(0, 0, w, m.top()),
            QRect(0, h - m.bottom(), w, m.bottom()),
            QRect(0, m.top(), m.left(), h - m.top() - m.bottom()),
            QRect(w - m.right(), m.top(), m.right(), h - m.top() - m.bottom()),
        )
        for grip, rect in zip(self.grips, rects):
            grip.setGeometry(rect)
            grip.setVisible(not self._bare() and not rect.isEmpty())
            grip.raise_()

    def eventFilter(self, obj, event):
        if obj is self.window:
            kind = event.type()
            if kind == QEvent.Type.Paint:
                self._paint()
            elif kind == QEvent.Type.WindowStateChange:
                self._sync()
            elif kind == QEvent.Type.Resize:
                self._place_grips()
            elif kind in (QEvent.Type.ActivationChange, QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
                self.title_bar.sync_state()
                self.window.update()
        return False

    def _paint(self):
        painter = QPainter(self.window)
        palette = self.window.palette()
        if self._bare():
            painter.fillRect(self.window.rect(), palette.color(QPalette.ColorRole.Window))
            return
        dark = _is_dark(palette)
        active = self.window.isActiveWindow()
        key = (self.window.size(), dark, active, palette.color(QPalette.ColorRole.Window).rgba())
        if key != self._shadow_key:
            self._shadow = self._render(self.window.size(), dark, active, palette.color(QPalette.ColorRole.Window))
            self._shadow_key = key
        painter.drawPixmap(0, 0, self._shadow)

    def _render(self, size, dark, active, background):
        """The shadow, outline and background of the window at ``size``, drawn once per size."""
        ratio = self.window.devicePixelRatioF()
        pixmap = QPixmap(QSize(round(size.width() * ratio), round(size.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        content = QRectF(QRect(QPoint(0, 0), size).marginsRemoved(self.margins))
        # Layers grow fainter outwards; drawn over each other they make a soft shadow.
        spread = min(self.margins.left(), self.margins.right(), self.margins.top() + SHADOW_OFFSET)
        strength = (0.5 if dark else 0.32) if active else (0.32 if dark else 0.16)
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(spread, 0, -1):
            fade = 1 - step / (spread + 1)
            shade = QColor(0, 0, 0)
            shade.setAlphaF(strength * fade * fade * 3 / spread)
            painter.setBrush(shade)
            layer = content.translated(0, SHADOW_OFFSET).adjusted(-step, -step, step, step)
            painter.drawRoundedRect(layer, CORNER_RADIUS + step, CORNER_RADIUS + step)
        shape = self._shape(content)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillPath(shape, background)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        outline = QColor(0, 0, 0)
        outline.setAlphaF(0.7 if dark else 0.23)
        painter.setPen(QPen(outline, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._shape(content.adjusted(-0.5, -0.5, 0.5, 0.5)))
        painter.end()
        return pixmap

    @staticmethod
    def _shape(rect):
        """Rounded at the top, square at the bottom, where the status bar is."""
        path = QPainterPath()
        radius = CORNER_RADIUS
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + radius)
        path.arcTo(QRectF(rect.left(), rect.top(), 2 * radius, 2 * radius), 180, -90)
        path.lineTo(rect.right() - radius, rect.top())
        path.arcTo(QRectF(rect.right() - 2 * radius, rect.top(), 2 * radius, 2 * radius), 90, -90)
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        return path


def install(window, menubar, wanted):
    """Give ``window`` its own frame and title bar if ``wanted`` and the desktop leaves them to the app.

    Returns the frame, or None after ``menubar`` was made the window's menu bar as usual."""
    if wanted and wants_own_title_bar(QGuiApplication.platformName()):
        return WindowFrame(window, menubar)
    window.setMenuBar(menubar)
    return None

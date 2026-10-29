"""OpenGL video widget for the libmpv engine.

Qt owns the OpenGL context and keeps painting the widget; each paint asks mpv
to draw the current frame into the widget's framebuffer. Nothing is a native
window, so the splash, spinner and fullscreen bar can sit on top as plain widgets.
"""

from __future__ import annotations

import ctypes

from PyQt6.QtCore import QT_VERSION_STR, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QOpenGLContext
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

GL_COLOR_BUFFER_BIT = 0x4000
# Opaque splitter resize of this widget stays with the pointer from Qt 6.11
# (AppImage, Flatpak, PyPI wheels). Qt 6.10 on the host falls behind while mpv paints.
_LIVE_SPLITTER_QT = (6, 11, 0)


def live_splitter_keeps_up(qt_version=None):
    """True when live (opaque) splitter resize of the video widget stays responsive."""
    text = QT_VERSION_STR if qt_version is None else qt_version
    parts = []
    for piece in str(text).split('.'):
        digits = []
        for char in piece:
            if char.isdigit():
                digits.append(char)
            else:
                break
        if not digits:
            break
        parts.append(int(''.join(digits)))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3]) >= _LIVE_SPLITTER_QT


def resize_on_release(choice, qt_version=None):
    """Whether pane drags resize only on mouse release.

    ``choice`` is the saved setting. None follows the Qt version: on before
    6.11, where live resize falls behind the pointer, and off from 6.11.
    """
    if choice is None:
        return not live_splitter_keeps_up(qt_version)
    return bool(choice)


class MpvVideoWidget(QOpenGLWidget):
    """The picture surface. ``MpvPlayer.attach()`` binds the engine to it."""

    # mpv reports a new frame from its own thread; the signal repaints on this one.
    _frame_ready = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = None
        self._render_context = None
        self._wayland = None
        self._frame_ready.connect(self.update, Qt.ConnectionType.QueuedConnection)

    def bind(self, engine):
        self._engine = engine
        if self.isValid():
            self.makeCurrent()
            self._create_render_context()
            self.doneCurrent()

    def platform_name(self):
        """Qt's windowing platform, e.g. "wayland" or "xcb" (X11 or XWayland)."""
        return QGuiApplication.platformName()

    def initializeGL(self):
        self.context().aboutToBeDestroyed.connect(self.release)
        self._create_render_context()

    def _create_render_context(self):
        if self._engine is None or self._render_context is not None:
            return
        if self._wayland is None and QGuiApplication.platformName() == 'wayland':
            self._wayland = _WaylandConnection()
        wl_display = self._wayland.display if self._wayland is not None else None
        context = self._engine.create_render_context(_proc_address, wl_display)
        context.update_cb = self._frame_ready.emit
        self._render_context = context

    def paintGL(self):
        if self._render_context is None:
            self._create_render_context()
        if self._render_context is None:
            gl = self.context().functions()
            gl.glClearColor(0.0, 0.0, 0.0, 1.0)
            gl.glClear(GL_COLOR_BUFFER_BIT)
            return
        ratio = self.devicePixelRatioF()
        self._render_context.render(
            flip_y=True,
            opengl_fbo={
                'w': round(self.width() * ratio),
                'h': round(self.height() * ratio),
                'fbo': self.defaultFramebufferObject(),
            },
        )

    def release(self):
        """Free the renderer without replacing a live native callback.

        Assigning update_cb = None in python-mpv replaces a ctypes closure.
        libmpv can still be executing that closure on its VO thread, so
        replacing it during shutdown can leave a dangling C callback.
        mpv_render_context_free() synchronizes with that thread: keep the
        existing callback alive on the context until free() returns.
        """
        context, self._render_context = self._render_context, None
        if context is not None:
            self.makeCurrent()
            try:
                context.free()
            finally:
                self.doneCurrent()
        wayland, self._wayland = self._wayland, None
        if wayland is not None:
            wayland.close()


def _proc_address(name):
    context = QOpenGLContext.currentContext()
    if context is None:
        return 0
    address = context.getProcAddress(name)
    return int(address) if address else 0


class _WaylandConnection:
    """A connection to the compositor of our own, for mpv's VA-API.

    PyQt6 does not expose Qt's ``wl_display``. mpv uses the display only to
    open VA-API; frames still reach Qt's OpenGL context as dma-bufs.
    """

    def __init__(self):
        self.display = None
        try:
            self._lib = ctypes.CDLL('libwayland-client.so.0')
        except OSError as exc:
            print(f'Debug: No Wayland client library for mpv: {exc}')
            return
        self._lib.wl_display_connect.restype = ctypes.c_void_p
        self._lib.wl_display_connect.argtypes = [ctypes.c_char_p]
        self._lib.wl_display_disconnect.argtypes = [ctypes.c_void_p]
        self.display = self._lib.wl_display_connect(None)
        if not self.display:
            print('Debug: Could not connect to the Wayland display for mpv')

    def close(self):
        display, self.display = self.display, None
        if display:
            self._lib.wl_display_disconnect(display)

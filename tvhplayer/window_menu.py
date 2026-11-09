"""The desktop's own window menu, for windows that draw their own title bar.

A right click on a title bar opens the window manager's menu: on GNOME it
moves the window to another workspace, keeps it on top and so on. A window
that draws its own title bar must ask for that menu itself. Wayland has a
request for it, xdg_toplevel.show_window_menu, and X11 window managers answer
_GTK_SHOW_WINDOW_MENU, but Qt offers neither to Python. Here they are reached
through Qt's native interfaces and the Wayland and X11 client libraries.

Every step checks what it gets, and :func:`show` returns False when the menu
could not be asked for, so the caller can show a menu of its own instead.

On Wayland the window's xdg_toplevel comes from one of Qt's private functions.
A mistake there would not raise an exception but crash the app, so it is only
called on the Qt versions whose source was checked for it (VERIFIED_QT), and
:class:`CrashGuard` notes each first try: a try that never finished, because
the app crashed in it, turns the native menu off for that Qt version for good.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import platform
from pathlib import Path

from PyQt6.QtCore import QLibraryInfo
from PyQt6.QtGui import QGuiApplication

try:
    from PyQt6 import sip
except ImportError:  # pragma: no cover - older PyQt6 installs sip on its own
    import sip

# xdg_toplevel's requests: destroy, set_parent, set_title, set_app_id, show_window_menu, ...
XDG_TOPLEVEL_SHOW_WINDOW_MENU = 4
# QNativeInterface::QWaylandApplication: two destructor slots, then display,
# compositor, seat, keyboard, pointer, touch, lastInputSerial, lastInputSeat.
# Qt only adds to the end of it.
SLOT_SEAT = 4
SLOT_LAST_INPUT_SERIAL = 8
SLOT_LAST_INPUT_SEAT = 9
# QtWaylandClient::QWaylandWindow::_surfaceRole() const, which returns an std::any
# holding the window's xdg_toplevel. Called by name: its place in the vtable
# moved in Qt 6.11.
SURFACE_ROLE_SYMBOL = b'_ZNK15QtWaylandClient14QWaylandWindow12_surfaceRoleEv'
RESOLVE_APP_SYMBOL = b'_ZNK15QGuiApplication16resolveInterfaceEPKci'
RESOLVE_WINDOW_SYMBOL = b'_ZNK7QWindow16resolveInterfaceEPKci'
# Qt versions (major, minor) whose QtWaylandClient::QWaylandWindow was checked:
# the private native interface is its first base, _surfaceRole() returns an
# std::any, and an xdg-shell window's holds its xdg_toplevel. The same in 6.5
# to 6.11. A newer Qt gets the app's own menu until it is checked too.
VERIFIED_QT = ((6, 5), (6, 11))
# QNativeInterface::QX11Application: two destructor slots, then display, connection.
SLOT_X11_CONNECTION = 3
XA_ATOM = 4


def qt_version():
    version = QLibraryInfo.version()
    return version.majorVersion(), version.minorVersion(), version.microVersion()


def verified_qt(version=None):
    major, minor = (version or qt_version())[:2]
    return VERIFIED_QT[0] <= (major, minor) <= VERIFIED_QT[1]


class CrashGuard:
    """Remembers, per Qt version, whether the native window menu worked.

    Written to disk before the first try, so it outlives a crash in it."""

    def __init__(self, path, version):
        self.path = Path(path)
        self.version = '.'.join(str(part) for part in version)

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, state):
        data = self._read()
        data[self.version] = state
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except OSError:
            return False

    def state(self):
        return self._read().get(self.version)

    def begin(self):
        """True if the native menu may be tried. A try left unfinished was a crash."""
        state = self.state()
        if state == 'ok':
            return True
        if state in ('trying', 'crashed'):
            if state == 'trying':
                self._write('crashed')
            return False
        # Not tried without a note on disk: a crash would go unnoticed.
        return self._write('trying')

    def done(self):
        if self.state() != 'ok':
            self._write('ok')


_guard_path = None


def set_guard_path(path):
    """Where :class:`CrashGuard` keeps its notes; without one the native Wayland menu is not tried."""
    global _guard_path, _backend_platform
    _guard_path = path
    _backend_platform = None


def _library(*names):
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


class _StdAny(ctypes.Structure):
    """libstdc++'s std::any: its manager, then a pointer kept in place."""

    _fields_ = [('manager', ctypes.c_void_p), ('value', ctypes.c_void_p)]


class _Wayland:
    """The Qt and libwayland-client calls that ask a Wayland compositor for the window menu."""

    def __init__(self, guard):
        # The std::any comes back through a hidden pointer, passed first only
        # on x86-64; elsewhere it travels in a register ctypes cannot set.
        if platform.machine() not in ('x86_64', 'AMD64'):
            raise OSError('unsupported architecture')
        self.guard = guard
        self.trusted = guard.state() == 'ok'
        gui = _library('libQt6Gui.so.6')
        client = _library('libQt6WaylandClient.so.6')
        wayland = _library(ctypes.util.find_library('wayland-client') or 'libwayland-client.so.0', 'libwayland-client.so.0')
        if gui is None or client is None or wayland is None:
            raise OSError('libraries missing')
        resolve = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int)
        self.resolve_app = resolve(ctypes.cast(getattr(gui, RESOLVE_APP_SYMBOL.decode()), ctypes.c_void_p).value)
        self.resolve_window = resolve(ctypes.cast(getattr(gui, RESOLVE_WINDOW_SYMBOL.decode()), ctypes.c_void_p).value)
        self.surface_role = ctypes.CFUNCTYPE(None, ctypes.POINTER(_StdAny), ctypes.c_void_p)(
            ctypes.cast(getattr(client, SURFACE_ROLE_SYMBOL.decode()), ctypes.c_void_p).value
        )
        self.get_class = wayland.wl_proxy_get_class
        self.get_class.restype = ctypes.c_char_p
        self.get_class.argtypes = [ctypes.c_void_p]
        self.get_version = wayland.wl_proxy_get_version
        self.get_version.restype = ctypes.c_uint32
        self.get_version.argtypes = [ctypes.c_void_p]
        self.marshal_flags = getattr(wayland, 'wl_proxy_marshal_flags', None)
        self.marshal = wayland.wl_proxy_marshal
        self.flush = wayland.wl_display_flush
        self.flush.argtypes = [ctypes.c_void_p]

    def _app_interface(self):
        app = QGuiApplication.instance()
        if app is None:
            return None
        return self.resolve_app(sip.unwrapinstance(app), b'QWaylandApplication', 1)

    @staticmethod
    def _virtual(interface, slot, restype):
        vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.CFUNCTYPE(restype, ctypes.c_void_p)(vtable[slot])(interface)

    def toplevel(self, window):
        """The window's xdg_toplevel, or None."""
        handle = window.windowHandle()
        if handle is None:
            return None
        interface = self.resolve_window(sip.unwrapinstance(handle), b'QWaylandWindow', 1)
        if not interface:
            return None
        role = _StdAny()
        self.surface_role(ctypes.byref(role), interface)
        # An empty std::any has no manager; a pointer is kept in place, so it needs no freeing.
        if not role.manager or not role.value:
            return None
        if self.get_class(role.value) != b'xdg_toplevel':
            return None
        return role.value

    def show(self, window, pos):
        if not self.trusted:
            if not self.guard.begin():
                return False
            toplevel = self.toplevel(window)
            # Still here: the private call works on this Qt.
            self.guard.done()
            self.trusted = True
        else:
            toplevel = self.toplevel(window)
        app = self._app_interface()
        if toplevel is None or not app:
            return False
        serial = self._virtual(app, SLOT_LAST_INPUT_SERIAL, ctypes.c_uint)
        seat = self._virtual(app, SLOT_LAST_INPUT_SEAT, ctypes.c_void_p) or self._virtual(app, SLOT_SEAT, ctypes.c_void_p)
        if not seat or self.get_class(seat) != b'wl_seat':
            return False
        display = self._virtual(app, 2, ctypes.c_void_p)
        args = (ctypes.c_void_p(seat), ctypes.c_uint32(serial), ctypes.c_int32(pos.x()), ctypes.c_int32(pos.y()))
        if self.marshal_flags is not None:
            self.marshal_flags(
                ctypes.c_void_p(toplevel), ctypes.c_uint32(XDG_TOPLEVEL_SHOW_WINDOW_MENU), ctypes.c_void_p(None),
                ctypes.c_uint32(self.get_version(toplevel)), ctypes.c_uint32(0), *args,
            )
        else:
            self.marshal(ctypes.c_void_p(toplevel), ctypes.c_uint32(XDG_TOPLEVEL_SHOW_WINDOW_MENU), *args)
        if display:
            self.flush(display)
        return True


class _X11:
    """Asks an X11 window manager for the window menu with _GTK_SHOW_WINDOW_MENU, as GTK does.

    Only a window manager that lists the request in _NET_SUPPORTED is asked:
    XSendEvent() says the message went out, not that anyone acted on it."""

    def __init__(self):
        self.xlib = xlib = _library('libX11.so.6')
        self.xcb = xcb = _library('libxcb.so.1')
        gui = _library('libQt6Gui.so.6')
        if xlib is None or xcb is None or gui is None:
            raise OSError('libraries missing')
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XInternAtom.restype = ctypes.c_ulong
        xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        xlib.XDefaultRootWindow.restype = ctypes.c_ulong
        xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        xlib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
        xlib.XFlush.argtypes = [ctypes.c_void_p]
        xlib.XFree.argtypes = [ctypes.c_void_p]
        xlib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
            ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
        ]
        xcb.xcb_ungrab_pointer.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        xcb.xcb_flush.argtypes = [ctypes.c_void_p]
        resolve = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int)
        self.resolve_app = resolve(ctypes.cast(getattr(gui, RESOLVE_APP_SYMBOL.decode()), ctypes.c_void_p).value)
        self.display = xlib.XOpenDisplay(None)
        if not self.display:
            raise OSError('no X display')
        self.atom = xlib.XInternAtom(self.display, b'_GTK_SHOW_WINDOW_MENU', 0)
        self.supported_atom = xlib.XInternAtom(self.display, b'_NET_SUPPORTED', 0)

    def supported(self):
        """True if the window manager lists _GTK_SHOW_WINDOW_MENU among the requests it handles."""
        root = self.xlib.XDefaultRootWindow(self.display)
        kind, fmt = ctypes.c_ulong(), ctypes.c_int()
        count, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        status = self.xlib.XGetWindowProperty(
            self.display, root, self.supported_atom, 0, 4096, 0, XA_ATOM,
            ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count), ctypes.byref(after), ctypes.byref(data),
        )
        if status != 0 or not data.value:
            return False
        try:
            if fmt.value != 32:
                return False
            atoms = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
            return any(atoms[index] == self.atom for index in range(count.value))
        finally:
            self.xlib.XFree(data)

    def _ungrab_qt(self):
        """Let go of the pointer Qt holds while the button is down, so the window manager can take it."""
        app = QGuiApplication.instance()
        interface = self.resolve_app(sip.unwrapinstance(app), b'QX11Application', 1) if app else None
        if not interface:
            return
        vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        connection = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vtable[SLOT_X11_CONNECTION])(interface)
        if connection:
            self.xcb.xcb_ungrab_pointer(connection, 0)
            self.xcb.xcb_flush(connection)

    def show(self, window, global_pos):
        class ClientMessage(ctypes.Structure):
            _fields_ = [
                ('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', ctypes.c_long * 5),
            ]

        handle = window.windowHandle()
        if handle is None or not self.supported():
            return False
        ratio = handle.devicePixelRatio()
        event = ClientMessage()
        event.type = 33  # ClientMessage
        event.send_event = 1
        event.display = self.display
        event.window = int(handle.winId())
        event.message_type = self.atom
        event.format = 32
        # Device 2 is the core pointer; then where, in the root window's pixels.
        event.data[0] = 2
        event.data[1] = round(global_pos.x() * ratio)
        event.data[2] = round(global_pos.y() * ratio)
        self._ungrab_qt()
        root = self.xlib.XDefaultRootWindow(self.display)
        # SubstructureRedirectMask | SubstructureNotifyMask
        mask = (1 << 20) | (1 << 19)
        sent = self.xlib.XSendEvent(self.display, root, 0, mask, ctypes.byref(event))
        self.xlib.XFlush(self.display)
        return bool(sent)


_backend = None
_backend_platform = None


def _backend_for(platform_name):
    global _backend, _backend_platform
    if _backend_platform != platform_name:
        _backend_platform = platform_name
        try:
            if platform_name.startswith('wayland'):
                version = qt_version()
                if _guard_path is None or not verified_qt(version):
                    _backend = None
                else:
                    _backend = _Wayland(CrashGuard(_guard_path, version))
            elif platform_name == 'xcb':
                _backend = _X11()
            else:
                _backend = None
        except (OSError, AttributeError):
            _backend = None
    return _backend


def show(window, pos, global_pos) -> bool:
    """Ask the window manager to open its window menu for ``window`` at ``pos``
    (in the window) / ``global_pos`` (on the screen). False if it could not be asked."""
    backend = _backend_for(QGuiApplication.platformName())
    if backend is None:
        return False
    try:
        if isinstance(backend, _Wayland):
            return backend.show(window, pos)
        return backend.show(window, global_pos)
    except (OSError, ValueError, TypeError, AttributeError):
        return False

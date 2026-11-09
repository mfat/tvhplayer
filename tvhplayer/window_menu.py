"""The desktop's own window menu, for windows that draw their own title bar.

A right click on a title bar opens the window manager's menu: on GNOME it
moves the window to another workspace, keeps it on top and so on. A window
that draws its own title bar must ask for that menu itself. Wayland has a
request for it, xdg_toplevel.show_window_menu, and X11 window managers answer
_GTK_SHOW_WINDOW_MENU, but Qt offers neither to Python. Here they are reached
through Qt's native interfaces and the Wayland and X11 client libraries.

Every step checks what it gets, and :func:`show` returns False when the menu
could not be asked for, so the caller can show a menu of its own instead.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform

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

    def __init__(self):
        # The std::any comes back through a hidden pointer, passed first only
        # on x86-64; elsewhere it travels in a register ctypes cannot set.
        if platform.machine() not in ('x86_64', 'AMD64'):
            raise OSError('unsupported architecture')
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
    """Asks an X11 window manager for the window menu with _GTK_SHOW_WINDOW_MENU, as GTK does."""

    def __init__(self):
        self.xlib = xlib = _library('libX11.so.6')
        if xlib is None:
            raise OSError('libX11 missing')
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XInternAtom.restype = ctypes.c_ulong
        xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        xlib.XDefaultRootWindow.restype = ctypes.c_ulong
        xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        xlib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
        xlib.XUngrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xlib.XFlush.argtypes = [ctypes.c_void_p]
        xlib.XGetSelectionOwner.restype = ctypes.c_ulong
        xlib.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.display = xlib.XOpenDisplay(None)
        if not self.display:
            raise OSError('no X display')
        self.atom = xlib.XInternAtom(self.display, b'_GTK_SHOW_WINDOW_MENU', 0)
        self.supported = xlib.XInternAtom(self.display, b'_NET_SUPPORTED', 0)

    def show(self, window, global_pos):
        class ClientMessage(ctypes.Structure):
            _fields_ = [
                ('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', ctypes.c_long * 5),
            ]

        handle = window.windowHandle()
        if handle is None:
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
        # The window manager can only take the pointer once Qt has let it go.
        self.xlib.XUngrabPointer(self.display, 0)
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
                _backend = _Wayland()
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

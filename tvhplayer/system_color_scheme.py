"""The desktop's light or dark preference, sandboxes included (from Jottr).

``QStyleHints.colorScheme()`` is often wrong: native Qt on GNOME Wayland can
report Light while the session is dark, since it follows GTK's settings.ini,
which GNOME no longer keeps in sync, and the Flatpak KDE runtime looks for
``kdeglobals`` inside the sandbox. The desktop portal is the source of truth:
``color-scheme`` in the ``org.freedesktop.appearance`` namespace, which the
GNOME, Plasma and wlroots portals provide without extra Flatpak permissions.
Without a portal, host GTK settings files are read, then Qt is asked.
"""

from __future__ import annotations

import enum
import os
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSlot


class _FallbackColorScheme(enum.Enum):
    """Stand-in for Qt.ColorScheme (Qt 6.5), with the same names and values."""

    Unknown = 0
    Light = 1
    Dark = 2


# Qt 6.4 (Ubuntu 24.04) has no Qt.ColorScheme; the portal and GTK answers still work there.
ColorScheme = getattr(Qt, "ColorScheme", _FallbackColorScheme)

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_SETTINGS_INTERFACE = "org.freedesktop.portal.Settings"
APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
COLOR_SCHEME_KEY = "color-scheme"

# org.freedesktop.appearance color-scheme values.
PORTAL_PREFER_DARK = 1
PORTAL_PREFER_LIGHT = 2

# A portal read is a blocking D-Bus call; keep the answer until it changes.
_portal_cache = None
_portal_watcher = None
# The scheme the app pinned onto QStyleHints, so reading it back is not taken
# for the platform's own answer.
_pinned = ColorScheme.Unknown


def clear_cache():
    global _portal_cache
    _portal_cache = None


def note_pinned(scheme):
    global _pinned
    _pinned = scheme


def _from_portal_value(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ColorScheme.Unknown
    if number == PORTAL_PREFER_DARK:
        return ColorScheme.Dark
    if number == PORTAL_PREFER_LIGHT:
        return ColorScheme.Light
    return ColorScheme.Unknown


def _unwrap(value, depth=4):
    """Unwrap nested QDBusVariant values (Read returns v<v<u>>)."""
    for _ in range(depth):
        inner = getattr(value, "variant", None)
        if not callable(inner):
            break
        value = inner()
    return value


def portal_color_scheme():
    """``color-scheme`` from the desktop portal, or Unknown."""
    global _portal_cache
    if _portal_cache is not None:
        return _portal_cache
    scheme = ColorScheme.Unknown
    try:
        from PyQt6.QtDBus import QDBusConnection, QDBusInterface
    except ImportError:
        _portal_cache = scheme
        return scheme
    bus = QDBusConnection.sessionBus()
    if bus.isConnected():
        interface = QDBusInterface(PORTAL_SERVICE, PORTAL_PATH, PORTAL_SETTINGS_INTERFACE, bus)
        if interface.isValid():
            # ReadOne is the version 2 call; Read is older and wraps the value once more.
            for method in ("ReadOne", "Read"):
                reply = interface.call(method, APPEARANCE_NAMESPACE, COLOR_SCHEME_KEY)
                arguments = reply.arguments() if reply is not None else []
                if arguments:
                    scheme = _from_portal_value(_unwrap(arguments[0]))
                    if scheme != ColorScheme.Unknown:
                        break
    _portal_cache = scheme
    return scheme


def _gtk_settings_files():
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return (root / "gtk-4.0" / "settings.ini", root / "gtk-3.0" / "settings.ini")


def _dark_name(name):
    return ColorScheme.Dark if name.endswith(("-dark", ":dark")) else ColorScheme.Light


def gtk_color_scheme():
    """Light or dark from GTK settings files, then ``GTK_THEME``."""
    for path in _gtk_settings_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        prefer_dark = None
        theme_name = ""
        for line in text.splitlines():
            key, _, value = line.partition("=")
            key = key.strip().casefold()
            value = value.strip()
            if key == "gtk-application-prefer-dark-theme":
                prefer_dark = value.casefold() in {"1", "true", "yes"}
            elif key == "gtk-theme-name":
                theme_name = value.casefold()
        if prefer_dark is not None:
            return ColorScheme.Dark if prefer_dark else ColorScheme.Light
        if theme_name:
            return _dark_name(theme_name)
    theme = os.environ.get("GTK_THEME", "").casefold()
    return _dark_name(theme) if theme else ColorScheme.Unknown


def system_color_scheme(app):
    """The desktop's scheme: the portal, then GTK settings, then Qt's platform theme."""
    scheme = portal_color_scheme()
    if scheme == ColorScheme.Unknown:
        scheme = gtk_color_scheme()
    if scheme != ColorScheme.Unknown:
        return scheme
    hints = app.styleHints()
    if not hasattr(hints, "colorScheme"):
        return ColorScheme.Unknown
    scheme = hints.colorScheme()
    # A scheme the app pinned itself says nothing about the desktop.
    return ColorScheme.Unknown if scheme == _pinned else scheme


def _make_portal_watcher():
    from PyQt6.QtDBus import QDBusVariant

    class PortalWatcher(QObject):
        """Turns the portal's SettingChanged broadcast into callbacks."""

        def __init__(self):
            super().__init__()
            self.callbacks = []

        @pyqtSlot(str, str, QDBusVariant)
        def on_setting_changed(self, namespace, key, _value):
            if namespace != APPEARANCE_NAMESPACE or key != COLOR_SCHEME_KEY:
                return
            clear_cache()
            for callback in list(self.callbacks):
                callback()

    return PortalWatcher()


def watch(app, callback):
    """Call ``callback`` when the desktop's light or dark preference may have changed.

    Qt's own signal, and the portal's broadcast, which a sandboxed platform
    theme may never see.
    """
    global _portal_watcher

    def on_qt_change(*_args):
        clear_cache()
        callback()

    signal = getattr(app.styleHints(), "colorSchemeChanged", None)
    if signal is not None:
        signal.connect(on_qt_change)
    try:
        from PyQt6.QtDBus import QDBusConnection
    except ImportError:
        return
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return
    if _portal_watcher is None:
        watcher = _make_portal_watcher()
        if not bus.connect("", PORTAL_PATH, PORTAL_SETTINGS_INTERFACE, "SettingChanged", watcher.on_setting_changed):
            return
        _portal_watcher = watcher
    _portal_watcher.callbacks.append(callback)

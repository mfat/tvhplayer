"""Show a file in the desktop's file manager, with the file selected.

On Linux the OpenURI portal's ``OpenDirectory`` opens the folder that holds a
file passed as an open file descriptor, so it also works inside Flatpak without
extra permissions, and the desktop's file manager selects the file. Without a
portal, ``org.freedesktop.FileManager1`` does the same outside a sandbox.
Windows Explorer and macOS Finder select files from the command line. When
nothing else works, the containing folder is opened.
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QProcess, QUrl
from PyQt6.QtGui import QDesktopServices

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
OPEN_URI_INTERFACE = "org.freedesktop.portal.OpenURI"
FILE_MANAGER_SERVICE = "org.freedesktop.FileManager1"
FILE_MANAGER_PATH = "/org/freedesktop/FileManager1"


def _call_session_bus(service, path, interface, method, arguments):
    """Call a session bus method and wait for its reply; True when it succeeded."""
    try:
        from PyQt6.QtDBus import QDBusConnection, QDBusMessage
    except ImportError:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    message = QDBusMessage.createMethodCall(service, path, interface, method)
    message.setArguments(arguments)
    reply = bus.call(message)
    return reply.type() == QDBusMessage.MessageType.ReplyMessage


def _portal_open_directory(path):
    """Ask the OpenURI portal to show *path* in its folder."""
    try:
        from PyQt6.QtDBus import QDBusUnixFileDescriptor
    except ImportError:
        return False
    if not QDBusUnixFileDescriptor.isSupported():
        return False
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        # The descriptor object keeps its own duplicate, so ours can close.
        return _call_session_bus(
            PORTAL_SERVICE, PORTAL_PATH, OPEN_URI_INTERFACE, "OpenDirectory",
            ["", QDBusUnixFileDescriptor(fd), {}],
        )
    finally:
        os.close(fd)


def _file_manager_show_items(path):
    """Ask an org.freedesktop.FileManager1 file manager to select *path*."""
    uri = QUrl.fromLocalFile(path).toString()
    return _call_session_bus(
        FILE_MANAGER_SERVICE, FILE_MANAGER_PATH, FILE_MANAGER_SERVICE, "ShowItems",
        [[uri], ""],
    )


def _start_detached(program, arguments):
    started = QProcess.startDetached(program, arguments)
    # PyQt6 returns (started, pid).
    return bool(started[0] if isinstance(started, tuple) else started)


def show_in_file_manager(path, platform=None):
    """Open the folder holding *path* with the file selected; True when shown."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return False
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        if _start_detached("explorer", ["/select,", os.path.normpath(path)]):
            return True
    elif platform == "darwin":
        if _start_detached("open", ["-R", path]):
            return True
    elif _portal_open_directory(path) or _file_manager_show_items(path):
        return True
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    return QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

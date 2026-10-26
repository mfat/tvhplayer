"""Ask the system not to sleep while a recording needs this computer.

Linux asks the desktop portal, which works inside Flatpak too, and falls back
to ``systemd-inhibit``. macOS runs ``caffeinate`` for as long as the hold lasts.
Windows marks the app's thread as needing the system.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger('tvhplayer.sleep')

PORTAL_SERVICE = 'org.freedesktop.portal.Desktop'
PORTAL_PATH = '/org/freedesktop/portal/desktop'
PORTAL_INHIBIT = 'org.freedesktop.portal.Inhibit'
PORTAL_REQUEST = 'org.freedesktop.portal.Request'
# Inhibit flags: 4 is suspend.
INHIBIT_SUSPEND = 4

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class SleepInhibitor:
    """Hold or release one sleep block. ``hold`` again with a new reason replaces it."""

    def __init__(self):
        self.reason = ''
        self._portal_handle = ''
        self._process = None
        self._windows = False

    def is_held(self) -> bool:
        return bool(self.reason)

    def hold(self, reason: str) -> None:
        if not reason:
            self.release()
            return
        if reason == self.reason:
            return
        self.release()
        if sys.platform == 'win32':
            self._windows = self._set_windows_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif sys.platform == 'darwin':
            self._process = self._spawn(['caffeinate', '-i', '-w', str(os.getpid())])
        else:
            self._portal_handle = self._portal_inhibit(reason)
            if not self._portal_handle:
                self._process = self._spawn([
                    'systemd-inhibit', '--what=sleep', '--who=TVHplayer',
                    f'--why={reason}', '--mode=block', 'sleep', 'infinity',
                ])
        if self._portal_handle or self._process is not None or self._windows:
            self.reason = reason
            log.info('Keeping the computer awake: %s', reason)
        else:
            log.warning('Could not keep the computer awake: %s', reason)

    def release(self) -> None:
        if self._portal_handle:
            self._portal_close(self._portal_handle)
            self._portal_handle = ''
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        if self._windows:
            self._set_windows_state(ES_CONTINUOUS)
            self._windows = False
        if self.reason:
            log.info('The computer may sleep again')
        self.reason = ''

    def _portal_inhibit(self, reason: str) -> str:
        try:
            from PyQt6.QtCore import QMetaType
            from PyQt6.QtDBus import QDBusArgument, QDBusConnection, QDBusMessage
        except ImportError:
            return ''
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return ''
        message = QDBusMessage.createMethodCall(PORTAL_SERVICE, PORTAL_PATH, PORTAL_INHIBIT, 'Inhibit')
        flags = QDBusArgument()
        flags.add(INHIBIT_SUSPEND, QMetaType.Type.UInt.value)
        message.setArguments(['', flags, {'reason': reason}])
        reply = bus.call(message, timeout=3000)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
            log.info('The desktop portal did not take the sleep block: %s', reply.errorMessage())
            return ''
        handle = reply.arguments()[0]
        return handle.path() if hasattr(handle, 'path') else str(handle)

    def _portal_close(self, handle: str) -> None:
        try:
            from PyQt6.QtDBus import QDBusConnection, QDBusMessage
        except ImportError:
            return
        message = QDBusMessage.createMethodCall(PORTAL_SERVICE, handle, PORTAL_REQUEST, 'Close')
        QDBusConnection.sessionBus().call(message, timeout=3000)

    def _spawn(self, command):
        if shutil.which(command[0]) is None:
            return None
        try:
            return subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            log.warning('Could not run %s: %s', command[0], exc)
            return None

    def _set_windows_state(self, flags: int) -> bool:
        try:
            import ctypes
            return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
        except Exception:
            return False

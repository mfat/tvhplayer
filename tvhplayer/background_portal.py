"""Asynchronous Flatpak background and optional login startup permission."""

from __future__ import annotations

import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher, QDBusPendingReply

SERVICE = 'org.freedesktop.portal.Desktop'
PATH = '/org/freedesktop/portal/desktop'
INTERFACE = 'org.freedesktop.portal.Background'
REQUEST = 'org.freedesktop.portal.Request'


class BackgroundPortal(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bus = QDBusConnection.sessionBus()
        self.handle = ''
        self.autostart = None
        self.succeeded = False
        self.watcher = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._finish(False, 'The desktop did not answer the background request.'))

    def request(self, autostart=False, commandline=None):
        if self.handle:
            return
        self.autostart = None
        self.succeeded = False
        if not self.bus.isConnected():
            self.finished.emit(False, 'The desktop background portal is unavailable.')
            return
        token = 'tvhplayer_' + uuid.uuid4().hex
        sender = self.bus.baseService().lstrip(':').replace('.', '_')
        self.handle = f'{PATH}/request/{sender}/{token}'
        if not self.bus.connect(SERVICE, self.handle, REQUEST, 'Response', self._response):
            self._finish(False, 'Could not receive desktop background permission.')
            return
        message = QDBusMessage.createMethodCall(SERVICE, PATH, INTERFACE, 'RequestBackground')
        options = {
            'handle_token': token,
            'reason': 'Keep the TV server and scheduled recordings running when the player window closes',
            'autostart': bool(autostart),
        }
        if autostart:
            options['commandline'] = list(commandline or ['tvhplayer', '--background'])
        message.setArguments(['', options])
        self.watcher = QDBusPendingCallWatcher(self.bus.asyncCall(message, 10000), self)
        self.watcher.finished.connect(lambda watcher, handle=self.handle: self._requested(watcher, handle))
        self.timer.start(120000)

    def _requested(self, watcher, expected_handle):
        reply = QDBusPendingReply(watcher).reply()
        if self.handle == expected_handle:
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                self._finish(False, 'The desktop background portal is unavailable or rejected the request.')
            else:
                args = reply.arguments()
                handle = args[0] if args else ''
                handle = handle.path() if hasattr(handle, 'path') else str(handle)
                if handle != self.handle:
                    self._finish(False, 'The desktop returned an unexpected background request.')
        watcher.deleteLater()
        if self.watcher is watcher:
            self.watcher = None

    @pyqtSlot('uint', 'QVariantMap')
    def _response(self, response, results):
        if not self.handle:
            return
        self.succeeded = response == 0
        self.autostart = bool(results.get('autostart')) if self.succeeded else None
        granted = self.succeeded and results.get('background') is True
        self._finish(granted, '' if granted else 'The desktop did not allow TVHplayer to run in the background.')

    def _finish(self, granted, reason):
        self.cancel()
        self.finished.emit(granted, reason)

    def cancel(self):
        self.timer.stop()
        if self.handle:
            handle, self.handle = self.handle, ''
            self.bus.disconnect(SERVICE, handle, REQUEST, 'Response', self._response)
            message = QDBusMessage.createMethodCall(SERVICE, handle, REQUEST, 'Close')
            self.bus.asyncCall(message, 3000)

    def set_status(self, text):
        # Version 1 desktops may reject this optional version 2 method.
        message = QDBusMessage.createMethodCall(SERVICE, PATH, INTERFACE, 'SetStatus')
        message.setArguments([{'message': text[:96]}])
        self.bus.asyncCall(message, 3000)

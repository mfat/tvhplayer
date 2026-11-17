"""Desktop activation and Flatpak permission protocol checks."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


def wait_for(qapp, predicate):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


def test_second_launch_activates_owner_and_lock_is_reusable(qapp, tmp_path):
    from tvhplayer.app_instance import AppInstance

    owner = AppInstance(tmp_path)
    second = AppInstance(tmp_path)
    activated = []
    owner.show_requested.connect(lambda: activated.append(True))
    try:
        assert owner.acquire()
        assert not second.acquire()
        wait_for(qapp, lambda: activated)
        assert activated == [True]
        second.close()  # A secondary must never release the owner's endpoint.
        assert owner.server.isListening()
    finally:
        owner.close()
    try:
        assert second.acquire()
    finally:
        second.close()


def test_configuration_profiles_have_independent_instances(qapp, tmp_path):
    from tvhplayer.app_instance import AppInstance

    first = AppInstance(tmp_path / 'one')
    second = AppInstance(tmp_path / 'two')
    try:
        assert first.acquire()
        assert second.acquire()
        assert first.name != second.name
    finally:
        first.close()
        second.close()


@pytest.mark.skipif(not shutil.which('dbus-run-session'), reason='needs an isolated D-Bus session')
@pytest.mark.parametrize('mode', ['grant', 'deny', 'cancel', 'unavailable', 'autostart-only'])
def test_background_portal_real_dbus_response(mode):
    # A fake desktop on a private bus exercises actual Qt marshalling and the
    # Response subscription, without asking the developer's desktop permission.
    script = r'''
import sys
from PyQt6.QtCore import QCoreApplication, QTimer, QObject, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusObjectPath
from tvhplayer.background_portal import BackgroundPortal, SERVICE, PATH, INTERFACE
app = QCoreApplication([])
bus = QDBusConnection.sessionBus()
mode = sys.argv[1]
grant = mode == 'grant'
class Desktop(QObject):
    @pyqtSlot(str, 'QVariantMap', QDBusMessage)
    def RequestBackground(self, parent, options, message):
        assert options['autostart'] is False
        if mode == 'unavailable':
            message.setDelayedReply(True)
            bus.send(message.createErrorReply('org.freedesktop.DBus.Error.UnknownMethod',
                                              'Background portal is unavailable'))
            return
        sender = message.service().lstrip(':').replace('.', '_')
        path = PATH + '/request/' + sender + '/' + options['handle_token']
        message.setDelayedReply(True)
        bus.send(message.createReply([QDBusObjectPath(path)]))
        def respond():
            signal = QDBusMessage.createSignal(path, 'org.freedesktop.portal.Request', 'Response')
            from PyQt6.QtCore import QMetaType
            from PyQt6.QtDBus import QDBusArgument
            code = QDBusArgument()
            code.add(1 if mode == 'cancel' else 0, QMetaType.Type.UInt.value)
            signal.setArguments([code, {'background': grant or mode == 'cancel',
                                        'autostart': mode == 'autostart-only'}])
            bus.send(signal)
        QTimer.singleShot(10, respond)
desktop = Desktop()
assert bus.registerService(SERVICE)
assert bus.registerObject(PATH, INTERFACE, desktop, QDBusConnection.RegisterOption.ExportAllSlots)
portal = BackgroundPortal()
results = []
def finished(ok, reason):
    results.append((ok, reason))
    app.quit()
portal.finished.connect(finished)
portal.request()
QTimer.singleShot(3000, app.quit)
app.exec()
assert len(results) == 1, results
assert results[0][0] is grant, results
assert not portal.handle
assert not portal.timer.isActive()
'''
    result = subprocess.run(
        ['dbus-run-session', '--', sys.executable, '-c', script, mode],
        cwd=Path(__file__).resolve().parents[1], env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_crashed_owner_releases_lock_and_stale_socket(qapp, tmp_path):
    code = '''
import os, sys
from PyQt6.QtCore import QCoreApplication
from tvhplayer.app_instance import AppInstance
app = QCoreApplication([])
instance = AppInstance(sys.argv[1])
assert instance.acquire()
os._exit(0)
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    from tvhplayer.app_instance import AppInstance
    replacement = AppInstance(tmp_path)
    try:
        assert replacement.acquire()
    finally:
        replacement.close()


def test_activation_accepts_only_show_command(qapp, tmp_path):
    from PyQt6.QtNetwork import QLocalSocket
    from tvhplayer.app_instance import AppInstance
    owner = AppInstance(tmp_path)
    activated = []
    owner.show_requested.connect(lambda: activated.append(True))
    socket = QLocalSocket()
    try:
        assert owner.acquire()
        socket.connectToServer(owner.name)
        assert socket.waitForConnected(1000)
        socket.write(b'quit\n')
        assert socket.waitForBytesWritten(1000)
        wait_for(qapp, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert not activated
        assert owner.server.isListening()
    finally:
        socket.abort()
        owner.close()

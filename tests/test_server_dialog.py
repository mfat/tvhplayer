import os
import sys
import time

import pytest

_app = None


@pytest.fixture
def ui(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.modules.pop('tvhplayer.tvhplayer', None)
    import tvhplayer.tvhplayer as module
    from PyQt6.QtWidgets import QApplication

    global _app
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *a, **k: None)
    return module


def _remote(name='UK', url='http://192.168.1.20:9981', **extra):
    server = {'name': name, 'url': url, 'username': '', 'password': '', 'protocol': 'http', 'htsp_port': 9982}
    server.update(extra)
    return server


def _wait(condition, timeout=3.0):
    from PyQt6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_address_check_messages(ui):
    check = ui.validate_server_url
    assert check('') == "Enter the server address"
    assert check('192.168.1.20:9981') == "Must start with http:// or https://"
    assert check('http://host:99999') == "Port must be between 1 and 65535"
    assert check('http://host:abc') == "Invalid port number"
    assert check('http://:9981') == "Enter a host name or IP address"
    assert check('http://192.168.1:9981') == "Invalid IP address format"
    assert check('http://192.168.1.300:9981') == "IP numbers must be between 0 and 255"
    assert check('https://tvh.example.net:9981/tvh') == ""
    assert check('http://127.0.0.1:9981') == ""


def test_edits_apply_live_and_closing_keeps_them(ui):
    original = [_remote()]
    dialog = ui.ServerDialog()
    dialog.load_servers(original)
    assert dialog.pages.currentIndex() == 0
    dialog.name_input.setText('Home')
    assert dialog.servers[0]['name'] == 'Home'
    assert dialog.server_list.item(0).text() == 'Home'
    assert dialog.title_label.text() == 'Home'
    # The caller's list changes only through dialog.servers.
    assert original[0]['name'] == 'UK'

    dialog.protocol_combo.setCurrentIndex(dialog.protocol_combo.findData('htsp'))
    assert dialog.servers[0]['protocol'] == 'htsp'
    assert not dialog.htsp_port_input.isHidden()
    dialog.protocol_combo.setCurrentIndex(dialog.protocol_combo.findData('http'))
    assert dialog.htsp_port_input.isHidden()

    dialog.reject()
    assert dialog.result() == ui.QDialog.DialogCode.Accepted


def test_bad_address_is_flagged_and_blocks_closing(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    dialog.url_input.setText('192.168.1.20:9981')
    assert dialog.url_hint.text() == "Must start with http:// or https://"
    assert dialog.status_label.text() == "Address needs fixing"
    assert not dialog.test_btn.isEnabled()
    assert not dialog.open_web_btn.isEnabled()
    assert dialog.server_list.item(0).data(ui.SERVER_STATUS_ROLE) == "Address needs fixing"

    dialog.show()
    dialog.accept()
    assert dialog.isVisible()
    dialog.url_input.setText('http://192.168.1.20:9981')
    assert dialog.url_hint.text() == ui.URL_HINT
    assert dialog.test_btn.isEnabled()
    dialog.accept()
    assert not dialog.isVisible()


def test_add_duplicate_and_remove(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote('A'), _remote('B')])

    dialog.add_server()
    assert dialog.server_list.currentRow() == 2
    assert dialog.servers[2]['name'] == 'New server'
    assert dialog.name_input.selectedText() == 'New server'
    assert dialog.servers[2]['protocol'] == 'htsp'
    assert dialog.protocol_combo.currentData() == 'htsp'
    assert dialog.status_label.text() == "Address needs fixing"

    dialog.server_list.setCurrentRow(0)
    dialog.duplicate_server()
    assert [s['name'] for s in dialog.servers] == ['A', 'A (copy)', 'B', 'New server']
    assert dialog.server_list.currentRow() == 1
    assert dialog.servers[1] is not dialog.servers[0]

    dialog.server_list.setCurrentRow(3)
    dialog.remove_server()
    assert [s['name'] for s in dialog.servers] == ['A', 'A (copy)', 'B']
    assert dialog.server_list.currentRow() == 2
    dialog.server_list.setCurrentRow(0)
    dialog.remove_server()
    assert dialog.server_list.currentRow() == 0
    assert dialog.name_input.text() == 'A (copy)'


def test_connection_test_reports_result(ui, monkeypatch):
    class Backend:
        def __init__(self, server):
            self.server = server

        def ping(self):
            if 'bad' in self.server['url']:
                raise ConnectionError('connection timed out')

        def close(self):
            pass

    monkeypatch.setattr(ui, 'create_backend', Backend)
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote(), _remote('Bad', 'http://bad.local:9981')])
    assert dialog.status_label.text() == "Not checked"

    dialog.test_connection()
    assert _wait(lambda: dialog.status_label.text() == "Connected")
    assert dialog.test_label.text().startswith("Connected to Tvheadend in ")
    assert dialog.server_list.item(0).data(ui.SERVER_STATUS_ROLE) == "Connected"

    dialog.server_list.setCurrentRow(1)
    dialog.test_connection()
    assert _wait(lambda: dialog.status_label.text() == "Unreachable")
    assert dialog.test_label.text() == "Could not connect: connection timed out."

    # Editing a server forgets its result.
    dialog.username_input.setText('admin')
    assert dialog.status_label.text() == "Not checked"
    assert dialog.test_label.text() == "Not tested yet."


def test_builtin_server_page(ui):
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QWidget

    class Supervisor(QObject):
        status_changed = pyqtSignal(str)

        def __init__(self):
            super().__init__()
            self.status = 'stopped'
            self.http_port = 9981

        def is_running(self):
            return self.status == 'running'

        def start(self):
            self.status = 'running'
            self.status_changed.emit('running')

        def stop(self):
            self.status = 'stopped'
            self.status_changed.emit('stopped')

    class Window(QWidget):
        def __init__(self):
            super().__init__()
            self.builtin = Supervisor()
            self.config = {'builtin_autostart': True}

        def _set_builtin_autostart(self, checked):
            self.config['builtin_autostart'] = checked

    window = Window()
    dialog = ui.ServerDialog(window)
    builtin = {'name': 'Built-in server', 'url': 'http://127.0.0.1:9981', 'builtin': True}
    dialog.load_servers([builtin, _remote()])
    assert dialog.pages.currentIndex() == 1
    assert dialog.duplicate_btn.isHidden() and dialog.remove_btn.isHidden()
    assert dialog.status_label.text() == "Stopped"
    assert not dialog.open_web_btn.isEnabled()
    assert dialog.autostart.isChecked()

    dialog.run_btn.click()
    assert dialog.status_label.text() == "Running on this computer"
    assert dialog.run_btn.text() == "S&top Server"
    assert dialog.open_web_btn.isEnabled()
    assert dialog.server_list.item(0).data(ui.SERVER_STATUS_ROLE) == "Running on this computer"

    dialog.autostart.setChecked(False)
    assert window.config['builtin_autostart'] is False

    dialog.remove_server()
    assert len(dialog.servers) == 2

    dialog.server_list.setCurrentRow(1)
    assert dialog.pages.currentIndex() == 0
    assert not dialog.duplicate_btn.isHidden()

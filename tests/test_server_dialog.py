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
    class Backend:
        def ping(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(module, 'create_backend', lambda server: Backend())
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
    assert check('192.168.1.20:9981') == ""
    assert check('myserver') == ""
    assert check('ftp://myserver') == "Use http:// or https://"
    assert check('http://host:99999') == "Port must be between 1 and 65535"
    assert check('http://host:abc') == "Invalid port number"
    assert check('http://:9981') == "Enter a host name or IP address"
    assert check('http://192.168.1:9981') == "Invalid IP address format"
    assert check('http://192.168.1.300:9981') == "IP numbers must be between 0 and 255"
    assert check('https://tvh.example.net:9981/tvh') == ""
    assert check('http://127.0.0.1:9981') == ""


def test_edits_are_drafts_and_ok_saves_them(ui):
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

    dialog.accept()
    assert dialog.result() == ui.QDialog.DialogCode.Accepted


def test_apply_saves_without_closing_and_cancel_discards_later_edits(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    saved = []
    dialog.applied.connect(saved.append)
    dialog.show()
    assert not dialog.apply_btn.isEnabled()
    dialog.name_input.setText('Home')
    assert dialog.apply_btn.isEnabled()
    dialog.apply_btn.click()
    assert dialog.isVisible()
    assert saved[0][0]['name'] == 'Home'
    assert not dialog.apply_btn.isEnabled()
    dialog.name_input.setText('Unsaved')
    dialog.reject()
    assert dialog.result() == ui.QDialog.DialogCode.Rejected
    assert dialog.servers[0]['name'] == 'Home'
    assert len(saved) == 1


def test_close_discards_invalid_draft_without_saving(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    saved = []
    dialog.applied.connect(saved.append)
    dialog.show()
    dialog.url_input.setText('ftp://invalid')
    dialog.apply_btn.click()
    assert dialog.isVisible()
    assert not saved
    dialog.close()
    assert not dialog.isVisible()
    assert dialog.servers == [_remote()]


def test_reverting_edits_disables_apply_and_ok_does_not_resave(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    saved = []
    dialog.applied.connect(saved.append)
    dialog.name_input.setText('Changed')
    dialog.name_input.setText('UK')
    assert not dialog.apply_btn.isEnabled()
    dialog.add_server()
    assert dialog.apply_btn.isEnabled()
    dialog.remove_server()
    assert not dialog.apply_btn.isEnabled()
    dialog.name_input.setText('Saved')
    dialog.apply_btn.click()
    dialog.accept()
    assert len(saved) == 1


def test_portless_address_is_normalized_on_edit_and_close(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote(url='http://tvh.example/tvh')])
    dialog.url_input.editingFinished.emit()
    assert dialog.url_input.text() == 'http://tvh.example:9981/tvh'
    assert dialog.servers[0]['url'] == 'http://tvh.example:9981/tvh'
    dialog.url_input.setText('http://other.example')
    dialog.accept()
    assert dialog.servers[0]['url'] == 'http://other.example:9981'


@pytest.mark.parametrize('address, expected', [
    ('myserver', 'http://myserver:9981'),
    ('127.0.0.1', 'http://127.0.0.1:9981'),
    ('myserver:8080/tvh', 'http://myserver:8080/tvh'),
    ('  myserver  ', 'http://myserver:9981'),
    ('https://myserver', 'https://myserver'),
    ('http://[::1]:9981', 'http://[::1]:9981'),
    ('[::1]', 'http://[::1]:9981'),
    ('https://[2001:db8::1]/tvh', 'https://[2001:db8::1]/tvh'),
])
def test_scheme_is_normalized_on_focus_loss_and_apply(ui, address, expected):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    dialog.url_input.setText(address)
    dialog.url_input.editingFinished.emit()
    assert dialog.url_input.text() == expected
    dialog.url_input.setText(address)
    assert dialog.apply_changes()
    assert dialog.servers[0]['url'] == expected
    assert dialog.url_input.text() == expected


@pytest.mark.parametrize('address', ['myserver?x=1', 'http://host#frag', 'host?', 'host#'])
def test_query_and_fragment_are_rejected_without_rewriting(ui, address):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    dialog.url_input.setText(address)
    dialog.url_input.editingFinished.emit()
    assert dialog.url_input.text() == address
    assert not dialog.test_btn.isEnabled()
    assert not dialog.apply_changes()
    assert 'query or fragment' in dialog.url_hint.text()


def test_bad_address_is_flagged_and_blocks_closing(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    dialog.url_input.setText('ftp://192.168.1.20:9981')
    assert dialog.url_hint.text() == "Use http:// or https://"
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


def test_opening_checks_all_valid_remote_servers_once(ui, monkeypatch):
    from PyQt6.QtCore import QObject, pyqtSignal

    started = []

    class Test(QObject):
        done = pyqtSignal(int, bool, int, str)

        def __init__(self, server, token):
            super().__init__()
            self.server, self.token = dict(server), token

        def start(self):
            started.append(self)

    monkeypatch.setattr(ui, 'ConnectionTest', Test)
    dialog = ui.ServerDialog()
    dialog.load_servers([
        _remote('A'), _remote('B'), _remote('Local', builtin=True),
        _remote('Invalid', 'ftp://host'),
    ])
    dialog.show()
    assert [test.server['name'] for test in started] == ['A', 'B']
    assert dialog.server_list.currentRow() == 0
    assert dialog.server_list.item(1).data(ui.SERVER_STATUS_ROLE) == 'Testing…'
    dialog.test_connection()
    assert len(started) == 2
    started[0].done.emit(started[0].token, True, 10, '')
    started[1].done.emit(started[1].token, False, 10, 'unreachable')
    assert dialog.server_list.item(0).data(ui.SERVER_STATUS_ROLE) == 'Connected'
    assert dialog.server_list.item(1).data(ui.SERVER_STATUS_ROLE) == 'Unreachable'
    dialog.hide()
    dialog.show()
    assert len(started) == 2
    dialog.test_connection()
    assert len(started) == 3
    dialog.username_input.setText('Edited')
    started[2].done.emit(started[2].token, True, 10, '')
    assert dialog.status_label.text() == 'Not checked'
    dialog.reject()


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


@pytest.mark.parametrize('http_error', [None, 'TLS handshake failed'])
def test_htsp_connection_requires_working_http_endpoint(ui, monkeypatch, http_error):
    checked, closed, results = [], [], []

    class Backend:
        def __init__(self, server):
            self.server = server

        def ping(self):
            checked.append(dict(self.server))
            if self.server['protocol'] == 'http':
                assert closed == ['htsp']
            if self.server['protocol'] == 'http' and http_error:
                raise ConnectionError(http_error)

        def close(self):
            closed.append(self.server['protocol'])

    monkeypatch.setattr(ui, 'create_backend', Backend)
    server = _remote(url='https://127.0.0.1:9981', protocol='htsp')
    test = ui.ConnectionTest(server, 1)
    test.done.connect(lambda *result: results.append(result))
    test._run()
    assert [entry['protocol'] for entry in checked] == ['htsp', 'http']
    assert all(entry['url'] == server['url'] for entry in checked)
    assert sorted(closed) == ['htsp', 'http']
    assert server['protocol'] == 'htsp'
    assert results[0][1] is True
    if http_error:
        assert 'HTSP connected' in results[0][3]
        assert http_error in results[0][3]
        dialog = ui.ServerDialog()
        dialog.load_servers([server])
        dialog.test_results[id(dialog.servers[0])] = {
            'phase': 'done', 'ok': True, 'ms': 10, 'error': results[0][3],
        }
        dialog._refresh_selected()
        assert dialog.status_label.text() == 'Partially connected'
        assert 'Playback has not been verified' in dialog.test_label.text()


@pytest.mark.parametrize('change, reloads, selected', [
    ('rename_other', 0, 0), ('rename_active', 0, 0),
    ('remove_other', 0, 0), ('move_active', 0, 1),
    ('change_active', 1, 0), ('autostart', 0, 0),
])
def test_apply_persists_and_only_reloads_changed_active_connection(ui, monkeypatch, change, reloads, selected):
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QWidget, QComboBox

    class Window(QWidget):
        current_server = ui.TVHeadendClient.current_server

        def __init__(self):
            super().__init__()
            self.servers = [_remote('A'), _remote('B', 'http://other:9981')]
            self.server_combo = QComboBox()
            self.server_combo.addItems(['A', 'B'])
            self.builtin = None
            self.config = {'builtin_http_port': 9981, 'builtin_htsp_port': 9982, 'builtin_autostart': True}
            self.config_store = SimpleNamespace(servers=self.servers)
            self.saved = []
            self.closed = self.fetched = 0

        def _builtin_credentials(self):
            return ('', '')

        def save_config(self):
            self.saved.append((dict(self.config), [dict(s) for s in self.servers]))

        def close_backend(self):
            self.closed += 1

        def fetch_channels(self):
            self.fetched += 1

    class Dialog(ui.ServerDialog):
        def exec(self):
            if change == 'rename_other':
                self.servers[1]['name'] = 'Renamed'
            elif change == 'rename_active':
                self.servers[0]['name'] = 'Renamed'
            elif change == 'remove_other':
                self.servers.pop()
            elif change == 'move_active':
                self.servers.reverse()
            elif change == 'change_active':
                self.servers[0]['url'] = 'http://new:9981'
            else:
                self.parent().config['builtin_autostart'] = False
            self.applied.emit(self.servers)
            return self.DialogCode.Rejected

    monkeypatch.setattr(ui, 'ServerDialog', Dialog)
    window = Window()
    ui.TVHeadendClient.manage_servers(window)
    assert len(window.saved) == 1
    assert window.closed == window.fetched == reloads
    assert window.server_combo.currentIndex() == selected
    if change == 'autostart':
        assert window.saved[0][0]['builtin_autostart'] is False


def test_connection_key_accepts_builtin_without_address(ui):
    builtin = {'name': 'Built-in', 'url': '', 'builtin': True, 'protocol': 'htsp'}
    assert ui.server_connection_key(builtin)[0] == ''
    assert ui.server_connection_key(_remote(url='http://tvh.example'))[0] == 'http://tvh.example:9981'


def test_name_edit_keeps_connection_result(ui):
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote()])
    result = {'phase': 'done', 'ok': True, 'ms': 10, 'error': ''}
    dialog.test_results[id(dialog.servers[0])] = result
    dialog.name_input.setText('Renamed')
    assert dialog.status_label.text() == 'Connected'
    assert dialog.test_results[id(dialog.servers[0])] is result


@pytest.mark.parametrize('url, expected', [
    ('myserver', 'http://myserver:9981'),
    ('http://myserver', 'http://myserver:9981'),
    ('http://myserver:80', 'http://myserver:80'),
    ('https://[::1]/tvh', 'https://[::1]/tvh'),
])
def test_open_web_normalizes_without_requiring_save(ui, monkeypatch, url, expected):
    opened = []
    monkeypatch.setattr(ui.QDesktopServices, 'openUrl', lambda value: opened.append(value.toString()))
    dialog = ui.ServerDialog()
    dialog.load_servers([_remote(url=url)])
    dialog._open_web()
    assert opened == [expected]


@pytest.mark.parametrize('builtin', [False, True])
def test_log_viewer_is_modal_child_of_server_management(ui, monkeypatch, builtin):
    from PyQt6.QtWidgets import QWidget

    class Window(QWidget):
        builtin = None
        show_builtin_log = ui.TVHeadendClient.show_builtin_log
        show_server_log = ui.TVHeadendClient.show_server_log

    class RemoteLog(ui.QDialog):
        def __init__(self, server, parent):
            super().__init__(parent)

    # Exercise the real opening methods without starting a remote log watcher.
    monkeypatch.setattr(ui, 'ServerLogDialog', RemoteLog)
    opened = []

    def inspect_exec(viewer):
        opened.append((viewer.parentWidget(), viewer.windowModality()))
        return ui.QDialog.DialogCode.Accepted

    monkeypatch.setattr(ui.QDialog, 'exec', inspect_exec)
    window = Window()
    dialog = ui.ServerDialog(window)
    dialog.load_servers([_remote(builtin=builtin)])
    dialog._show_log()
    assert opened == [(dialog, ui.Qt.WindowModality.WindowModal)]


def test_builtin_log_streams_preserves_scroll_and_stops_on_close(ui):
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication

    class Supervisor(QObject):
        log_output = pyqtSignal(str)

        def log_text(self):
            return ''.join(f'line {i}\n' for i in range(200)) + 'partial'

    supervisor = Supervisor()
    dialog = ui.BuiltinLogDialog(supervisor)
    dialog.show()
    QApplication.processEvents()
    supervisor.log_output.emit(' completed\n')
    assert dialog.view.toPlainText().endswith('partial completed\n')
    bar = dialog.view.verticalScrollBar()
    assert bar.value() == bar.maximum()
    bar.setValue(20)
    supervisor.log_output.emit('next line\n')
    assert bar.value() == 20
    bar.setValue(bar.maximum())
    supervisor.log_output.emit('last line\n')
    assert bar.value() == bar.maximum()
    dialog.close()
    contents = dialog.view.toPlainText()
    supervisor.log_output.emit('after closing\n')
    assert dialog.view.toPlainText() == contents


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
    assert window.config['builtin_autostart'] is True
    applied = []
    dialog.applied.connect(applied.append)
    dialog.apply_btn.click()
    assert len(applied) == 1
    assert window.config['builtin_autostart'] is False
    dialog.autostart.setChecked(True)
    dialog.reject()
    assert window.config['builtin_autostart'] is False

    dialog.remove_server()
    assert len(dialog.servers) == 2

    dialog.server_list.setCurrentRow(1)
    assert dialog.pages.currentIndex() == 0
    assert not dialog.duplicate_btn.isHidden()

"""Login registration tests use temporary directories and a fake Windows registry."""

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import types

import pytest

from tvhplayer.core import autostart


@pytest.fixture
def native(monkeypatch, tmp_path):
    monkeypatch.delenv('FLATPAK_ID', raising=False)
    monkeypatch.delenv('APPIMAGE', raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(autostart.sys, 'platform', 'linux')
    monkeypatch.setattr(autostart, 'launch_command', lambda: ['/opt/TVH Player/tvhplayer', '--background'])
    return tmp_path


def test_linux_register_replace_and_remove(native, monkeypatch):
    path = native / 'autostart/io.github.mfat.tvhplayer-login.desktop'
    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    text = path.read_text()
    assert 'Exec="/opt/TVH Player/tvhplayer" "--background"\n' in text
    assert 'Terminal=false\n' in text
    monkeypatch.setattr(autostart, 'launch_command', lambda: ['/new/location', '--background'])
    assert not autostart.is_enabled()  # The old target is not this app's location.
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    assert '/new/location' in path.read_text()
    assert '/opt/TVH Player' not in path.read_text()
    autostart.set_enabled(False)
    autostart.set_enabled(False)
    assert not path.exists()


def test_mac_user_login_agent_does_not_restart_the_app(native, monkeypatch):
    monkeypatch.setattr(autostart.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: native)
    autostart.set_enabled(True)
    path = native / 'Library/LaunchAgents/io.github.mfat.tvhplayer.login.plist'
    data = plistlib.loads(path.read_bytes())
    assert data['ProgramArguments'] == ['/opt/TVH Player/tvhplayer', '--background']
    assert data['RunAtLoad'] is True
    assert data['KeepAlive'] is False
    assert data['LimitLoadToSessionType'] == 'Aqua'
    autostart.set_enabled(False)
    assert not path.exists()


def test_flatpak_never_writes_native_registration(native, monkeypatch):
    monkeypatch.setenv('FLATPAK_ID', autostart.APP_ID)
    with pytest.raises(OSError, match='portal'):
        autostart.set_enabled(True)
    assert not (native / 'autostart').exists()


def test_windows_registration_is_per_user_and_preserves_other_apps(native, monkeypatch):
    monkeypatch.setattr(autostart.sys, 'platform', 'win32')
    values = {'OtherApp': 'other.exe'}
    opened = []
    class Key:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def query(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1
    def remove(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        del values[name]
    def create(root, path, zero, permissions):
        opened.append((root, path))
        return Key()
    monkeypatch.setitem(sys.modules, 'winreg', types.SimpleNamespace(
        HKEY_CURRENT_USER='HKCU', KEY_SET_VALUE=2, KEY_QUERY_VALUE=1, REG_SZ=1,
        CreateKeyEx=create, SetValueEx=lambda key, name, zero, kind, value: values.__setitem__(name, value),
        QueryValueEx=query, DeleteValue=remove))
    autostart.set_enabled(True)
    assert values['TVHplayer'] == '"/opt/TVH Player/tvhplayer" --background'
    assert opened == [('HKCU', autostart.RUN_KEY)]
    autostart.set_enabled(False)
    assert values == {'OtherApp': 'other.exe'}


def test_desktop_entry_escapes_field_codes_and_shell_characters():
    quoted = autostart.desktop_exec(['/opt/100%/$TVH`"\\player', '--background'])
    assert '100%%' in quoted
    assert '\\\\$' in quoted and '\\\\`' in quoted and '\\\\"' in quoted
    with pytest.raises(ValueError):
        autostart.desktop_exec(['/opt/bad\npath'])


def test_appimage_registration_uses_original_file(monkeypatch, tmp_path):
    monkeypatch.delenv('FLATPAK_ID', raising=False)
    monkeypatch.setenv('APPIMAGE', str(tmp_path / 'TVH Player.AppImage'))
    assert autostart.launch_command() == [str(tmp_path / 'TVH Player.AppImage'), '--background']


@pytest.mark.parametrize('enabled', [False, True])
def test_background_login_entry_respects_preference_and_never_shows_window(tmp_path, enabled):
    # Separate application event loop: do not quit pytest's shared QApplication.
    script = r'''
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from tvhplayer.core.config import ConfigStore
import tvhplayer.tvhplayer as ui
store = ConfigStore()
store.data['start_at_login'] = sys.argv[1] == 'True'
store.save()
ui.frozen_libs.prepare = lambda: None
ui.mpv_missing = lambda: None
ui.prefers_high_contrast = lambda: True
created = []
class Background:
    def start_hidden(self):
        created.append('hidden')
        QTimer.singleShot(0, QApplication.instance().quit)
    def show_window(self):
        raise AssertionError('Login launch unexpectedly activated the window')
    def end_session(self, manager):
        pass
class Window:
    def __init__(self, start_hidden=False):
        assert start_hidden
        self.background = Background()
        created.append('created')
    def show(self):
        raise AssertionError('Login launch unexpectedly showed the window')
ui.TVHeadendClient = Window
sys.argv = ['tvhplayer', '--background']
try:
    ui.main()
except SystemExit as error:
    assert error.code == 0
assert created == (['created', 'hidden'] if store.data['start_at_login'] else [])
'''
    result = subprocess.run([sys.executable, '-c', script, str(enabled)],
                            env=dict(os.environ, TVHPLAYER_PROFILE_DIR=str(tmp_path), QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('mode', ['grant', 'autostart-denied', 'background-denied', 'error'])
def test_flatpak_login_validates_permissions_before_constructing_player(tmp_path, mode):
    script = r'''
import sys
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication
from tvhplayer.core.config import ConfigStore
import tvhplayer.tvhplayer as ui
import tvhplayer.background_portal as portal_module
mode = sys.argv[1]
store = ConfigStore()
store.data['start_at_login'] = True
store.save()
ui.frozen_libs.prepare = lambda: None
ui.mpv_missing = lambda: None
ui.prefers_high_contrast = lambda: True
ui.installed_by_flatpak = lambda: True
created = []
class Portal(QObject):
    finished = pyqtSignal(bool, str)
    def __init__(self, parent):
        super().__init__(parent)
        self.succeeded = mode != 'error'
        self.autostart = mode not in ('autostart-denied', 'error')
    def request(self, **options):
        assert options['autostart'] is True
        self.finished.emit(mode in ('grant', 'autostart-denied'), 'Denied')
class Background(QObject):
    def start_hidden(self):
        created.append('hidden')
        QTimer.singleShot(0, QApplication.instance().quit)
    def show_window(self):
        raise AssertionError('Unexpected activation')
    def end_session(self, manager):
        pass
    def _permission(self, *args):
        pass
class Window:
    def __init__(self, start_hidden=False):
        assert mode in ('grant', 'background-denied'), mode
        assert start_hidden == (mode == 'grant')
        self.background = Background()
        created.append('created')
    def show(self):
        created.append('visible')
        QTimer.singleShot(0, QApplication.instance().quit)
ui.TVHeadendClient = Window
portal_module.BackgroundPortal = Portal
sys.argv = ['tvhplayer', '--background']
try:
    ui.main()
except SystemExit as error:
    assert error.code == 0
expected = ['created', 'hidden'] if mode == 'grant' else ['created', 'visible'] if mode == 'background-denied' else []
assert created == expected, created
if mode == 'autostart-denied':
    assert ConfigStore().data['start_at_login'] is False
'''
    result = subprocess.run([sys.executable, '-c', script, mode],
                            env=dict(os.environ, TVHPLAYER_PROFILE_DIR=str(tmp_path), QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr

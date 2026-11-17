"""Per-user application login startup. No administrator rights or server service."""

from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

APP_ID = 'io.github.mfat.tvhplayer'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'TVHplayer'


def launch_command():
    """Keep paths stable across logins, including a mounted AppImage."""
    if os.environ.get('FLATPAK_ID'):
        return ['tvhplayer', '--background']
    if os.environ.get('APPIMAGE'):
        return [os.path.abspath(os.environ['APPIMAGE']), '--background']
    executable = os.path.abspath(sys.executable)
    if getattr(sys, 'frozen', False):
        return [executable, '--background']
    if sys.platform == 'win32':
        pythonw = Path(executable).with_name('pythonw.exe')
        if pythonw.is_file():
            executable = str(pythonw)
    # Execute the installed/source script directly, independently of the login
    # working directory, while preserving the current virtual environment.
    return [executable, str(Path(__file__).resolve().parents[1] / 'tvhplayer.py'), '--background']


def desktop_exec(command):
    """Quote argv for a Desktop Entry, including its two escaping layers."""
    def quote(arg):
        if any(char in arg for char in '\n\r\0'):
            raise ValueError('The application path contains an unsupported control character.')
        arg = arg.replace('%', '%%')
        for char in ('\\', '"', '`', '$'):
            arg = arg.replace(char, '\\' + char)
        # Desktop Entry string unescaping happens before Exec unquoting.
        return '"' + arg.replace('\\', '\\\\') + '"'
    return ' '.join(quote(str(arg)) for arg in command)


def _registration_path():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'LaunchAgents' / (APP_ID + '.login.plist')
    if sys.platform.startswith('linux'):
        config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        return config / 'autostart' / (APP_ID + '-login.desktop')
    raise OSError('Login startup is not supported on this platform.')


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if path.read_bytes() != data:
        raise OSError('Could not verify the login startup registration.')


def set_enabled(enabled):
    """Apply and verify native registration; Flatpak must use the portal instead."""
    if os.environ.get('FLATPAK_ID') or Path('/.flatpak-info').exists():
        raise OSError('Flatpak login startup must be requested through the desktop portal.')
    if sys.platform == 'win32':
        import winreg
        command = subprocess.list2cmdline(launch_command())
        if enabled and len(command) > 260:
            raise OSError('The application path is too long for Windows login startup.')
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
                if winreg.QueryValueEx(key, RUN_NAME)[0] != command:
                    raise OSError('Could not verify Windows login startup.')
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
                try:
                    winreg.QueryValueEx(key, RUN_NAME)
                except FileNotFoundError:
                    return
                raise OSError('Windows did not remove the login startup registration.')
        return
    path = _registration_path()
    if not enabled:
        path.unlink(missing_ok=True)
        if path.exists():
            raise OSError('Could not remove the login startup registration.')
        return
    _write(path, _registration_data())


def _registration_data():
    command = launch_command()
    if sys.platform == 'darwin':
        data = plistlib.dumps({
            'Label': APP_ID + '.login', 'ProgramArguments': command,
            'RunAtLoad': True, 'KeepAlive': False, 'LimitLoadToSessionType': 'Aqua',
        })
    else:
        data = ('[Desktop Entry]\nType=Application\nName=TVHplayer\n'
                'Comment=Start TVHplayer in the background at login\n'
                f'Exec={desktop_exec(command)}\n'
                f'Icon={APP_ID}\nTerminal=false\nStartupNotify=false\n').encode('utf-8')
    return data


def is_enabled():
    """Verify our current launch target, including an externally removed entry."""
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return winreg.QueryValueEx(key, RUN_NAME)[0] == subprocess.list2cmdline(launch_command())
        except FileNotFoundError:
            return False
    try:
        return _registration_path().read_bytes() == _registration_data()
    except FileNotFoundError:
        return False

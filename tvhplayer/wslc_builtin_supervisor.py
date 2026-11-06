"""Opt-in Windows backend. All WSLc and HTTP work runs off the Qt thread."""
from __future__ import annotations

import csv
import io
import json
import os
import logging
import re
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

from PyQt6.QtCore import QObject, QLockFile, pyqtSignal

try:
    from .core.builtin_server import (ensure_superuser, initial_ports, serverinfo_ok,
                                     apply_builtin_defaults, set_padding, pick_port_pair, use_guest_ffmpeg)
    from .core.windows_backend_paths import bind_mount
    from .core.logs import sanitize, SERVER_LOGGER
    from .core.windows_wslc import WslcRuntimeAdapter, WslcError, WslcPrerequisiteError, port_conflict
except ImportError:  # PyInstaller/source script imports
    from core.builtin_server import (ensure_superuser, initial_ports, serverinfo_ok,
                                    apply_builtin_defaults, set_padding, pick_port_pair, use_guest_ffmpeg)
    from core.windows_backend_paths import bind_mount
    from core.logs import sanitize, SERVER_LOGGER
    from core.windows_wslc import WslcRuntimeAdapter, WslcError, WslcPrerequisiteError, port_conflict


GUEST_FFMPEG_MIGRATION = 1


def _private_acl(sddl, sid):
    """Accept only a protected DACL granting inheritable full access to us/SYSTEM."""
    match = re.fullmatch(r'D:P(?:AI|AR)*((?:\([^()]*\))+)', sddl)
    return bool(match and sorted(re.findall(r'\(([^()]*)\)', match[1])) ==
                sorted(('A;OICI;FA;;;SY', f'A;OICI;FA;;;{sid}')))


def _folder_is_private(folder, sid):
    """Read the current Windows ACL; a marker or an mtime cannot prove protection."""
    import ctypes
    from ctypes import wintypes
    descriptor = ctypes.c_void_p()
    text = wintypes.LPWSTR()
    try:
        security = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        security.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                                  *([ctypes.POINTER(ctypes.c_void_p)] * 5)]
        security.GetNamedSecurityInfoW.restype = wintypes.DWORD
        security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD),
        ]
        security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
        if security.GetNamedSecurityInfoW(str(folder), 1, 4, None, None, None, None, ctypes.byref(descriptor)):
            return False
        try:
            if not security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descriptor, 1, 4, ctypes.byref(text), None):
                return False
            try:
                return _private_acl(text.value, sid)
            finally:
                kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            kernel.LocalFree(descriptor)
    except (AttributeError, OSError, ValueError):
        return False


def protect_config(folder):
    """Windows chmod does not protect secrets: restrict the dedicated config tree."""
    folder.mkdir(parents=True, exist_ok=True)
    kwargs = dict(capture_output=True, text=True, timeout=10,
                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    result = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'], **kwargs)
    sid = next(csv.reader(io.StringIO(result.stdout)))[1]
    if not sid.startswith('S-1-'):
        raise WslcError('Could not identify the Windows account for backend permissions.')
    if _folder_is_private(folder, sid):
        return
    subprocess.run(['icacls.exe', str(folder), '/inheritance:r', '/grant:r',
                    f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], **kwargs)


def write_record(path, data):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class WslcBuiltinSupervisor(QObject):
    status_changed = pyqtSignal(str)
    ready = pyqtSignal(int, int)
    failed = pyqtSignal(str)
    log_output = pyqtSignal(str)
    _phase = pyqtSignal(str)
    _completed = pyqtSignal(str)
    _started = pyqtSignal()

    available = True
    can_install = True

    def __init__(self, config_dir, backend_dir, http_port=0, htsp_port=0, parent=None,
                 runtime=None):
        super().__init__(parent)
        self.config_dir = Path(config_dir)
        self.backend_dir = Path(backend_dir)
        self.runtime = runtime or WslcRuntimeAdapter()
        self.http_port, self.htsp_port = http_port, htsp_port
        self.username = self.password = ''
        self.recordings_dir = ''
        self.padding = None
        self._status = 'stopped'
        self._thread = None
        self._cancel = threading.Event()
        self.runtime.cancel = self._cancel
        self._closing = False
        self._log = []
        self._lock = None
        self.setup_issue = None
        self._phase.connect(self._set_status)
        self._completed.connect(self._finish)
        self._started.connect(self._on_ready)
        self.log_output.connect(self._append_log)

    @property
    def status(self):
        return self._status

    @property
    def needs_setup(self):
        return not (self.backend_dir / 'manifest.json').is_file()

    def is_running(self):
        return self._status == 'running' and not self._cancel.is_set()

    def log_text(self):
        return ''.join(self._log)

    def _append_log(self, text):
        self._log = (self._log + [text])[-400:]

    def _emit_log(self, text):
        if self.password:
            text = text.replace(self.password, '<redacted>')
        text = sanitize(text)
        logger = logging.getLogger(SERVER_LOGGER)
        for line in text.splitlines():
            if line.strip():
                logger.info(line)
        self.log_output.emit(text)

    def _set_status(self, status):
        if self._closing or self._cancel.is_set():
            return
        self._status = status
        self.status_changed.emit(status)

    def start(self):
        if self._closing or self._thread is not None:
            return
        self.setup_issue = None
        try:
            self.config_dir.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._finish(f'Could not create the backend settings folder: {exc}')
            return
        self._lock = QLockFile(str(self.config_dir.parent / 'wslc.lock'))
        if not self._lock.tryLock(0):
            self._status = 'failed'
            self.status_changed.emit('failed')
            message = ('Could not write the backend lock file. Check the settings-folder permissions.'
                       if self._lock.error() == QLockFile.LockError.PermissionError
                       else 'Another TVHplayer is using the built-in backend.')
            self.failed.emit(message)
            return
        self._cancel.clear()
        self._set_status('starting')
        self._thread = threading.Thread(target=self._run, name='tvhplayer-wslc', daemon=True)
        self._thread.start()

    def _run(self):
        owner = uuid.uuid4().hex
        name = 'tvhplayer-' + owner
        launched = False
        error = ''
        record = self.config_dir / 'wslc-owner.json'
        try:
            self.runtime.check()
            protect_config(self.config_dir)
            # QLockFile ensures no second UI is using this config. A stale record
            # identifies only our previous randomly named, labelled container.
            if record.exists():
                previous = json.loads(record.read_text(encoding='utf-8'))
                self.runtime.stop_owned(previous['name'], previous['owner'])
                record.unlink()
            self._phase.emit('installing')
            image = self.runtime.provision(self.backend_dir)
            if self._cancel.is_set():
                return
            self.username, self.password = ensure_superuser(self.config_dir)
            self.runtime.prepare_config(image, self.config_dir)
            if self._cancel.is_set():
                return
            state_path = self.config_dir / '.tvhplayer-runtime.json'
            previous_state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            if previous_state.get('image') and previous_state['image'] != image:
                snapshot = self.runtime.backup_config(upgrade=True)
                self._emit_log(f'Backing up backend settings to {snapshot}\n')
            recordings = Path(self.recordings_dir) if self.recordings_dir else self.config_dir.parent / 'Recordings'
            bind_mount(str(recordings), '/recordings')
            recordings.mkdir(parents=True, exist_ok=True)
            self.http_port, self.htsp_port = initial_ports(self.http_port, self.htsp_port)
            self._phase.emit('starting')
            for attempt in range(3):
                ports = (self.http_port, self.htsp_port)
                write_record(record, {'name': name, 'owner': owner})
                # Mark before launch: if the CLI times out, the container may exist.
                launched = True
                try:
                    self.runtime.launch(image, name, owner, self.config_dir, recordings, ports)
                    break
                except WslcError as exc:
                    if attempt == 2 or not port_conflict(exc) or self._cancel.is_set():
                        raise
                    self.runtime.stop_owned(name, owner)
                    launched = False
                    record.unlink(missing_ok=True)
                    self.http_port, self.htsp_port = pick_port_pair(avoid=ports)
                    owner = uuid.uuid4().hex
                    name = 'tvhplayer-' + owner
                    self._emit_log('Server ports were in use; retrying with different ports.\n')
            deadline = time.monotonic() + 60
            while not self._cancel.is_set():
                self.runtime.verify_running(name, owner, ports)
                if serverinfo_ok(self.http_port, username=self.username, password=self.password):
                    with socket.create_connection(('127.0.0.1', self.htsp_port), timeout=1):
                        pass
                    failures = apply_builtin_defaults(self.http_port, self.username, self.password,
                                                      '/recordings', self.padding)
                    if failures:
                        raise WslcError('Could not configure backend: ' + ', '.join(failures))
                    generation = self.runtime.config_generation
                    if (previous_state.get('guest_ffmpeg') != GUEST_FFMPEG_MIGRATION
                            or previous_state.get('config_generation') != generation
                            or previous_state.get('image') != image):
                        migrated = use_guest_ffmpeg(self.http_port, self.username, self.password, self._cancel)
                        if migrated < 0:
                            if self._cancel.is_set():
                                return
                            raise WslcError('Could not migrate playlist commands to Linux FFmpeg.')
                    if self._cancel.is_set():
                        return
                    write_record(state_path, {'schema': 1, 'image': image,
                                             'guest_ffmpeg': GUEST_FFMPEG_MIGRATION,
                                             'config_generation': generation})
                    (self.config_dir.parent / 'wslc-setup.json').unlink(missing_ok=True)
                    self._started.emit()
                    break
                if time.monotonic() > deadline:
                    raise WslcError('Built-in TVHeadend did not become ready within 60 seconds.')
                self._cancel.wait(.5)
            previous_log = ''
            while not self._cancel.wait(2):
                self.runtime.verify_running(name, owner, ports)
                current_log = self.runtime.logs_owned(name, owner)
                if current_log != previous_log:
                    delta = current_log[len(previous_log):] if current_log.startswith(previous_log) else current_log
                    self._emit_log(delta + '\n')
                    previous_log = current_log
        except Exception as exc:
            error = '' if self._cancel.is_set() else str(exc)
            if isinstance(exc, WslcPrerequisiteError):
                self.setup_issue = exc
            if launched and not self._cancel.is_set():
                try:
                    self._emit_log(self.runtime.logs_owned(name, owner) + '\n')
                except Exception:
                    pass
        finally:
            if launched:
                try:
                    self.runtime.stop_owned(name, owner)
                    record.unlink(missing_ok=True)
                    self.runtime.backup_config()
                except Exception as exc:
                    error = (error + '\n' if error else '') + f'Backend cleanup failed ({name}): {exc}'
            self._completed.emit(error)

    def _on_ready(self):
        if self._cancel.is_set() or self._closing:
            return
        self._set_status('running')
        self.ready.emit(self.http_port, self.htsp_port)

    def _finish(self, error):
        self._thread = None
        if self._lock:
            self._lock.unlock()
        if error:
            self._emit_log(error + '\n')
        self._status = 'failed' if error else 'stopped'
        self.status_changed.emit(self._status)
        if error and not self._closing:
            self.failed.emit(error)

    def stop(self):
        self._cancel.set()
        if self._thread:
            self._status = 'stopping'
            self.status_changed.emit('stopping')
        else:
            self._status = 'stopped'
            self.status_changed.emit('stopped')

    def shut_down(self):
        self._closing = True
        self.stop()
        # Keep the QObject alive while bounded CLI cleanup finishes. If image import
        # is still running, cancellation is observed before a container is created.
        if self._thread:
            self._thread.join(timeout=35)

    def set_recordings_dir(self, folder):
        if self._thread is not None and folder != self.recordings_dir:
            self._emit_log('Stop the built-in server before changing its recordings folder.\n')
            return False
        if folder:
            try:
                bind_mount(folder, '/recordings')
            except ValueError:
                return False
        self.recordings_dir = folder or ''
        return True

    def set_padding(self, padding):
        self.padding = tuple(padding)
        if not self.is_running():
            return True
        return set_padding(self.http_port, self.padding, self.username, self.password)

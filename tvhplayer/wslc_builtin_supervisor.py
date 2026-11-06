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
                                     apply_builtin_defaults, apply_hdhomerun_transport,
                                     set_padding, pick_port_pair, use_guest_ffmpeg)
    from .core.windows_backend_paths import bind_mount
    from .core.logs import sanitize, SERVER_LOGGER
    from .core.hdhomerun import probe_host_device, pick_udp_base, plan_transport
    from .core.windows_wslc import WslcRuntimeAdapter, WslcError, WslcPrerequisiteError, port_conflict
except ImportError:  # PyInstaller/source script imports
    from core.builtin_server import (ensure_superuser, initial_ports, serverinfo_ok,
                                    apply_builtin_defaults, apply_hdhomerun_transport,
                                    set_padding, pick_port_pair, use_guest_ffmpeg)
    from core.windows_backend_paths import bind_mount
    from core.logs import sanitize, SERVER_LOGGER
    from core.hdhomerun import probe_host_device, pick_udp_base, plan_transport
    from core.windows_wslc import WslcRuntimeAdapter, WslcError, WslcPrerequisiteError, port_conflict


GUEST_FFMPEG_MIGRATION = 1


def _private_acl(sddl, sid, expected_sddl=None):
    """Accept only a protected DACL granting inheritable full access to us/SYSTEM."""
    match = re.fullmatch(r'D:P(?:AI|AR)*((?:\([^()]*\))+)', sddl)
    expected = expected_sddl or f'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})'
    expected_match = re.fullmatch(r'D:P(?:AI|AR)*((?:\([^()]*\))+)', expected)
    return bool(match and expected_match and
                sorted(re.findall(r'\(([^()]*)\)', match[1])) ==
                sorted(re.findall(r'\(([^()]*)\)', expected_match[1])))


def _set_private_acl(folder, sid):
    """Replace the folder DACL with exactly the two inheritable full-control ACEs.

    ``icacls /grant:r`` only replaces grants for the identities named on the
    command line, so an older explicit ACE for another account can survive.
    Building the DACL here makes the result exact, and the caller re-reads it.
    """
    import ctypes
    from ctypes import wintypes
    sddl = f'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})'
    descriptor = ctypes.c_void_p()
    kernel = None
    try:
        security = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.ULONG),
        ]
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        security.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL),
        ]
        security.GetSecurityDescriptorDacl.restype = wintypes.BOOL
        security.SetNamedSecurityInfoW.argtypes = [
            wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        security.SetNamedSecurityInfoW.restype = wintypes.DWORD
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError()
        present = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        if not security.GetSecurityDescriptorDacl(
                descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError()
        if not present.value or not dacl.value:
            raise WslcError('Could not build the backend settings permissions.')
        # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        code = security.SetNamedSecurityInfoW(str(folder), 1, 4 | 0x80000000,
                                              None, None, dacl, None)
        if code:
            raise ctypes.WinError(code)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise WslcError(f'Could not secure the backend settings folder: {exc}') from exc
    finally:
        if descriptor.value and kernel is not None:
            kernel.LocalFree(descriptor)


def _folder_is_private(folder, sid):
    """Read the current Windows ACL; a marker or an mtime cannot prove protection."""
    import ctypes
    from ctypes import wintypes
    descriptor = ctypes.c_void_p()
    text = wintypes.LPWSTR()
    expected_descriptor = ctypes.c_void_p()
    expected_text = wintypes.LPWSTR()
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
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.ULONG),
        ]
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        if security.GetNamedSecurityInfoW(str(folder), 1, 4, None, None, None, None, ctypes.byref(descriptor)):
            return False
        try:
            if not security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descriptor, 1, 4, ctypes.byref(text), None):
                return False
            try:
                # Windows can serialize account SIDs as aliases (e.g. LA for
                # the local Administrator). Canonicalize the expected ACL with
                # the same API, preserving exact identities and permissions.
                expected = f'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})'
                try:
                    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                            expected, 1, ctypes.byref(expected_descriptor), None):
                        return False
                    if not security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                            expected_descriptor, 1, 4, ctypes.byref(expected_text), None):
                        return False
                    return _private_acl(text.value, sid, expected_text.value)
                finally:
                    if expected_text:
                        kernel.LocalFree(ctypes.cast(expected_text, ctypes.c_void_p))
                    if expected_descriptor.value:
                        kernel.LocalFree(expected_descriptor)
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
    _set_private_acl(folder, sid)
    # Never continue with an ACL we cannot prove; the folder holds credentials.
    if not _folder_is_private(folder, sid):
        raise WslcError('Could not secure the backend settings folder.')


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
        self.hdhomerun_transport = None
        self.setup_issue = None
        try:
            from .core.windows_prerequisites import pending_setup
        except ImportError:
            from core.windows_prerequisites import pending_setup
        saved_setup = pending_setup(self.config_dir) or {}
        self.disabled = saved_setup.get('stage') == 'disabled'
        self.setup_checks = saved_setup.get('checks') or []
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
        if self.disabled or self._closing or self._thread is not None:
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

    def enable_and_check(self):
        """Explicit user action after changing firmware or choosing to retry setup."""
        try:
            from .core.windows_prerequisites import save_setup
        except ImportError:
            from core.windows_prerequisites import save_setup
        save_setup(self.config_dir, 'check_required', 'check')
        self.disabled = False
        self.start()

    def _run(self):
        owner = uuid.uuid4().hex
        name = 'tvhplayer-' + owner
        launched = False
        error = ''
        record = self.config_dir / 'wslc-owner.json'
        try:
            try:
                from .core.windows_prerequisites import restart_still_required
            except ImportError:
                from core.windows_prerequisites import restart_still_required
            if restart_still_required(self.config_dir):
                raise WslcPrerequisiteError(
                    'Restart Windows to finish built-in server setup, even if no reboot prompt appeared. '
                    'Save your work, use Start > Power > Restart, then reopen TVHplayer. '
                    'Restarting only the app does not complete setup.', 'reboot')
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
            transport = self._plan_hdhomerun_transport()
            self._phase.emit('starting')
            for attempt in range(3):
                ports = (self.http_port, self.htsp_port)
                udp_ports = self._udp_specs(transport)
                self.runtime.configure_hdhomerun(transport)
                write_record(record, {'name': name, 'owner': owner})
                # Mark before launch: if the CLI times out, the container may exist.
                launched = True
                try:
                    self.runtime.launch(image, name, owner, self.config_dir, recordings, ports, udp_ports)
                    break
                except WslcError as exc:
                    if attempt == 2 or not port_conflict(exc) or self._cancel.is_set():
                        raise
                    self.runtime.stop_owned(name, owner)
                    launched = False
                    record.unlink(missing_ok=True)
                    self.http_port, self.htsp_port = pick_port_pair(avoid=ports)
                    transport = self._replan_hdhomerun_transport(transport)
                    owner = uuid.uuid4().hex
                    name = 'tvhplayer-' + owner
                    self._emit_log('Server ports were in use; retrying with different ports.\n')
            deadline = time.monotonic() + 60
            while not self._cancel.is_set():
                self.runtime.verify_running(name, owner, ports, udp_ports)
                if serverinfo_ok(self.http_port, username=self.username, password=self.password):
                    with socket.create_connection(('127.0.0.1', self.htsp_port), timeout=1):
                        pass
                    failures = apply_builtin_defaults(self.http_port, self.username, self.password,
                                                      '/recordings', self.padding)
                    if transport is not None and not apply_hdhomerun_transport(
                            self.http_port, transport.local_ip, transport.base_port,
                            self.username, self.password):
                        failures.append('HDHomeRun stream address')
                    if failures:
                        raise WslcError('Could not configure backend: ' + ', '.join(failures))
                    if transport is not None:
                        self._emit_log(
                            f'HDHomeRun streaming configured: udp://{transport.local_ip}:'
                            f'{transport.base_port}-{transport.ports[-1]} for '
                            f'{transport.tuner_count} tuner(s).\n')
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
                self.runtime.verify_running(name, owner, ports, udp_ports)
                current_log = self.runtime.logs_owned(name, owner)
                if current_log != previous_log:
                    delta = current_log[len(previous_log):] if current_log.startswith(previous_log) else current_log
                    self._emit_log(delta + '\n')
                    previous_log = current_log
        except Exception as exc:
            error = '' if self._cancel.is_set() else str(exc)
            try:
                from .core.windows_prerequisites import failed_checks
            except ImportError:
                from core.windows_prerequisites import failed_checks
            self.setup_checks = failed_checks(getattr(self.runtime, 'setup_checks', []),
                                               getattr(exc, 'action', 'diagnose'))
            if isinstance(exc, WslcPrerequisiteError):
                self.setup_issue = exc
                if exc.action == 'bios':
                    self.disabled = True
                try:
                    from .core.windows_prerequisites import pending_setup, save_setup
                except ImportError:
                    from core.windows_prerequisites import pending_setup, save_setup
                try:
                    if self.disabled:
                        save_setup(self.config_dir, 'disabled', exc.action, self.setup_checks)
                    elif not pending_setup(self.config_dir):
                        save_setup(self.config_dir, 'check_required', exc.action)
                except OSError:
                    logging.getLogger(__name__).exception('Could not save built-in server setup progress')
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

    @staticmethod
    def _udp_specs(transport):
        return tuple((transport.local_ip, port) for port in transport.ports) if transport else ()

    def _plan_hdhomerun_transport(self):
        """Pick the LAN address and UDP range HDHomeRun will stream to.

        Use the configured device's current route and a short unicast probe.
        Broadcast discovery belongs to setup, not every server start. Absence
        of a tuner must not prevent IPTV, recordings or guide access.
        """
        address = self.runtime.hdhomerun_device()
        try:
            device = probe_host_device(address, cancel=self._cancel) if address else None
            if self._cancel.is_set():
                return None
            transport = plan_transport([device] if device else [], device_ip=address, cancel=self._cancel)
        except Exception as exc:
            self._emit_log(f'HDHomeRun streaming could not be configured: {exc}\n')
            transport = None
        if transport is None:
            self._emit_log('No Windows LAN address is available; HDHomeRun streaming is disabled.\n')
        else:
            self._emit_log(transport.describe() + '.\n')
        self.hdhomerun_transport = transport
        return transport

    def _replan_hdhomerun_transport(self, transport):
        if transport is None:
            return None
        try:
            base = pick_udp_base(transport.tuner_count, avoid=transport.ports,
                                 local_ip=transport.local_ip)
        except RuntimeError as exc:
            self._emit_log(f'{exc}; HDHomeRun streaming is disabled.\n')
            self.hdhomerun_transport = None
            return None
        updated = transport.with_base_port(base)
        self.hdhomerun_transport = updated
        self._emit_log(
            f'HDHomeRun stream ports were in use; using {updated.local_ip}:{updated.base_port}.\n')
        return updated

    def _on_ready(self):
        if self._cancel.is_set() or self._closing:
            return
        self._set_status('running')
        try:
            (self.config_dir.parent / 'wslc-setup.json').unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).exception('Could not clear completed setup progress')
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

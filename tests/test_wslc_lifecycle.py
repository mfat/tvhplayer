import contextlib
import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip('PyQt6')
from tvhplayer import wslc_builtin_supervisor as module
from tvhplayer.core.windows_wslc import WslcError, WslcRuntimeAdapter

IMAGE = 'sha256:' + 'b' * 64


class Runtime:
    def __init__(self, collisions=0):
        self.collisions = collisions
        self.starts = []
        self.stops = []
    def check(self):
        pass
    def provision(self, folder):
        return IMAGE
    def launch(self, image, name, owner, config, recordings, ports):
        self.starts.append((name, owner, ports))
        if len(self.starts) <= self.collisions:
            raise WslcError('bind: Address already in use')
    def verify_running(self, name, owner, ports):
        pass
    def logs_owned(self, name, owner):
        return ''
    def stop_owned(self, name, owner):
        self.stops.append((name, owner))


def supervisor(tmp_path, monkeypatch, runtime):
    monkeypatch.setattr(module, 'bind_mount', lambda *args: None)
    monkeypatch.setattr(module, 'protect_config', lambda path: path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(module, 'serverinfo_ok', lambda *args, **kwargs: True)
    monkeypatch.setattr(module, 'apply_builtin_defaults', lambda *args, **kwargs: [])
    monkeypatch.setattr(module, 'use_guest_ffmpeg', lambda *args: 0)
    monkeypatch.setattr(module.socket, 'create_connection', lambda *args, **kwargs: contextlib.nullcontext())
    s = module.WslcBuiltinSupervisor(tmp_path / 'config', tmp_path, 24111, 24112, runtime=runtime)
    s.recordings_dir = str(tmp_path / 'recordings')
    s.ready.connect(lambda *_ports: s.stop())
    return s


def test_port_collision_recreates_only_owned_container(tmp_path, monkeypatch):
    runtime = Runtime(collisions=1)
    s = supervisor(tmp_path, monkeypatch, runtime)
    s._run()
    assert len(runtime.starts) == 2
    assert runtime.starts[0][0] != runtime.starts[1][0]
    assert runtime.starts[0][2] != runtime.starts[1][2]
    assert runtime.stops == [start[:2] for start in runtime.starts]
    assert not (s.config_dir / 'wslc-owner.json').exists()
    assert s.status == 'stopped'


def test_image_upgrade_backs_up_config_without_recordings(tmp_path, monkeypatch):
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    (s.config_dir / 'channels.json').write_text('keep channels')
    (s.config_dir / '.tvhplayer-runtime.json').write_text(json.dumps({'image': 'sha256:' + 'a' * 64}))
    Path(s.recordings_dir).mkdir()
    (Path(s.recordings_dir) / 'recording.ts').write_bytes(b'keep media')
    s._run()
    snapshots = list((tmp_path / 'backend-backups').glob('*.zip'))
    assert len(snapshots) == 1
    with zipfile.ZipFile(snapshots[0]) as archive:
        assert archive.read('channels.json') == b'keep channels'
        assert not any('recording.ts' in name for name in archive.namelist())
    assert (Path(s.recordings_dir) / 'recording.ts').read_bytes() == b'keep media'
    assert json.loads((s.config_dir / '.tvhplayer-runtime.json').read_text())['image'] == IMAGE


def test_stale_owned_record_is_recovered_before_launch(tmp_path, monkeypatch):
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    previous = {'name': 'tvhplayer-' + 'a' * 32, 'owner': 'a' * 32}
    (s.config_dir / 'wslc-owner.json').write_text(json.dumps(previous))
    s._run()
    assert runtime.stops[0] == (previous['name'], previous['owner'])
    assert len(runtime.starts) == 1


def test_missing_orphan_does_not_block_restart():
    calls = []
    def runner(args, **kwargs):
        import subprocess
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'Object not found: tvhplayer-' + 'a' * 32, '')
    runtime = WslcRuntimeAdapter('wslc.exe', runner)
    assert runtime.stop_owned('tvhplayer-' + 'a' * 32, 'a' * 32) is False
    assert len(calls) == 1


def test_setup_commands_are_explicit_fixed_actions():
    from tvhplayer.windows_backend_setup import setup_command
    assert '--no-distribution' in setup_command('install')[-1]
    assert '-Verb RunAs' in setup_command('install')[-1]
    assert '--update' in setup_command('update')[-1]
    with pytest.raises(ValueError):
        setup_command('arbitrary shell text')


def test_settings_folder_permission_failure_is_reported_without_a_thread(tmp_path, monkeypatch):
    s = module.WslcBuiltinSupervisor(tmp_path / 'private/config', tmp_path, runtime=Runtime())
    reasons = []
    s.failed.connect(reasons.append)
    def denied(*args, **kwargs):
        raise PermissionError('access denied')
    monkeypatch.setattr(Path, 'mkdir', denied)
    s.start()
    assert reasons and 'settings folder' in reasons[0]
    assert s._thread is None and s.status == 'failed'


def test_backend_log_redacts_credentials_and_stream_tickets(tmp_path):
    s = module.WslcBuiltinSupervisor(tmp_path / 'config', tmp_path, runtime=Runtime())
    s.password = 'private-superuser-password'
    lines = []
    s.log_output.connect(lines.append)
    s._emit_log('login private-superuser-password stream http://localhost/stream?ticket=secret-ticket\n')
    assert 'private-superuser-password' not in lines[0]
    assert 'secret-ticket' not in lines[0]

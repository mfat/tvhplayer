import contextlib
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip('PyQt6')
from tvhplayer import wslc_builtin_supervisor as module
from tvhplayer.core.windows_wslc import WslcError, WslcRuntimeAdapter

IMAGE = 'sha256:' + 'b' * 64


class Runtime:
    config_generation = 'c' * 32
    def __init__(self, collisions=0):
        self.collisions = collisions
        self.starts = []
        self.stops = []
        self.backups = []
    def check(self):
        pass
    def provision(self, folder):
        return IMAGE
    def prepare_config(self, image, config):
        pass
    def backup_config(self, *, upgrade=False):
        self.backups.append(upgrade)
        return Path('native-backup.tar.gz')
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
    assert runtime.backups == [True, False]
    assert (s.config_dir / 'channels.json').read_text() == 'keep channels'
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


@pytest.mark.parametrize('private', [True, False])
def test_permissions_are_only_reapplied_when_current_acl_needs_it(tmp_path, monkeypatch, private):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'user,S-1-5-21-123\n', '')
    monkeypatch.setattr(module.subprocess, 'run', run)
    states = iter([private, True])
    monkeypatch.setattr(module, '_folder_is_private', lambda *args: next(states))
    applied = []
    monkeypatch.setattr(module, '_set_private_acl', lambda *args: applied.append(args))
    module.protect_config(tmp_path / 'config')
    assert [args[0] for args in calls] == ['whoami.exe']
    assert bool(applied) is not private


def test_protect_config_fails_closed_when_acl_is_still_not_private(tmp_path, monkeypatch):
    monkeypatch.setattr(module.subprocess, 'run',
                        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, 'user,S-1-5-21-123\n', ''))
    monkeypatch.setattr(module, '_folder_is_private', lambda *args: False)
    monkeypatch.setattr(module, '_set_private_acl', lambda *args: None)
    with pytest.raises(WslcError, match='secure'):
        module.protect_config(tmp_path / 'config')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows ACLs')
def test_protect_config_removes_unexpected_explicit_grant(tmp_path):
    folder = tmp_path / 'config'
    folder.mkdir()
    result = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'],
                            capture_output=True, text=True, check=True)
    sid = next(csv.reader(io.StringIO(result.stdout)))[1]
    try:
        subprocess.run(['icacls.exe', str(folder), '/grant', '*S-1-1-0:(OI)(CI)R'],
                       capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f'cannot set a test ACL in this environment: {exc}')
    assert not module._folder_is_private(folder, sid)
    module.protect_config(folder)
    assert module._folder_is_private(folder, sid)


@pytest.mark.parametrize('sddl,private', [
    ('D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;S-1-5-21-123)', True),
    ('D:P(A;OICI;FA;;;S-1-5-21-123)(A;OICI;FA;;;SY)', True),
    ('D:AI(A;OICI;FA;;;SY)(A;OICI;FA;;;S-1-5-21-123)', False),
    ('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;S-1-5-21-123)(A;OICI;FR;;;WD)', False),
    ('D:P(A;;FA;;;SY)(A;OICI;FA;;;S-1-5-21-123)', False),
    ('D:P(A;OICI;FR;;;SY)(A;OICI;FA;;;S-1-5-21-123)', False),
    ('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;S-1-5-21-456)', False),
])
def test_acl_fast_path_requires_private_inheritable_permissions(sddl, private):
    assert module._private_acl(sddl, 'S-1-5-21-123') is private


def test_playlist_migration_runs_once_and_rechecks_changed_settings(tmp_path, monkeypatch):
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    calls = []
    monkeypatch.setattr(module, 'use_guest_ffmpeg', lambda *a: calls.append('migration') or 0)
    s._run()
    assert calls == ['migration']
    s._cancel.clear()
    s._run()
    assert calls == ['migration']
    runtime.config_generation = 'd' * 32
    s._cancel.clear()
    s._run()
    assert calls == ['migration', 'migration']
    state_path = s.config_dir / '.tvhplayer-runtime.json'
    state = json.loads(state_path.read_text())
    state['image'] = 'sha256:' + 'a' * 64
    state_path.write_text(json.dumps(state))
    s._cancel.clear()
    s._run()
    assert len(calls) == 3


def test_failed_playlist_migration_is_retried(tmp_path, monkeypatch):
    s = supervisor(tmp_path, monkeypatch, Runtime())
    monkeypatch.setattr(module, 'use_guest_ffmpeg', lambda *a: -1)
    s._run()
    assert not (s.config_dir / '.tvhplayer-runtime.json').exists()
    assert s.status == 'failed'
    monkeypatch.setattr(module, 'use_guest_ffmpeg', lambda *a: 0)
    s._run()
    assert json.loads((s.config_dir / '.tvhplayer-runtime.json').read_text())['guest_ffmpeg'] == module.GUEST_FFMPEG_MIGRATION

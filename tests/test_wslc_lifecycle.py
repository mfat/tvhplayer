import contextlib
import csv
import io
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip('PyQt6')
from tvhplayer import wslc_builtin_supervisor as module
from tvhplayer.core.windows_wslc import WslcError, WslcRuntimeAdapter

IMAGE = 'sha256:' + 'b' * 64


class Runtime:
    config_generation = 'c' * 32
    def __init__(self, collisions=0, missing_image=0):
        self.collisions = collisions
        self.missing_image = missing_image
        self.starts = []
        self.stops = []
        self.backups = []
        self.log_tails = []
        self.provision_calls = []
        self.skipped_image_inspect = False
    def check(self):
        pass
    def provision(self, folder, trusted_image=None):
        self.provision_calls.append(trusted_image)
        self.skipped_image_inspect = trusted_image == IMAGE
        return IMAGE
    def prepare_config(self, image, config):
        pass
    def hdhomerun_device(self):
        return ''
    def configure_hdhomerun(self, transport):
        pass
    def backup_config(self, *, upgrade=False):
        self.backups.append(upgrade)
        return Path('native-backup.tar.gz')
    def launch(self, image, name, owner, config, recordings, ports, udp_ports=(), dns_servers=()):
        self.starts.append((name, owner, ports, udp_ports))
        self.dns_servers = tuple(dns_servers)
        if self.missing_image:
            self.missing_image -= 1
            raise WslcError(f'No such image: {image}\nError code: WSLC_E_IMAGE_NOT_FOUND')
        if len(self.starts) <= self.collisions:
            raise WslcError('bind: Address already in use')
    def verify_running(self, name, owner, ports, udp_ports=()):
        pass
    def logs_owned(self, name, owner, **kwargs):
        self.log_tails.append(kwargs.get('tail', 200))
        return getattr(self, 'trace_log', '')
    def monitor_owned(self, name, owner, ports, udp_ports=()):
        self.verify_running(name, owner, ports, udp_ports)
        return self.logs_owned(name, owner)
    def stop_owned(self, name, owner):
        self.stops.append((name, owner))


def supervisor(tmp_path, monkeypatch, runtime):
    monkeypatch.delenv('TVHPLAYER_TRACE_STARTUP', raising=False)
    monkeypatch.setattr(module, 'tcp_accepts', lambda port, timeout=0.05: False)
    monkeypatch.setattr(module, 'bind_mount', lambda *args: None)
    monkeypatch.setattr(module, 'protect_config', lambda path: path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(module, 'serverinfo_ok', lambda *args, **kwargs: True)
    monkeypatch.setattr(module, 'apply_builtin_defaults', lambda *args, **kwargs: [])
    monkeypatch.setattr(module, 'probe_host_device', lambda *args, **kwargs: None)
    monkeypatch.setattr(module, 'plan_transport', lambda devices, **kwargs: None)
    monkeypatch.setattr(module, 'apply_hdhomerun_transport', lambda *args, **kwargs: True)
    monkeypatch.setattr(module, 'use_guest_ffmpeg', lambda *args: 0)
    monkeypatch.setattr(module.socket, 'create_connection', lambda *args, **kwargs: contextlib.nullcontext())
    s = module.WslcBuiltinSupervisor(tmp_path / 'config', tmp_path, 24111, 24112, runtime=runtime)
    s.recordings_dir = str(tmp_path / 'recordings')
    s.ready.connect(lambda *_ports: s.stop())
    return s


def test_readiness_records_each_verification_and_the_first_answers(tmp_path, monkeypatch, caplog):
    runtime = Runtime()
    calls = {'info': 0, 'port': 0}
    seen = {'http': 0, 'htsp': 0}

    def serverinfo(*args, **kwargs):
        calls['info'] += 1
        return calls['info'] >= 2

    def htsp_port(*args, **kwargs):
        calls['port'] += 1
        return calls['port'] >= 2

    def accepts(port, timeout=0.05):
        if int(port) == 24111:
            seen['http'] += 1
            return seen['http'] >= 2
        seen['htsp'] += 1
        return seen['htsp'] >= 2

    s = supervisor(tmp_path, monkeypatch, runtime)
    monkeypatch.setattr(module, 'serverinfo_ok', serverinfo)
    monkeypatch.setattr(module, 'htsp_ready', htsp_port)
    monkeypatch.setattr(module, 'tcp_accepts', accepts)
    with caplog.at_level(logging.INFO):
        s._run()
    assert 'verify_running 1 took' in caplog.text
    assert 'verify_running 2 took' in caplog.text
    assert 'HTTP serverinfo check 1 not ready' in caplog.text
    assert 'HTTP serverinfo first answered' in caplog.text
    assert 'HTTP port first accepted' in caplog.text
    assert 'HTSP port first accepted' in caplog.text
    assert 'HTSP hello did not answer' in caplog.text
    assert 'UI marked the server ready' in caplog.text
    http_port = caplog.text.index('HTTP port first accepted')
    http_api = caplog.text.index('HTTP serverinfo first answered')
    ui_ready = caplog.text.index('UI marked the server ready')
    assert http_port < http_api < ui_ready


def test_native_startup_observations_keep_stage_lines_only():
    text = '\n'.join([
        '2026-11-19 13:45:59.001 [  TRACE] main: startup iptv_network_init: 1916 ms',
        '2026-11-19 13:45:59.001 [  TRACE] main: startup iptv threads: 0 ms (2 thread(s))',
        '2026-11-19 13:45:59.001 [  TRACE] main: mpegts_init() leave',
        '2026-11-19 13:45:59.001 [  TRACE] main: startup mpegts_init: 1935 ms',
        '2026-11-19 13:46:01.662 [  TRACE] main: startup epg decode/restore/destroy: 56/1170/29 ms',
        '2026-11-19 13:46:01.664 [ NOTICE] START: HTS Tvheadend version started',
        'startup mpegts_init without the trace marker',
    ])
    assert module.native_startup_observations(text) == [
        'iptv_network_init: 1916 ms',
        'iptv threads: 0 ms (2 thread(s))',
        'mpegts_init: 1935 ms',
        'epg decode/restore/destroy: 56/1170/29 ms',
    ]
    assert module.native_startup_observations('') == []
    assert module.native_startup_observations(None) == []


def test_traced_startup_records_native_stages_once(tmp_path, monkeypatch, caplog):
    runtime = Runtime()
    runtime.trace_log = (
        '2026-11-19 13:45:59.001 [  TRACE] main: startup mpegts_init: 1935 ms\n'
        '2026-11-19 13:45:59.979 [  TRACE] main: startup channel_init: 977 ms\n'
    )
    s = supervisor(tmp_path, monkeypatch, runtime)
    monkeypatch.setenv('TVHPLAYER_TRACE_STARTUP', '1')
    with caplog.at_level(logging.INFO):
        s._run()
    assert runtime.log_tails == [1000]
    assert 'Built-in startup: mpegts_init: 1935 ms' in caplog.text
    assert 'Built-in startup: channel_init: 977 ms' in caplog.text
    assert 'Connection readiness took' in caplog.text
    readiness = caplog.text.index('Connection readiness took')
    assert caplog.text.index('mpegts_init: 1935 ms') > readiness


def test_startup_trace_read_failure_does_not_fail_startup(tmp_path, monkeypatch, caplog):
    runtime = Runtime()

    def logs_owned(name, owner, **kwargs):
        raise module.WslcError('logs unavailable')

    runtime.logs_owned = logs_owned
    s = supervisor(tmp_path, monkeypatch, runtime)
    monkeypatch.setenv('TVHPLAYER_TRACE_STARTUP', '1')
    with caplog.at_level(logging.INFO):
        s._run()
    assert runtime.stops
    assert 'native stage trace was not read' in caplog.text
    assert 'Built-in startup completed' in caplog.text


def test_normal_startup_does_not_read_a_native_trace(tmp_path, monkeypatch):
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    s._run()
    assert runtime.log_tails == []


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


@pytest.mark.parametrize('failures,fatal', [(['plain login'], True), (['unknown setting'], True),
    (['recordings folder'], False), (['recording margins', 'setup wizard off'], False)])
def test_windows_uses_same_essential_defaults_policy(tmp_path, monkeypatch, failures, fatal):
    s = supervisor(tmp_path, monkeypatch, Runtime())
    monkeypatch.setattr(module, 'apply_builtin_defaults', lambda *args, **kwargs: failures)
    ready, errors = [], []
    s.ready.connect(lambda *_ports: ready.append(True))
    s.failed.connect(errors.append)
    s._run()
    assert bool(errors) == fatal
    assert bool(ready) != fatal
    assert s.startup_warnings == ([] if fatal else failures)


def test_hdhomerun_udp_range_is_published_and_configured(tmp_path, monkeypatch):
    from tvhplayer.core.hdhomerun import HdHomeRunTransport
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    transport = HdHomeRunTransport('192.168.8.211', 30000, 2, device_ip='192.168.8.148')
    monkeypatch.setattr(module, 'plan_transport', lambda devices, **kwargs: transport)
    applied = []
    monkeypatch.setattr(module, 'apply_hdhomerun_transport',
                        lambda *args, **kwargs: applied.append(args) or True)
    s._run()
    expected = (('192.168.8.211', 30000), ('192.168.8.211', 30001))
    assert runtime.starts[0][3] == expected
    assert applied and applied[0][1:3] == ('192.168.8.211', 30000)
    assert 'udp://192.168.8.211:30000-30001' in s.log_text()


def test_transport_planning_uses_configured_device_without_broadcast(tmp_path, monkeypatch):
    from tvhplayer.core.hdhomerun import HostTuner, HdHomeRunTransport
    runtime = Runtime()
    runtime.hdhomerun_device = lambda: '192.168.1.9'
    s = supervisor(tmp_path, monkeypatch, runtime)
    device = HostTuner('192.168.1.9', '192.168.1.5', 4)
    def probe(address, **kwargs):
        assert address == '192.168.1.9'
        return device
    def plan(devices, **kwargs):
        assert devices == [device] and kwargs['device_ip'] == device.ip
        return HdHomeRunTransport(device.local_ip, 30000, device.tuner_count, device.ip)
    monkeypatch.setattr(module, 'probe_host_device', probe)
    monkeypatch.setattr(module, 'plan_transport', plan)
    assert s._plan_hdhomerun_transport().device_ip == device.ip


def test_startup_steps_are_logged_and_tuner_settings_are_separate(tmp_path, monkeypatch, caplog):
    runtime = Runtime()
    runtime.hdhomerun_device = lambda: ''
    s = supervisor(tmp_path, monkeypatch, runtime)
    with caplog.at_level(logging.INFO):
        assert s._plan_hdhomerun_transport() is None
    assert 'Built-in startup: Reading tuner settings…' in caplog.text
    assert 'Built-in startup: Checking tuner networking…' in caplog.text
    reading = caplog.text.index('Reading tuner settings…')
    checking = caplog.text.index('Checking tuner networking…')
    assert reading < checking


def test_unreadable_live_config_does_not_launch_or_overwrite_it(tmp_path, monkeypatch):
    runtime = Runtime()
    def fail():
        raise WslcError('Cannot read live settings')
    runtime.hdhomerun_device = fail
    runtime.configure_hdhomerun = lambda *a: pytest.fail('Must not overwrite unreadable settings')
    s = supervisor(tmp_path, monkeypatch, runtime)
    s._run()
    assert not runtime.starts and s.status == 'failed'


def test_hdhomerun_udp_ports_move_when_a_publish_conflicts(tmp_path, monkeypatch):
    from tvhplayer.core.hdhomerun import HdHomeRunTransport
    runtime = Runtime(collisions=1)
    s = supervisor(tmp_path, monkeypatch, runtime)
    transport = HdHomeRunTransport('192.168.8.211', 30000, 2)
    monkeypatch.setattr(module, 'plan_transport', lambda devices, **kwargs: transport)
    monkeypatch.setattr(module, 'pick_udp_base', lambda *args, **kwargs: 31000)
    s._run()
    assert runtime.starts[0][3] == (('192.168.8.211', 30000), ('192.168.8.211', 30001))
    assert runtime.starts[1][3] == (('192.168.8.211', 31000), ('192.168.8.211', 31001))


def test_missing_image_before_launch_imports_the_bundle_once(tmp_path, monkeypatch):
    runtime = Runtime()
    seen = []
    def prepare(image, config):
        seen.append(image)
        if len(seen) == 1:
            raise WslcError(f'No such image: {image}\nError code: WSLC_E_IMAGE_NOT_FOUND')
    runtime.prepare_config = prepare
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    (s.config_dir / '.tvhplayer-runtime.json').write_text(json.dumps({'image': IMAGE}))
    s._run()
    assert runtime.provision_calls == [IMAGE, None]
    assert seen == [IMAGE, IMAGE]
    assert len(runtime.starts) == 1
    assert s.status == 'stopped'


def test_recorded_image_skips_inspect_until_the_image_is_missing(tmp_path, monkeypatch, caplog):
    runtime = Runtime(missing_image=1)
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    (s.config_dir / '.tvhplayer-runtime.json').write_text(json.dumps({
        'image': IMAGE, 'guest_ffmpeg': module.GUEST_FFMPEG_MIGRATION,
        'config_generation': runtime.config_generation}))
    with caplog.at_level(logging.INFO):
        s._run()
    assert runtime.provision_calls == [IMAGE, None]
    assert len(runtime.starts) == 2
    assert runtime.stops[0] == runtime.starts[0][:2]
    assert 'recorded image was missing' in caplog.text
    assert s.status == 'stopped'


def test_skipped_inspect_does_not_import_on_an_unrelated_launch_failure(tmp_path, monkeypatch):
    runtime = Runtime()
    def fail_launch(*args, **kwargs):
        runtime.starts.append(args)
        raise WslcError('The Windows hypervisor could not start')
    runtime.launch = fail_launch
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    (s.config_dir / '.tvhplayer-runtime.json').write_text(json.dumps({'image': IMAGE}))
    s._run()
    assert runtime.provision_calls == [IMAGE]
    assert s.status == 'failed'


def test_port_conflict_still_retries_when_the_image_inspect_was_skipped(tmp_path, monkeypatch):
    runtime = Runtime(collisions=1)
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    (s.config_dir / '.tvhplayer-runtime.json').write_text(json.dumps({'image': IMAGE}))
    s._run()
    assert runtime.provision_calls == [IMAGE]
    assert len(runtime.starts) == 2


def test_image_upgrade_starts_without_backing_up_settings(tmp_path, monkeypatch):
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    (s.config_dir / 'channels.json').write_text('keep channels')
    (s.config_dir / '.tvhplayer-runtime.json').write_text(json.dumps({'image': 'sha256:' + 'a' * 64}))
    Path(s.recordings_dir).mkdir()
    (Path(s.recordings_dir) / 'recording.ts').write_bytes(b'keep media')
    s._run()
    assert runtime.backups == []
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


def test_shutdown_cancels_without_joining_and_notifies_after_cleanup(tmp_path, monkeypatch, qapp):
    s = supervisor(tmp_path, monkeypatch, Runtime())

    class Worker:
        def join(self, *args, **kwargs):
            pytest.fail('Shutdown must never join a worker on the Qt thread')

    worker = Worker()
    s._thread = worker
    s._status = 'running'
    completed, failures = [], []
    s.shutdown_finished.connect(lambda: completed.append(True))
    s.failed.connect(failures.append)
    assert s.shut_down() is False
    assert s.shut_down() is False
    assert s._cancel.is_set() and s._closing
    assert s._thread is worker and s.status == 'stopping'
    assert not completed
    # Late readiness/progress cannot restart a shutting-down backend.
    s._started.emit()
    s._phase.emit('running')
    assert s.status == 'stopping'
    s._completed.emit('Backend cleanup failed: command timed out')
    assert s._thread is None and s.status == 'failed'
    assert s.last_error == 'Backend cleanup failed: command timed out'
    assert completed == [True] and not failures
    assert s.shut_down() is True
    assert completed == [True]


def test_shutdown_without_a_worker_completes_immediately_and_prevents_restart(tmp_path, monkeypatch):
    s = supervisor(tmp_path, monkeypatch, Runtime())
    assert s.shut_down() is True
    s.start()
    assert s._thread is None and s._cancel.is_set()


def test_shutdown_does_not_call_join(tmp_path, monkeypatch):
    s = supervisor(tmp_path, monkeypatch, Runtime())
    joins = []

    class Worker:
        def join(self, *args, **kwargs):
            joins.append(kwargs)

    s._thread = Worker()
    s.shut_down()
    assert not joins
    s._completed.emit('')


@pytest.mark.parametrize('failure', [False, True])
def test_slow_shutdown_keeps_qt_responsive_and_retains_ownership_until_cleanup(
        tmp_path, monkeypatch, qapp, failure):
    from PyQt6.QtCore import QTimer

    entered, release = threading.Event(), threading.Event()

    class SlowRuntime(Runtime):
        def stop_owned(self, name, owner):
            entered.set()
            if not release.wait(5):
                raise WslcError('test cleanup gate timed out')
            if failure:
                raise WslcError('stop command timed out')
            super().stop_owned(name, owner)

    runtime = SlowRuntime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    monkeypatch.setattr(module, 'htsp_ready', lambda *args, **kwargs: True)
    completed = []
    s.shutdown_finished.connect(lambda: completed.append(True))
    s.start()
    worker = s._thread
    try:
        deadline = time.monotonic() + 3
        while not entered.is_set() and time.monotonic() < deadline:
            qapp.processEvents()
            entered.wait(.005)
        assert entered.is_set()
        started = time.monotonic()
        assert s.shut_down() is False
        assert time.monotonic() - started < .1
        assert s._thread is worker and worker.is_alive()
        assert s._lock.isLocked() and not completed
        pulses = []
        QTimer.singleShot(0, lambda: pulses.append(True))
        qapp.processEvents()
        assert pulses and not completed
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        qapp.processEvents()
        assert completed == [True]
        assert s._thread is None and not s._lock.isLocked()
        assert s.status == ('failed' if failure else 'stopped')
        assert bool(s.last_error) == bool(failure)
        # Failed stop leaves the ownership record for recovery on next launch.
        assert (s.config_dir / 'wslc-owner.json').exists() == failure
        assert runtime.backups == []
    finally:
        release.set()
        s.stop()
        worker.join(3)
        qapp.processEvents()


@pytest.mark.parametrize('quitting', [False, True])
def test_stopping_the_container_preserves_settings_without_creating_a_backup(
        tmp_path, monkeypatch, quitting):
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir()
    storage = s.config_dir / '.tvhplayer-storage'
    storage.mkdir()
    snapshot = storage / 'latest.tar.gz'
    snapshot.write_bytes(b'existing backup')
    (s.config_dir / 'channels.json').write_text('keep channels')
    if quitting:
        s.ready.connect(lambda *_: s.shut_down())
    s._run()
    assert s.status == 'stopped' and not s.last_error
    assert runtime.stops == [runtime.starts[0][:2]]
    assert runtime.backups == []
    assert snapshot.read_bytes() == b'existing backup'
    assert (s.config_dir / 'channels.json').read_text() == 'keep channels'
    assert not (s.config_dir / 'wslc-owner.json').exists()


def test_setup_commands_are_explicit_fixed_actions():
    from tvhplayer.windows_backend_setup import setup_command
    assert '--no-distribution' in setup_command('install')[-1]
    assert '-Verb RunAs' in setup_command('install')[-1]
    assert '--update' in setup_command('update')[-1]
    repair = setup_command('repair')[-1]
    assert 'dism.exe' in repair and '/featurename:VirtualMachinePlatform' in repair
    assert '/norestart' in repair and '-Verb RunAs' in repair
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


@pytest.mark.parametrize('actual,private', [
    ('D:PAI(A;OICI;FA;;;LA)(A;OICI;FA;;;SY)', True),
    ('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;LG)', False),
    ('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;LA)(A;OICI;FR;;;WD)', False),
    ('D:AI(A;OICI;FA;;;SY)(A;OICI;FA;;;LA)', False),
])
def test_acl_comparison_uses_native_canonical_account_identity(actual, private):
    sid = 'S-1-5-21-123-456-789-500'
    expected = 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;LA)'
    assert module._private_acl(actual, sid, expected) is private
    assert not module._private_acl(actual, sid)


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


@pytest.mark.parametrize('previous_success,pending,expected', [(False, False, False), (True, False, True), (True, True, False)])
def test_fast_start_requires_previous_success_and_no_pending_setup(tmp_path, monkeypatch, previous_success, pending, expected):
    from tvhplayer.core import windows_prerequisites
    runtime = Runtime()
    s = supervisor(tmp_path, monkeypatch, runtime)
    s.config_dir.mkdir(parents=True, exist_ok=True)
    if previous_success:
        (s.config_dir / '.tvhplayer-runtime.json').write_text('{}')
    monkeypatch.setattr(windows_prerequisites, 'pending_setup', lambda _: {'stage': 'check_required'} if pending else None)
    checked = []
    runtime.check = lambda: checked.append(runtime.established)
    s._run()
    assert checked == [expected]

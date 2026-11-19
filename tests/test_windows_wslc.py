"""Windows backend safety contracts, using a fake CLI (no WSL setup required)."""
import hashlib
import json
import logging
import subprocess
import threading
import sys
import time
from pathlib import Path

import pytest

from tvhplayer.core.builtin_runtime import windows_backend_enabled
from tvhplayer.core.windows_backend_paths import bind_mount
from tvhplayer.core.windows_wslc import WslcError, WslcRuntimeAdapter
from tvhplayer.core.backend_bundle import TVHEADEND_COMMIT

OWNER = 'a' * 32
NAME = 'tvhplayer-' + OWNER
IMAGE = 'sha256:' + 'b' * 64


class Cli:
    def __init__(self, output=''):
        self.calls = []
        self.output = output
        self.code = 0

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert isinstance(args, list) and not kwargs.get('shell')
        assert kwargs['timeout'] > 0
        return subprocess.CompletedProcess(args, self.code, self.output, '')


@pytest.mark.parametrize('command', ['info', 'inspect', 'run'])
def test_virtualization_failure_opens_setup_from_any_runtime_stage(command):
    from tvhplayer.core.windows_wslc import WslcPrerequisiteError
    cli = Cli('WSL2 is unable to start. Error code: HCS_E_HYPERV_NOT_INSTALLED')
    cli.code = 1
    with pytest.raises(WslcPrerequisiteError) as error:
        WslcRuntimeAdapter('wslc.exe', cli).command(command)
    assert error.value.action == 'repair'
    assert 'Restart Windows' in str(error.value)
    assert 'BIOS/UEFI' in str(error.value)


def test_unrelated_command_error_does_not_offer_windows_repair():
    from tvhplayer.core.windows_wslc import WslcCommandError
    cli = Cli('Access denied')
    cli.code = 1
    with pytest.raises(WslcCommandError):
        WslcRuntimeAdapter('wslc.exe', cli).command('inspect')


def bundle(tmp_path):
    archive = tmp_path / 'tvheadend.tar'
    archive.write_bytes(b'image fixture')
    (tmp_path / 'manifest.json').write_text(json.dumps({
        'schema': 1, 'image': IMAGE, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'tvheadend_commit': TVHEADEND_COMMIT,
    }))


@pytest.mark.parametrize('host', ['relative', r'\\server\share', r'\\?\C:\folder',
                                   r'C:\one,two', 'C:\\bad\nname', r'C:\one\..\two',
                                   r'C:\folder:stream'])
def test_reject_ambiguous_mounts(host):
    with pytest.raises(ValueError):
        bind_mount(host, '/config')


def test_mount_keeps_spaces_and_unicode_as_one_argument():
    assert bind_mount(r'C:\Users\مهدی\My TV', '/recordings') == (
        'type=bind,source=C:\\Users\\مهدی\\My TV,target=/recordings')


def test_windows_release_gate(monkeypatch, tmp_path):
    monkeypatch.setattr('tvhplayer.core.builtin_runtime.windows_backend_dir', lambda: tmp_path)
    monkeypatch.setattr('sys.platform', 'win32')
    monkeypatch.delenv('TVHPLAYER_EXPERIMENTAL_WSLC', raising=False)
    assert not windows_backend_enabled()


def test_complete_windows_package_is_available_before_wsl_setup(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.platform', 'win32')
    monkeypatch.delenv('TVHPLAYER_EXPERIMENTAL_WSLC', raising=False)
    monkeypatch.setattr('tvhplayer.core.builtin_runtime.windows_backend_dir', lambda: tmp_path)
    (tmp_path / 'manifest.json').write_text(json.dumps({'schema': 2, 'architecture': 'amd64', 'tvheadend_commit': TVHEADEND_COMMIT}))
    assert windows_backend_enabled()
    monkeypatch.setenv('TVHPLAYER_EXPERIMENTAL_WSLC', '0')
    assert not windows_backend_enabled()
    monkeypatch.setenv('TVHPLAYER_EXPERIMENTAL_WSLC', '1')
    assert windows_backend_enabled()
    monkeypatch.setattr('sys.platform', 'darwin')
    assert not windows_backend_enabled()


def test_corrupt_archive_never_reaches_runtime(tmp_path):
    bundle(tmp_path)
    (tmp_path / 'tvheadend.tar').write_bytes(b'tampered')
    cli = Cli('Object not found: ' + IMAGE)
    with pytest.raises(WslcError, match='checksum'):
        WslcRuntimeAdapter('wslc.exe', cli).provision(tmp_path)
    assert cli.calls == [['wslc.exe', 'inspect', '--type', 'image', IMAGE]]


def test_offline_provision_uses_immutable_image(tmp_path):
    bundle(tmp_path)
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    assert WslcRuntimeAdapter('wslc.exe', cli).provision(tmp_path) == IMAGE
    assert cli.calls == [['wslc.exe', 'inspect', '--type', 'image', IMAGE]]


def test_matching_recorded_image_skips_inspect(tmp_path, monkeypatch, caplog):
    bundle(tmp_path)
    monkeypatch.setattr('tvhplayer.core.backend_bundle.file_digest',
                        lambda *args, **kwargs: pytest.fail('A trusted image must not hash the archive'))
    (tmp_path / 'tvheadend.tar').unlink()
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    with caplog.at_level(logging.INFO):
        assert runtime.provision(tmp_path, trusted_image=IMAGE) == IMAGE
    assert cli.calls == []
    assert runtime.skipped_image_inspect
    assert runtime.image_state == 'installed'
    assert not runtime.archive_verified
    assert 'skipped image inspect' in caplog.text


def test_different_recorded_image_still_inspects(tmp_path):
    bundle(tmp_path)
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    assert runtime.provision(tmp_path, trusted_image='sha256:' + 'a' * 64) == IMAGE
    assert cli.calls == [['wslc.exe', 'inspect', '--type', 'image', IMAGE]]
    assert not runtime.skipped_image_inspect


@pytest.mark.parametrize('output', [
    f'No such image: {IMAGE}\nError code: WSLC_E_IMAGE_NOT_FOUND\n',
    f'Object not found: {IMAGE}',
    f'Unable to find image "{IMAGE}" locally',
])
def test_image_absent_matches_only_this_image(output):
    from tvhplayer.core.windows_wslc import WslcCommandError, image_absent
    error = WslcCommandError('run', 1, output)
    assert image_absent(error, IMAGE)
    assert not image_absent(error, 'sha256:' + 'a' * 64)
    assert not image_absent(WslcError('bind: Address already in use'), IMAGE)
    assert not image_absent(WslcCommandError('run', 1, 'Object not found: tvhplayer-' + 'a' * 32), IMAGE)


def test_cached_image_inspect_is_one_query_after_the_manifest(tmp_path, monkeypatch, caplog):
    bundle(tmp_path)
    monkeypatch.setattr('tvhplayer.core.backend_bundle.file_digest',
                        lambda *args, **kwargs: pytest.fail('Cached image startup must not hash the offline archive'))
    (tmp_path / 'tvheadend.tar').unlink()
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    runtime.established = True
    with caplog.at_level(logging.INFO):
        assert runtime.provision(tmp_path) == IMAGE
    assert cli.calls == [['wslc.exe', 'inspect', '--type', 'image', IMAGE]]
    assert 'image manifest read in' in caplog.text
    assert 'image inspect hit in' in caplog.text
    assert 'WSLc already checked: True' in caplog.text
    assert runtime.image_state == 'installed'
    assert not runtime.archive_verified


def test_cached_image_does_not_read_unused_archive(tmp_path, monkeypatch):
    bundle(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('Cached image startup must not hash the offline archive')
    monkeypatch.setattr('tvhplayer.core.backend_bundle.file_digest', forbidden)
    (tmp_path / 'tvheadend.tar').unlink()
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    assert runtime.provision(tmp_path) == IMAGE
    assert runtime.image_state == 'installed'
    assert not runtime.archive_verified  # A reused image is not a freshly hashed archive.


def test_first_import_reports_verification_and_import_as_distinct_stages(tmp_path, monkeypatch):
    from tvhplayer.core.windows_prerequisites import setup_checks
    bundle(tmp_path)
    runtime = WslcRuntimeAdapter('wslc.exe', Cli())
    images = iter([False, True])
    monkeypatch.setattr(runtime, 'has_image', lambda image: next(images))
    states = []
    monkeypatch.setattr('tvhplayer.core.windows_wslc.verify_bundle',
                        lambda *args, **kwargs: states.append(runtime.image_state))
    stages = []
    runtime.progress = stages.append
    runtime.setup_checks = setup_checks()
    assert runtime.provision(tmp_path) == IMAGE
    assert states == ['available']
    assert stages == ['Checking the server image…', 'Verifying the server files…',
                      'Importing the server image. This can take a few minutes…']
    assert runtime.archive_verified and runtime.image_state == 'installed'
    assert next(row for row in runtime.setup_checks if row['key'] == 'image')['status'] == 'passed'


def test_old_wsl_version_offers_update_without_starting_server():
    from tvhplayer.core.windows_wslc import WslcPrerequisiteError
    cli = Cli('WSLc version 2.9.2')
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    with pytest.raises(WslcPrerequisiteError) as error:
        runtime.check()
    assert error.value.action == 'update'
    assert cli.calls == [['wslc.exe', 'version']]
    assert next(row for row in runtime.setup_checks if row['key'] == 'version')['status'] == 'failed'
    assert len(cli.calls) == 1


@pytest.mark.parametrize('field,value', [('image', 'latest'), ('tvheadend_commit', 'wrong'), ('schema', 99)])
def test_invalid_manifest_rejected_before_cached_image_lookup(tmp_path, field, value):
    bundle(tmp_path)
    path = tmp_path / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    with pytest.raises(WslcError):
        WslcRuntimeAdapter('wslc.exe', cli).provision(tmp_path)
    assert not cli.calls


def test_offline_load_on_cache_miss(tmp_path):
    bundle(tmp_path)
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    def runner(args, **kwargs):
        result = cli(args, **kwargs)
        if len(cli.calls) == 1:
            result.stdout = 'Object not found: ' + IMAGE
        return result
    WslcRuntimeAdapter('wslc.exe', runner).provision(tmp_path)
    assert cli.calls[1] == ['wslc.exe', 'load', '--input', str(tmp_path / 'tvheadend.tar')]
    assert all('pull' not in call for call in cli.calls)


def test_provision_rejects_unexpected_cached_image_identity(tmp_path):
    bundle(tmp_path)
    cli = Cli(json.dumps([{'Id': 'sha256:' + 'c' * 64, 'Architecture': 'amd64'}]))
    with pytest.raises(WslcError, match='verify'):
        WslcRuntimeAdapter('wslc.exe', cli).provision(tmp_path)


def test_launch_publishes_only_two_loopback_ports_without_credentials():
    from types import SimpleNamespace
    cli = Cli()
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    runtime.config_storage = SimpleNamespace(volume='tvhplayer-config-' + OWNER)
    runtime.launch(IMAGE, NAME, OWNER, r'C:\Config', r'D:\TV recordings', (24111, 24112))
    args = cli.calls[0]
    assert '--dns' not in args
    assert args.count('--publish') == 2
    assert '127.0.0.1:24111:9981/tcp' in args
    assert '127.0.0.1:24112:9982/tcp' in args
    assert args[args.index('--pull') + 1] == 'never'
    assert not any('password' in arg for arg in args)
    assert '--noacl' in args[-1].split()
    assert r'C:\Config' not in str(args)
    assert 'type=volume,source=tvhplayer-config-' + OWNER + ',target=/config' in args
    assert '-c /config/data' in args[-1]


@pytest.mark.parametrize('trace', [None, '', '0', '1', 'yes'])
def test_native_startup_tracing_is_explicit_and_preserves_launch_contract(monkeypatch, trace):
    from types import SimpleNamespace

    if trace is None:
        monkeypatch.delenv('TVHPLAYER_TRACE_STARTUP', raising=False)
    else:
        monkeypatch.setenv('TVHPLAYER_TRACE_STARTUP', trace)
    cli = Cli()
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    runtime.config_storage = SimpleNamespace(volume='tvhplayer-config-' + OWNER)
    runtime.launch(IMAGE, NAME, OWNER, r'C:\Config', r'D:\Recordings', (24111, 24112))
    command = cli.calls[0]
    server_command = command[-1]
    assert ('--trace main' in server_command) == (trace == '1')
    assert (' -d' in server_command) == (trace == '1')
    assert '-c /config/data -B --bindaddr 0.0.0.0 --noacl' in server_command
    assert command[command.index('--label') + 1] == 'tvhplayer.owner=' + OWNER
    assert command.count('--publish') == 2
    assert not any('password' in value for value in command)


def test_tuner_address_save_is_reported_only_when_the_settings_change():
    from types import SimpleNamespace
    runtime = WslcRuntimeAdapter('wslc.exe', Cli())
    saved = []
    runtime.config_storage = SimpleNamespace(update_server_settings=saved.append)
    stages = []
    runtime.progress = stages.append
    transport = SimpleNamespace(config=lambda: {'local_ip': '192.0.2.10', 'local_port': 30000})
    runtime._server_settings = {'local_ip': '192.0.2.10', 'local_port': 30000}
    runtime.configure_hdhomerun(transport)
    assert stages == [] and saved == []
    runtime._server_settings = {'local_ip': '', 'local_port': 0}
    runtime.configure_hdhomerun(transport)
    assert stages == ['Saving tuner addresses…']
    assert saved == [{'local_ip': '192.0.2.10', 'local_port': 30000}]


def test_startup_trace_log_tail_is_bounded(monkeypatch):
    cli = Cli(json.dumps(state()))

    def runner(args, **kwargs):
        result = cli(args, **kwargs)
        if args[1] == 'logs':
            result.stdout = 'main: startup mpegts_init: 1935 ms\n'
        return result

    runtime = WslcRuntimeAdapter('wslc.exe', runner)
    assert 'mpegts_init' in runtime.logs_owned(NAME, OWNER, tail=1000)
    logs = next(call for call in cli.calls if call[1] == 'logs')
    assert logs[logs.index('--tail') + 1] == '1000'
    assert logs[-1] == NAME
    with pytest.raises(WslcError, match='out of range'):
        runtime.logs_owned(NAME, OWNER, tail=1001)
    with pytest.raises(WslcError, match='out of range'):
        runtime.logs_owned(NAME, OWNER, tail=0)


def test_container_healthcheck_and_entrypoint_use_live_settings_path():
    root = Path(__file__).resolve().parents[1]
    containerfile = (root / 'windows' / 'backend' / 'Containerfile').read_text(encoding='utf-8')
    entrypoint = (root / 'windows' / 'backend' / 'entrypoint.sh').read_text(encoding='utf-8')
    assert 'test -s /config/data/superuser' in containerfile
    assert 'test -s /config/data/superuser' in entrypoint
    assert 'test -s /config/superuser' not in containerfile
    assert 'test -s /config/superuser' not in entrypoint
    assert '-c /config/data' in entrypoint


def test_launch_publishes_hdhomerun_udp_ports_on_one_lan_address():
    from types import SimpleNamespace
    cli = Cli()
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    runtime.config_storage = SimpleNamespace(volume='tvhplayer-config-' + OWNER)
    udp = [('192.168.8.211', 30000), ('192.168.8.211', 30001)]
    runtime.launch(IMAGE, NAME, OWNER, r'C:\Config', r'D:\TV recordings', (24111, 24112), udp)
    args = cli.calls[0]
    assert args.count('--publish') == 4
    assert '127.0.0.1:24111:9981/tcp' in args
    assert '127.0.0.1:24112:9982/tcp' in args
    assert '192.168.8.211:30000:30000/udp' in args
    assert '192.168.8.211:30001:30001/udp' in args
    assert '0.0.0.0:30000:30000/udp' not in args


def state(udp=()):
    ports = {
        '9981/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '24111'}],
        '9982/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '24112'}],
    }
    for host_ip, port in udp:
        ports[f'{port}/udp'] = [{'HostIp': host_ip, 'HostPort': str(port)}]
    return {'Name': '/' + NAME, 'Config': {'Labels': {'tvhplayer.owner': OWNER}},
            'State': {'Running': True}, 'NetworkSettings': {'Ports': ports}}


def test_foreign_container_is_never_stopped():
    data = state()
    data['Config']['Labels']['tvhplayer.owner'] = 'someone-else'
    cli = Cli(json.dumps(data))
    with pytest.raises(WslcError, match='ownership'):
        WslcRuntimeAdapter('wslc.exe', cli).stop_owned(NAME, OWNER)
    assert len(cli.calls) == 1 and cli.calls[0][1] == 'inspect'


@pytest.mark.parametrize('binding', ['0.0.0.0', '::', '192.168.1.1'])
def test_readiness_rejects_non_loopback_publication(binding):
    data = state()
    data['NetworkSettings']['Ports']['9981/tcp'][0]['HostIp'] = binding
    with pytest.raises(WslcError, match='loopback'):
        WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(data))).verify_running(NAME, OWNER, (24111, 24112))


def test_verified_owned_backend_can_be_stopped():
    cli = Cli(json.dumps(state()))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    runtime.verify_running(NAME, OWNER, (24111, 24112))
    runtime.stop_owned(NAME, OWNER)
    assert cli.calls[-2:] == [['wslc.exe', 'stop', '--time', '5', NAME], ['wslc.exe', 'remove', NAME]]


def test_stop_owned_ignores_remove_when_container_already_gone():
    # WSLc may delete on stop, or cleanup races; "not found" must not fail shutdown.
    responses = [
        json.dumps(state()),
        '',
        f"Container '{NAME}' not found.\nError code: WSLC_E_CONTAINER_NOT_FOUND\n",
    ]
    codes = [0, 0, 1]
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        output = responses.pop(0)
        code = codes.pop(0)
        return subprocess.CompletedProcess(args, code, output, output if code else '')

    assert WslcRuntimeAdapter('wslc.exe', runner).stop_owned(NAME, OWNER) is True
    assert calls[-1] == ['wslc.exe', 'remove', NAME]


def test_inspect_owned_recognizes_wslc_container_not_found():
    cli = Cli(f"Container '{NAME}' not found.\nError code: WSLC_E_CONTAINER_NOT_FOUND\n")
    cli.code = 1
    assert WslcRuntimeAdapter('wslc.exe', cli).inspect_owned(NAME, OWNER, missing_ok=True) is None


def test_wslc_3_top_level_ports():
    data = state()
    data['Ports'] = data['NetworkSettings'].pop('Ports')
    WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(data))).verify_running(NAME, OWNER, (24111, 24112))


def test_readiness_accepts_the_hdhomerun_udp_range():
    udp = [('192.168.8.211', 30000), ('192.168.8.211', 30001)]
    WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(state(udp)))).verify_running(
        NAME, OWNER, (24111, 24112), udp)


def test_readiness_rejects_a_missing_hdhomerun_udp_port():
    with pytest.raises(WslcError, match='port publication'):
        WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(state()))).verify_running(
            NAME, OWNER, (24111, 24112), [('192.168.8.211', 30000)])


@pytest.mark.parametrize('host_ip', ['0.0.0.0', '::', '127.0.0.1'])
def test_readiness_rejects_wildcard_or_loopback_udp_publication(host_ip):
    udp = [(host_ip, 30000)]
    data = state(udp)
    with pytest.raises(WslcError, match='LAN address'):
        WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(data))).verify_running(
            NAME, OWNER, (24111, 24112), udp)


def test_readiness_rejects_udp_published_on_another_host():
    udp = [('192.168.8.211', 30000)]
    data = state([('192.168.8.212', 30000)])
    with pytest.raises(WslcError, match='stream port'):
        WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(data))).verify_running(
            NAME, OWNER, (24111, 24112), udp)


def test_cleanup_runs_despite_cancellation():
    data = state()
    data['State']['Running'] = False
    cli = Cli(json.dumps(data))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    runtime.cancel = threading.Event()
    runtime.cancel.set()
    runtime.stop_owned(NAME, OWNER)
    assert cli.calls[-1] == ['wslc.exe', 'remove', NAME]
    assert all(call[1] != 'stop' for call in cli.calls)


def test_cancellable_cli_process_does_not_wait_for_command_timeout():
    runtime = WslcRuntimeAdapter(sys.executable)
    runtime.cancel = threading.Event()
    timer = threading.Timer(.2, runtime.cancel.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(WslcError, match='cancelled'):
            runtime.command('-c', 'import time; time.sleep(30)', timeout=10)
    finally:
        timer.cancel()
    assert time.monotonic() - start < 3


def test_windows_playlist_uses_guest_ffmpeg(monkeypatch):
    from tvhplayer.core.playlist_sync import ffmpeg_for_server
    monkeypatch.setattr('sys.platform', 'win32')
    def forbidden(*args):
        pytest.fail('Windows host FFmpeg must never be used in the Linux container')
    assert ffmpeg_for_server({'builtin': True}, which=forbidden, starter=forbidden) == '/usr/bin/ffmpeg'


def test_old_ffmpeg_mux_commands_migrate_idempotently():
    from tvhplayer.core.playlist import _quote, tvh_split
    from tvhplayer.core.playlist_sync import guest_ffmpeg_changes
    rows = [{'uuid': 'one', 'iptv_url': 'pipe://' + _quote(r'C:\Program Files\TVHplayer\ffmpeg.exe') + ' -i https://example.test/live -c copy -f mpegts pipe:1'},
            {'uuid': 'two', 'iptv_url': 'pipe:///usr/local/bin/tvhplayer-ffmpeg -i https://example.test/live -c copy -f mpegts pipe:1'},
            {'uuid': 'custom', 'iptv_url': 'pipe:///bin/sh -c custom-command'}]
    changes = guest_ffmpeg_changes(rows)
    assert {row['uuid'] for row in changes} == {'one', 'two'}
    assert all(tvh_split(row['iptv_url'][7:])[0] == '/usr/bin/ffmpeg' for row in changes)
    assert guest_ffmpeg_changes(changes) == []


def test_container_stderr_logs_are_not_discarded():
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, '', 'backend log from stderr')
    assert WslcRuntimeAdapter('wslc.exe', runner).command('logs', NAME) == 'backend log from stderr'


@pytest.mark.parametrize('operation', ['stop', 'shut_down'])
def test_cancel_before_provision_completes_never_launches(tmp_path, monkeypatch, operation):
    pytest.importorskip('PyQt6')
    from PyQt6.QtCore import QCoreApplication
    from tvhplayer import wslc_builtin_supervisor as module
    app = QCoreApplication.instance() or QCoreApplication([])
    reached = threading.Event()
    release = threading.Event()
    class Runtime:
        def check(self):
            pass
        def provision(self, folder, trusted_image=None):
            reached.set()
            release.wait(5)
            return IMAGE
        def launch(self, *args, **kwargs):
            pytest.fail('Cancelled setup must not launch a container')
    monkeypatch.setattr(module, 'protect_config', lambda folder: folder.mkdir(parents=True, exist_ok=True))
    supervisor = module.WslcBuiltinSupervisor(tmp_path / 'config', tmp_path, runtime=Runtime())
    supervisor.start()
    assert reached.wait(5)
    getattr(supervisor, operation)()
    release.set()
    supervisor._thread.join(5)
    app.processEvents()
    assert supervisor.status == 'stopped'
    assert supervisor._thread is None


def test_successful_runtime_check_skips_windows_diagnostics(monkeypatch):
    from tvhplayer.core import windows_prerequisites
    monkeypatch.setattr(windows_prerequisites, 'probe_windows', lambda: pytest.fail('CIM on healthy start'))
    runtime = WslcRuntimeAdapter('wslc.exe')
    runtime.established = True
    calls = []
    runtime.command = lambda command: calls.append(command) or 'WSLc version 3.0.5'
    for _ in range(2):
        runtime.check()
    assert calls == ['version', 'info', 'version', 'info']
    assert runtime._prerequisite_state == {}


def test_failed_runtime_check_runs_windows_diagnostics(monkeypatch):
    from tvhplayer.core import windows_prerequisites, windows_wslc
    monkeypatch.setattr(windows_wslc.sys, 'platform', 'win32')
    calls = []
    monkeypatch.setattr(windows_prerequisites, 'probe_windows', lambda: calls.append('probe') or {'feature': 2})
    runtime = WslcRuntimeAdapter('wslc.exe')
    runtime.established = True
    def command(name):
        if name == 'version': return '3.0.5'
        raise WslcError('unavailable')
    runtime.command = command
    with pytest.raises(windows_wslc.WslcPrerequisiteError) as error:
        runtime.check()
    assert error.value.action == 'repair'
    assert calls == ['probe']


@pytest.mark.parametrize('fault', [None, 'owner', 'stopped', 'ports'])
def test_monitor_inspects_once_and_rejects_bad_state(fault):
    data = state()
    if fault == 'owner': data['Config']['Labels']['tvhplayer.owner'] = 'other'
    if fault == 'stopped': data['State']['Running'] = False
    if fault == 'ports': data['NetworkSettings']['Ports'] = {}
    cli = Cli(json.dumps(data))
    runtime = WslcRuntimeAdapter('wslc.exe', cli)
    if fault:
        with pytest.raises(WslcError):
            runtime.monitor_owned(NAME, OWNER, (24111, 24112))
        assert [c[1] for c in cli.calls] == ['inspect']
    else:
        runtime.monitor_owned(NAME, OWNER, (24111, 24112))
        assert [c[1] for c in cli.calls] == ['inspect', 'logs']


def test_cancelled_runtime_check_does_not_probe(monkeypatch):
    from tvhplayer.core import windows_prerequisites
    monkeypatch.setattr(windows_prerequisites, 'probe_windows', lambda: pytest.fail('probe after cancellation'))
    runtime = WslcRuntimeAdapter('wslc.exe')
    runtime.established = True
    runtime.cancel = threading.Event()
    runtime.cancel.set()
    def command(*args): raise WslcError('cancelled')
    runtime.command = command
    with pytest.raises(WslcError, match='cancelled'):
        runtime.check()


@pytest.mark.parametrize('error', [subprocess.TimeoutExpired('info', 20), OSError('missing')])
def test_runtime_check_failure_remains_bounded(error):
    def runner(*args, **kwargs): raise error
    with pytest.raises(WslcError):
        WslcRuntimeAdapter('wslc.exe', runner).check()

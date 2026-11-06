"""Windows backend safety contracts, using a fake CLI (no WSL setup required)."""
import hashlib
import json
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


def test_cached_image_does_not_read_unused_archive(tmp_path, monkeypatch):
    bundle(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('Cached image startup must not hash the offline archive')
    monkeypatch.setattr('tvhplayer.core.backend_bundle.file_digest', forbidden)
    (tmp_path / 'tvheadend.tar').unlink()
    cli = Cli(json.dumps([{'Id': IMAGE, 'Architecture': 'amd64'}]))
    assert WslcRuntimeAdapter('wslc.exe', cli).provision(tmp_path) == IMAGE
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
    assert args.count('--publish') == 2
    assert '127.0.0.1:24111:9981/tcp' in args
    assert '127.0.0.1:24112:9982/tcp' in args
    assert args[args.index('--pull') + 1] == 'never'
    assert not any('password' in arg or 'noacl' in arg for arg in args)
    assert r'C:\Config' not in str(args)
    assert 'type=volume,source=tvhplayer-config-' + OWNER + ',target=/config' in args
    assert '-c /config/data' in args[-1]


def test_container_healthcheck_and_entrypoint_use_live_settings_path():
    root = Path(__file__).resolve().parents[1]
    containerfile = (root / 'windows' / 'backend' / 'Containerfile').read_text(encoding='utf-8')
    entrypoint = (root / 'windows' / 'backend' / 'entrypoint.sh').read_text(encoding='utf-8')
    assert 'test -s /config/data/superuser' in containerfile
    assert 'test -s /config/data/superuser' in entrypoint
    assert 'test -s /config/superuser' not in containerfile
    assert 'test -s /config/superuser' not in entrypoint
    assert '-c /config/data' in entrypoint


def state():
    return {'Name': '/' + NAME, 'Config': {'Labels': {'tvhplayer.owner': OWNER}},
            'State': {'Running': True}, 'NetworkSettings': {'Ports': {
                '9981/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '24111'}],
                '9982/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '24112'}]}}}


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


def test_wslc_3_top_level_ports():
    data = state()
    data['Ports'] = data['NetworkSettings'].pop('Ports')
    WslcRuntimeAdapter('wslc.exe', Cli(json.dumps(data))).verify_running(NAME, OWNER, (24111, 24112))


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


def test_cancel_before_provision_completes_never_launches(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6')
    from PyQt6.QtCore import QCoreApplication
    from tvhplayer import wslc_builtin_supervisor as module
    app = QCoreApplication.instance() or QCoreApplication([])
    reached = threading.Event()
    release = threading.Event()
    class Runtime:
        def check(self):
            pass
        def provision(self, folder):
            reached.set()
            release.wait(5)
            return IMAGE
        def launch(self, *args):
            pytest.fail('Cancelled setup must not launch a container')
    monkeypatch.setattr(module, 'protect_config', lambda folder: folder.mkdir(parents=True, exist_ok=True))
    supervisor = module.WslcBuiltinSupervisor(tmp_path / 'config', tmp_path, runtime=Runtime())
    supervisor.start()
    assert reached.wait(5)
    supervisor.stop()
    release.set()
    supervisor._thread.join(5)
    app.processEvents()
    assert supervisor.status == 'stopped'
    assert supervisor._thread is None

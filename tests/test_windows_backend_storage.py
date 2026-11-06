import json
from pathlib import Path
import tarfile
import threading

import pytest

from tvhplayer.core.windows_backend_storage import NativeConfigStorage
from tvhplayer.core.windows_wslc import WslcError

IMAGE = 'sha256:' + 'b' * 64


@pytest.fixture(autouse=True)
def fake_mount(monkeypatch):
    monkeypatch.setattr('tvhplayer.core.windows_backend_storage.bind_mount',
                        lambda host, guest: f'type=bind,source={host},target={guest}')


class Runtime:
    """Model the volume and helper filesystem at the CLI boundary."""
    def __init__(self, config, native):
        self.config, self.native = config, native
        self.cancel = threading.Event()
        self.volumes = {}
        self.calls = []
        self.fail_import = False
        self.fail_backup = False

    def stop_owned(self, name, owner):
        assert name == 'tvhplayer-' + owner

    def command(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ('volume', 'inspect'):
            item = self.volumes.get(args[2])
            return json.dumps([item]) if item else f"Volume not found: '{args[2]}'\n[]"
        if args[:2] == ('volume', 'create'):
            label = args[args.index('--label') + 1].split('=', 1)[1]
            self.volumes[args[-1]] = {'Name': args[-1], 'Labels': {'tvhplayer.config': label}}
            return args[-1]
        if args[0] == 'run':
            script = args[-1]
            assert '--pull' in args and 'never' in args
            if 'mktemp' in script:
                if self.fail_import:
                    raise WslcError('Interrupted import')
                if not (self.native / 'superuser').exists():
                    self.native.mkdir(exist_ok=True)
                    with tarfile.open(self.config / '.tvhplayer-storage/import.tar') as archive:
                        archive.extractall(self.native, filter='data')
            elif 'tar -czf' in script:
                if self.fail_backup:
                    raise WslcError('Interrupted backup')
                with tarfile.open(self.config / '.tvhplayer-storage/backup.tmp', 'w:gz') as archive:
                    archive.add(self.native, arcname='.')
            else:
                raise AssertionError(script)
            return ''
        raise AssertionError(args)


def storage(tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'superuser').write_text('{"username":"test","password":"private"}')
    (config / 'channels').mkdir()
    (config / 'channels/one').write_text('initial channel')
    (config / 'wslc-owner.json').write_text('host bookkeeping')
    native = tmp_path / 'native'
    runtime = Runtime(config, native)
    return NativeConfigStorage(runtime, IMAGE, config), runtime


def test_migration_keeps_original_and_restart_uses_native_settings(tmp_path, monkeypatch):
    s, runtime = storage(tmp_path)
    volume = s.prepare()
    assert (runtime.native / 'channels/one').read_text() == 'initial channel'
    assert (s.config / 'channels/one').read_text() == 'initial channel'
    assert not (runtime.native / 'wslc-owner.json').exists()
    assert not (runtime.native / '.tvhplayer-storage').exists()
    (runtime.native / 'channels/one').write_text('edited in Linux')
    runtime.calls.clear()
    monkeypatch.setattr(s, '_make_seed', lambda: pytest.fail('Must not scan Windows files again'))
    assert s.prepare() == volume
    assert runtime.calls == [('volume', 'inspect', volume)]
    assert (runtime.native / 'channels/one').read_text() == 'edited in Linux'


def test_interrupted_migration_is_resumable(tmp_path):
    s, runtime = storage(tmp_path)
    runtime.fail_import = True
    with pytest.raises(WslcError, match='Interrupted'):
        s.prepare()
    state = json.loads(s.state_path.read_text())
    assert state['ready'] is False
    runtime.fail_import = False
    assert s.prepare() == state['volume']
    assert json.loads(s.state_path.read_text())['ready'] is True


def test_backups_use_live_native_data_and_retain_previous(tmp_path):
    s, runtime = storage(tmp_path)
    s.prepare()
    (runtime.native / 'channels/one').write_text('first edit')
    s.backup()
    first = s.latest.read_bytes()
    (runtime.native / 'channels/one').write_text('second edit')
    s.backup()
    assert s.previous.read_bytes() == first
    with tarfile.open(s.latest) as archive:
        assert archive.extractfile('./channels/one').read() == b'second edit'
    upgrade = s.backup(upgrade=True)
    assert upgrade.exists() and upgrade != s.latest
    runtime.fail_backup = True
    current = s.latest.read_bytes()
    with pytest.raises(WslcError):
        s.backup()
    assert s.latest.read_bytes() == current


def test_shutdown_backup_ignores_startup_cancellation(tmp_path):
    s, runtime = storage(tmp_path)
    s.prepare()
    runtime.cancel.set()
    original = runtime.command
    def checked(*args, **kwargs):
        assert kwargs.get('cancellable') is False
        return original(*args, **kwargs)
    runtime.command = checked
    assert s.backup().exists()


def test_missing_volume_restores_latest_backup_instead_of_stale_windows_tree(tmp_path):
    s, runtime = storage(tmp_path)
    s.prepare()
    (runtime.native / 'channels/one').write_text('latest edit')
    s.backup()
    runtime.volumes.clear()
    (runtime.native / 'superuser').unlink()
    (runtime.native / 'channels/one').unlink()
    s.prepare()
    assert (runtime.native / 'channels/one').read_text() == 'latest edit'


def test_missing_volume_without_backup_does_not_silently_reset(tmp_path):
    s, runtime = storage(tmp_path)
    s.prepare()
    runtime.volumes.clear()
    with pytest.raises(WslcError, match='no current backup'):
        s.prepare()


def test_interrupted_restore_keeps_using_current_backup_on_retry(tmp_path):
    s, runtime = storage(tmp_path)
    s.prepare()
    (runtime.native / 'channels/one').write_text('latest edit')
    s.backup()
    runtime.volumes.clear()
    (runtime.native / 'superuser').unlink()
    (runtime.native / 'channels/one').unlink()
    runtime.fail_import = True
    with pytest.raises(WslcError, match='Interrupted'):
        s.prepare()
    assert json.loads(s.state_path.read_text())['ready'] is False
    runtime.fail_import = False
    s.prepare()
    assert (runtime.native / 'channels/one').read_text() == 'latest edit'


def test_foreign_volume_is_never_used_or_changed(tmp_path):
    s, runtime = storage(tmp_path)
    volume = s.prepare()
    runtime.volumes[volume]['Labels']['tvhplayer.config'] = 'foreign'
    runtime.calls.clear()
    with pytest.raises(WslcError, match='ownership'):
        s.prepare()
    assert runtime.calls == [('volume', 'inspect', volume)]


def test_cancelled_migration_preserves_original_files(tmp_path):
    s, runtime = storage(tmp_path)
    runtime.cancel.set()
    with pytest.raises(WslcError, match='cancelled'):
        s.prepare()
    assert (s.config / 'channels/one').read_text() == 'initial channel'
    assert not runtime.calls

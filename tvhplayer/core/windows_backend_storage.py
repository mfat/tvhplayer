"""Persistent Linux settings with a recoverable Windows migration and backups."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import uuid

from .windows_backend_paths import bind_mount
from .windows_wslc import WslcError


def _write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


class NativeConfigStorage:
    def __init__(self, runtime, image, config):
        self.runtime, self.image = runtime, image
        self.config = Path(config)
        self.folder = self.config / '.tvhplayer-storage'
        self.state_path = self.folder / 'state.json'
        self.helper_path = self.folder / 'helper.json'
        self.latest = self.folder / 'latest.tar.gz'
        self.previous = self.folder / 'previous.tar.gz'
        self.volume = None
        self.owner = None

    def _cancelled(self):
        if self.runtime.cancel is not None and self.runtime.cancel.is_set():
            raise WslcError('Backend operation cancelled.')

    def _volume_exists(self, *, cancellable=True):
        missing = (f'Volume not found: {self.volume}', f"Volume not found: '{self.volume}'",
                   f'Object not found: {self.volume}')
        try:
            output = self.runtime.command('volume', 'inspect', self.volume, cancellable=cancellable)
        except WslcError as exc:
            if getattr(exc, 'output', '').strip() in missing:
                return False
            raise
        if output.strip().splitlines() and output.strip().splitlines()[0] in missing:
            return False
        try:
            data = json.loads(output)
            if isinstance(data, list):
                if not data:
                    return False
                if len(data) != 1:
                    raise ValueError('Ambiguous volume metadata')
                data = data[0]
            if data['Name'] != self.volume or data['Labels']['tvhplayer.config'] != self.owner:
                raise ValueError('Volume ownership mismatch')
        except (ValueError, KeyError, TypeError) as exc:
            raise WslcError('Cannot verify the Linux settings volume ownership.') from exc
        return True

    def _recover_helper(self):
        if self.helper_path.exists():
            previous = json.loads(self.helper_path.read_text(encoding='utf-8'))
            self.runtime.stop_owned(previous['name'], previous['owner'])
            self.helper_path.unlink()

    def _helper(self, script, *, timeout=20, cancellable=True):
        self._recover_helper()
        owner = uuid.uuid4().hex
        name = 'tvhplayer-' + owner
        _write_json(self.helper_path, {'name': name, 'owner': owner})
        try:
            self.runtime.command(
                'run', '--rm', '--pull', 'never', '--name', name,
                '--label', f'tvhplayer.owner={owner}', '--network', 'none',
                '--mount', f'type=volume,source={self.volume},target=/native',
                '--mount', bind_mount(str(self.config), '/config'),
                '--entrypoint', '/bin/sh', self.image, '-c', script,
                timeout=timeout, cancellable=cancellable,
            )
        finally:
            self.runtime.stop_owned(name, owner)
            self.helper_path.unlink(missing_ok=True)

    def _make_seed(self):
        seed = self.folder / 'seed.tar'
        if seed.exists():
            return seed
        temporary = self.folder / 'seed.tmp'
        try:
            with tarfile.open(temporary, 'w') as archive:
                for path in self.config.rglob('*'):
                    self._cancelled()
                    relative = path.relative_to(self.config)
                    if relative.parts[0] == '.tvhplayer-storage' or relative.name in (
                        'wslc-owner.json', '.tvhplayer-runtime.json',
                    ):
                        continue
                    if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(self.config.resolve()):
                        raise WslcError('Linked files are unsupported in server settings migration.')
                    if path.is_file():
                        archive.add(path, arcname=relative.as_posix(), recursive=False)
            self._check_snapshot(temporary)
            os.replace(temporary, seed)
        finally:
            temporary.unlink(missing_ok=True)
        return seed

    @staticmethod
    def _check_snapshot(path):
        has_superuser = False
        with tarfile.open(path, 'r:*') as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if name.is_absolute() or '..' in name.parts or not (member.isfile() or member.isdir()):
                    raise WslcError('Unsafe entry in server settings backup.')
                if name == PurePosixPath('superuser') and member.isfile() and member.size:
                    has_superuser = True
        if not has_superuser:
            raise WslcError('Server settings backup is missing its credentials.')

    def prepare(self):
        self._cancelled()
        self.folder.mkdir(exist_ok=True)
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
        else:
            owner = uuid.uuid4().hex
            state = {'schema': 1, 'owner': owner, 'volume': 'tvhplayer-config-' + owner, 'ready': False}
            _write_json(self.state_path, state)
        if (state.get('schema') != 1 or not re.fullmatch(r'[0-9a-f]{32}', state.get('owner', ''))
                or state.get('volume') != 'tvhplayer-config-' + state['owner']
                or not isinstance(state.get('ready'), bool)):
            raise WslcError('Invalid Linux settings storage record.')
        self.volume, self.owner = state['volume'], state['owner']
        self._recover_helper()
        exists = self._volume_exists()
        if state['ready'] and exists:
            return self.volume
        if state['ready'] or state.get('restoring'):
            # Never silently replace a lost volume with the stale Windows tree.
            snapshot = next((p for p in (self.latest, self.previous) if p.exists()), None)
            if snapshot is None:
                raise WslcError('Linux server settings volume is missing and no current backup is available. '
                                'The original Windows settings are preserved; restore a backup before continuing.')
            # Record an unfinished restore before creating a replacement volume.
            # Otherwise a cancelled restore could look like a ready empty volume.
            state['ready'], state['restoring'] = False, True
            _write_json(self.state_path, state)
        else:
            snapshot = self._make_seed()
        self._check_snapshot(snapshot)
        transfer = self.folder / 'import.tar'
        shutil.copyfile(snapshot, transfer)
        if not exists:
            self.runtime.command('volume', 'create', '--label', f'tvhplayer.config={self.owner}', self.volume)
        if not self._volume_exists():
            raise WslcError('Could not create the Linux settings volume.')
        self._helper(
            'set -eu; umask 077; '
            'if [ ! -f /native/data/.tvhplayer-native-ready ]; then '
            'test ! -e /native/data; stage=$(mktemp -d /native/import.XXXXXX); '
            'tar --no-same-owner --no-same-permissions -xf /config/.tvhplayer-storage/import.tar -C "$stage"; '
            'test -s "$stage/superuser"; touch "$stage/.tvhplayer-native-ready"; '
            'mv "$stage" /native/data; fi; test -s /native/data/superuser',
            timeout=120,
        )
        state['ready'] = True
        state.pop('restoring', None)
        _write_json(self.state_path, state)
        transfer.unlink(missing_ok=True)
        logging.getLogger(__name__).info('Server settings migrated to persistent Linux storage')
        return self.volume

    def backup(self, *, upgrade=False):
        if not self.volume or not self._volume_exists(cancellable=False):
            raise WslcError('The Linux settings volume is unavailable for backup.')
        temporary = self.folder / 'backup.tmp'
        self._helper(
            'set -eu; umask 077; test -s /native/data/superuser; '
            'tar -czf /config/.tvhplayer-storage/backup.tmp -C /native/data .',
            cancellable=False,
        )
        self._check_snapshot(temporary)
        if upgrade:
            destination = self.folder / ('before-upgrade-' + uuid.uuid4().hex + '.tar.gz')
        else:
            destination = self.latest
            if destination.exists():
                os.replace(destination, self.previous)
        os.replace(temporary, destination)
        return destination

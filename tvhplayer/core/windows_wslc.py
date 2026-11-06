"""Bounded, shell-free WSLc CLI adapter. Never pulls an image or changes WSL settings."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .windows_backend_paths import bind_mount
from .backend_bundle import read_manifest, verify_bundle


class WslcError(RuntimeError):
    pass


class WslcPrerequisiteError(WslcError):
    def __init__(self, message, action='install'):
        super().__init__(message)
        self.action = action


def find_wslc():
    # An installer may update the system PATH after this app was launched.
    # Search the official location too so "Check again" works without relaunch.
    for variable in ('ProgramW6432', 'ProgramFiles'):
        base = os.environ.get(variable)
        if base and (Path(base) / 'WSL/wslc.exe').is_file():
            return str(Path(base) / 'WSL/wslc.exe')
    return shutil.which('wslc.exe')


class WslcCommandError(WslcError):
    def __init__(self, command, code, output):
        self.code, self.output = code, output
        super().__init__(f'WSL container {command} failed: {output[-2000:]}')


def port_conflict(error):
    message = str(error).lower()
    return any(text in message for text in ('address already in use', 'only one usage of each socket',
                                             'port is already allocated', 'port is already in use'))


class WslcRuntimeAdapter:
    def __init__(self, executable=None, runner=None):
        self.executable = executable or find_wslc()
        self.runner = runner
        self.cancel = None

    def command(self, *args, timeout=20, cancellable=True):
        if not self.executable:
            raise WslcPrerequisiteError('WSL Containers is missing. Install or update WSL to 2.9.3 or newer. Remote servers remain available.')
        try:
            argv = [self.executable, *map(str, args)]
            options = dict(encoding='utf-8', errors='replace',
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if self.runner is not None:
                result = self.runner(argv, capture_output=True, timeout=timeout, **options)
            else:
                if cancellable and self.cancel is not None and self.cancel.is_set():
                    raise WslcError('Backend operation cancelled.')
                with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options) as process:
                    deadline = time.monotonic() + timeout
                    while True:
                        cancelled = cancellable and self.cancel is not None and self.cancel.is_set()
                        if cancelled or time.monotonic() >= deadline:
                            process.kill()
                            process.communicate()
                            raise WslcError('Backend operation cancelled.' if cancelled else f'WSL container {args[0]} timed out.')
                        try:
                            stdout, stderr = process.communicate(timeout=.2)
                            result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
                            break
                        except subprocess.TimeoutExpired:
                            continue
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WslcError(f'WSL container command failed: {args[0]}: {exc}') from exc
        if result.returncode:
            raise WslcCommandError(args[0], result.returncode, result.stderr or result.stdout)
        # WSLc preserves a container's stderr stream for `logs`.
        return (result.stdout + '\n' + result.stderr).strip() if args[0] == 'logs' else result.stdout.strip()

    def check(self):
        if self.executable is None:
            self.executable = find_wslc()
        version = self.command('version')
        match = re.search(r'(\d+)\.(\d+)\.(\d+)', version)
        if not match or tuple(map(int, match.groups())) < (2, 9, 3):
            raise WslcPrerequisiteError('WSL 2.9.3 or newer is required. Update WSL and restart TVHplayer.', 'update')
        try:
            self.command('info')
        except WslcError as exc:
            raise WslcPrerequisiteError(f'WSL Containers could not start. Virtualization may be disabled, or a Windows restart may be needed.\n{exc}', 'repair') from exc

    def provision(self, directory):
        directory = Path(directory)
        started = time.monotonic()
        try:
            manifest = read_manifest(directory)
            image = manifest['image']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise WslcError(f'Install the matching offline backend bundle: {exc}') from exc
        # WSLc checks the immutable imported image identity and architecture.
        # The archive is only needed (and hashed) when that image is absent.
        if not self.has_image(image):
            try:
                verify_bundle(directory, cancel=self.cancel)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise WslcError(f'Install the matching offline backend bundle: {exc}') from exc
            logging.getLogger(__name__).info('Offline backend archive verified in %.1fs', time.monotonic() - started)
            loading = time.monotonic()
            self.command('load', '--input', directory / 'tvheadend.tar', timeout=300)
            logging.getLogger(__name__).info('Offline backend image imported in %.1fs', time.monotonic() - loading)
            if not self.has_image(image):
                raise WslcError('The offline archive did not provide the required backend image.')
        else:
            logging.getLogger(__name__).info('Reused offline backend image in %.1fs', time.monotonic() - started)
        return image

    def has_image(self, image):
        try:
            output = self.command('inspect', '--type', 'image', image)
        except WslcCommandError as exc:
            if exc.output.strip() == f'Object not found: {image}':
                return False
            raise
        # WSLc 3.x reports missing objects with exit status zero.
        if output.strip() == f'Object not found: {image}':
            return False
        try:
            data = json.loads(output)
            if isinstance(data, list):
                if not data:
                    return False
                if len(data) != 1:
                    raise ValueError('Ambiguous image metadata')
                data = data[0]
            if data['Id'] != image or data['Architecture'] != 'amd64':
                raise ValueError('Unexpected image identity or architecture')
        except (ValueError, KeyError, TypeError) as exc:
            raise WslcError('Cannot verify the required x86-64 backend image.') from exc
        return True

    def launch(self, image, name, owner, config, recordings, ports):
        args = ['run', '--detach', '--pull', 'never', '--name', name,
                '--label', f'tvhplayer.owner={owner}', '--stop-timeout', '5']
        for host, guest in zip(ports, (9981, 9982)):
            args += ['--publish', f'127.0.0.1:{int(host)}:{guest}/tcp']
        for host, guest in ((config, '/config'), (recordings, '/recordings')):
            args += ['--mount', bind_mount(str(host), guest)]
        self.command(*args, image, timeout=60)

    def inspect_owned(self, name, owner, cancellable=True, missing_ok=False):
        if not re.fullmatch(r'[0-9a-f]{32}', owner) or name != 'tvhplayer-' + owner:
            raise WslcError('Invalid TVHplayer container identity.')
        try:
            try:
                output = self.command('inspect', '--type', 'container', name,
                                      timeout=5, cancellable=cancellable)
            except WslcCommandError as exc:
                if missing_ok and exc.output.strip() == f'Object not found: {name}':
                    return None
                raise
            if missing_ok and output.strip() == f'Object not found: {name}':
                return None
            data = json.loads(output)
            if isinstance(data, list):
                data = data[0]
            if data['Name'].lstrip('/') != name or data['Config']['Labels']['tvhplayer.owner'] != owner:
                raise ValueError('Container ownership mismatch')
            return data
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise WslcError('Cannot verify TVHplayer container ownership.') from exc

    def verify_running(self, name, owner, ports):
        data = self.inspect_owned(name, owner)
        if not data['State']['Running']:
            raise WslcError('The built-in container stopped before it was ready.')
        # WSLc 3.x uses top-level Ports; Docker-compatible versions may nest it.
        mappings = data.get('Ports', data.get('NetworkSettings', {}).get('Ports', {}))
        if set(mappings) != {'9981/tcp', '9982/tcp'}:
            raise WslcError('Unexpected backend port publication.')
        for host, guest in zip(ports, (9981, 9982)):
            if mappings.get(f'{guest}/tcp') != [{'HostIp': '127.0.0.1', 'HostPort': str(host)}]:
                raise WslcError('Cannot verify loopback-only publication of both server ports.')

    def stop_owned(self, name, owner):
        data = self.inspect_owned(name, owner, cancellable=False, missing_ok=True)
        if data is None:
            return False
        if data.get('State', {}).get('Running'):
            self.command('stop', '--time', '5', name, timeout=8, cancellable=False)
        self.command('remove', name, timeout=5, cancellable=False)
        return True

    def logs_owned(self, name, owner):
        self.inspect_owned(name, owner)
        return self.command('logs', '--tail', '200', name, timeout=5)

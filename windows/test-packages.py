"""Exercise real ZIP/installer executables with isolated profiles, not source UI mocks.

Run on a disposable Windows runner. --exercise-backend explicitly starts real WSL
containers; only containers whose private test ownership labels match are stopped.
Real WSL installation/UAC/reboot tests still require a clean, snapshot-capable VM.
"""
import argparse
import base64
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tvhplayer.core.backend_bundle import verify_bundle
from tvhplayer.core.logs import sanitize


def environment(profile, native_wsl=False):
    env = dict(os.environ, TVHPLAYER_PROFILE_DIR=str(profile), QT_QPA_PLATFORM='offscreen')
    if not native_wsl:
        # Older releases lack the app-profile override. This fallback is used
        # only for remote tests, where no WSL process should be launched.
        env.update(APPDATA=str(profile / 'Roaming'), LOCALAPPDATA=str(profile / 'Local'),
                   USERPROFILE=str(profile))
    env.pop('TVHPLAYER_EXPERIMENTAL_WSLC', None)
    return env


def wait_until(check, process, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Packaged app exited with code {process.returncode}')
        if check():
            return
        time.sleep(.2)
    raise TimeoutError('Packaged application did not reach the expected state')


def stop(process):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=15)


def remote_smoke(executable, profile):
    """An actual HTTP request proves the packaged app used the saved remote login."""
    received = threading.Event()
    authorization = 'Basic ' + base64.b64encode(b'package-test:test-password').decode()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Authorization') != authorization:
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="test"')
                self.end_headers()
                return
            payload = {'entries': [], 'total': 0}
            if self.path.split('?')[0] == '/api/channel/grid':
                received.set()
            if self.path.split('?')[0] == '/api/serverinfo':
                payload = {'sw_version': 'package-test', 'api_version': 19, 'name': 'Package acceptance'}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_POST = do_GET
        def log_message(self, *_args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config_dir = profile / 'Roaming/TVHplayer'
    config_dir.mkdir(parents=True, exist_ok=True)
    config = config_dir / 'tvhplayer.conf'
    settings = json.loads(config.read_text()) if config.exists() else {}
    settings.update(check_for_updates=False, builtin_autostart=False, last_server=1,
                    local_recording_dir=str(profile / 'recordings'),
                    package_acceptance_marker='preserve-through-upgrade', servers=[
                        {'name': 'Built-in Server', 'builtin': True, 'url': '', 'protocol': 'htsp'},
                        {'name': 'Remote acceptance', 'url': f'http://127.0.0.1:{server.server_port}',
                         'username': 'package-test', 'password': 'test-password', 'protocol': 'http'}])
    config.write_text(json.dumps(settings), encoding='utf-8')
    marker = config_dir / 'wslc-setup.json'
    marker.write_text(json.dumps({'schema': 1, 'stage': 'disabled', 'action': 'bios'}))
    process = subprocess.Popen([str(executable)], env=environment(profile), cwd=executable.parent,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        wait_until(received.is_set, process)
        time.sleep(1)
        if process.poll() is not None:
            raise RuntimeError('Packaged app exited after connecting')
        log = (profile / 'Local/TVHplayer/Logs/app.log').read_text(encoding='utf-8')
        assert 'Media player created successfully' in log, 'Bundled mpv did not initialize'
        assert 'Error starting application' not in log and 'Traceback (most recent call last)' not in log
        assert json.loads(marker.read_text())['stage'] == 'disabled', 'Remote use resumed local setup'
        assert not (config_dir / 'tvheadend/wslc-owner.json').exists(), 'Remote use started a local container'
        assert json.loads(config.read_text())['package_acceptance_marker'] == 'preserve-through-upgrade'
    finally:
        stop(process)
        server.shutdown()


def builtin_smoke(executable, profile):
    """Run the packaged backend twice; the second launch must recover our orphan."""
    import requests
    from tvhplayer.core.windows_wslc import WslcRuntimeAdapter
    config_dir = profile / 'Roaming/TVHplayer'
    config_dir.mkdir(parents=True, exist_ok=True)
    config = config_dir / 'tvhplayer.conf'
    if not config.exists():
        config.write_text(json.dumps({'check_for_updates': False, 'local_recording_dir': str(profile / 'recordings')}))
    backend = config_dir / 'tvheadend'
    owner_path = backend / 'wslc-owner.json'
    previous_owner = None
    login = None
    for _attempt in range(2):
        process = subprocess.Popen([str(executable)], env=environment(profile, native_wsl=True), cwd=executable.parent,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def ready():
            try:
                log = profile / 'Local/TVHplayer/Logs/app.log'
                if log.exists() and 'Built-in server failed:' in log.read_text(encoding='utf-8'):
                    raise RuntimeError(f'Packaged backend startup failed; inspect {log}')
                state = json.loads(config.read_text())
                auth = json.loads((backend / 'superuser').read_text())
                owner = json.loads(owner_path.read_text())
                if previous_owner is not None and owner['owner'] == previous_owner:
                    return False
                port = state.get('builtin_http_port')
                session = requests.Session()
                session.trust_env = False
                with session:
                    response = session.get(f'http://127.0.0.1:{port}/api/serverinfo',
                                           auth=(auth['username'], auth['password']), timeout=2)
                return response.ok and bool(state.get('setup_started') or state.get('setup_completed')
                                            or state.get('setup_offered'))
            except (OSError, ValueError, requests.RequestException):
                return False
        try:
            wait_until(ready, process, timeout=360)
            current = json.loads((backend / 'superuser').read_text())
            if login is not None:
                assert current == login, 'Backend credentials changed across restart/upgrade'
            login = current
            previous_owner = json.loads(owner_path.read_text())['owner']
        finally:
            # First launch deliberately leaves our owned orphan, testing crash recovery.
            stop(process)
            if (_attempt == 1 or sys.exc_info()[0] is not None) and owner_path.exists():
                owned = json.loads(owner_path.read_text())
                WslcRuntimeAdapter().stop_owned(owned['name'], owned['owner'])
    return login


def install(installer, target, profile):
    subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/CURRENTUSER',
                    '/NORESTART', f'/DIR={target}'], env=environment(profile), check=True, timeout=180)
    executable = target / 'TVHplayer.exe'
    if not executable.is_file():
        raise RuntimeError('Installer did not produce TVHplayer.exe')
    return executable


def damaged_bundle_checks(bundle):
    """Damage only the extracted private test copy, always restoring its bytes."""
    archive = bundle / 'tvheadend.tar'
    missing = bundle / 'tvheadend.tar.missing'
    archive.rename(missing)
    try:
        try:
            verify_bundle(bundle)
        except (OSError, ValueError):
            pass
        else:
            raise AssertionError('Missing distributed archive was accepted')
    finally:
        missing.rename(archive)
    with archive.open('r+b') as handle:
        original = handle.read(1)
        handle.seek(0)
        handle.write(bytes([original[0] ^ 1]))
    try:
        try:
            verify_bundle(bundle)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupt distributed archive was accepted')
    finally:
        with archive.open('r+b') as handle:
            handle.write(original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable', type=Path, required=True)
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--previous-installer', type=Path)
    parser.add_argument('--exercise-backend', action='store_true')
    parser.add_argument('--work-root', type=Path, help='Parent directory for retained test profiles and reports')
    args = parser.parse_args()
    if args.work_root:
        args.work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='tvhplayer-package-', dir=args.work_root)).resolve()
    print(f'Acceptance logs and isolated profiles: {work}', flush=True)
    results = []
    status, error = 'failed', ''
    try:
        with zipfile.ZipFile(args.portable) as archive:
            archive.extractall(work / 'portable')
        portable = work / 'portable/TVHplayer/TVHplayer.exe'
        assert portable.is_file(), 'Portable ZIP has no application'
        verify_bundle(portable.parent / 'backend')
        damaged_bundle_checks(portable.parent / 'backend')
        results.append('distributed archive: missing/corrupt files rejected by the production verifier')
        remote_smoke(portable, work / 'portable-profile')
        results.append('portable: verified bundled image and real remote connection without local setup')
        profile, backend_profile = work / 'installed-profile', work / 'backend-profile'
        if args.previous_installer:
            previous = install(args.previous_installer.resolve(), work / 'installed', profile)
            remote_smoke(previous, profile)
        if args.installer:
            installed = install(args.installer.resolve(), work / 'installed', profile)
            verify_bundle(installed.parent / 'backend')
            remote_smoke(installed, profile)
            results.append('installer: real remote connection and preserved profile')
            if args.previous_installer:
                results.append('upgrade: previous distributed installer replaced without losing profile')
        if args.exercise_backend:
            builtin_smoke(portable, work / 'portable-backend-profile')
            if args.installer:
                builtin_smoke(installed, backend_profile)
            results.append('packaged backend: authenticated readiness, first-run setup, orphan recovery and credential preservation')
        status = 'passed'
        print(json.dumps({'status': status, 'checks': results}, indent=2), flush=True)
    except Exception as exc:
        error = sanitize(str(exc))
        raise
    finally:
        (work / 'report.json').write_text(json.dumps({'status': status, 'error': error,
                                                     'completed_checks': results}, indent=2))


if __name__ == '__main__':
    main()

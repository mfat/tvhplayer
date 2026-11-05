import json
import getpass
import http.server
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from tvhplayer.core.backend_bundle import TVHEADEND_COMMIT, RELEASE_ARTIFACTS, file_digest, verify_bundle


def release_bundle(folder):
    for name in RELEASE_ARTIFACTS:
        (folder / name).write_bytes(name.encode())
    manifest = {'schema': 2, 'image': 'sha256:' + 'b' * 64, 'tvheadend_commit': TVHEADEND_COMMIT,
                'sha256': file_digest(folder / 'tvheadend.tar'),
                'artifacts': {name: file_digest(folder / name) for name in RELEASE_ARTIFACTS}}
    (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8-sig')
    return manifest


def test_release_bundle_verifies_all_artifacts(tmp_path):
    expected = release_bundle(tmp_path)
    assert verify_bundle(tmp_path, release=True) == expected
    (tmp_path / 'corresponding-source.tar.gz').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='corresponding-source'):
        verify_bundle(tmp_path, release=True)


def test_release_rejects_missing_sources(tmp_path):
    manifest = release_bundle(tmp_path)
    del manifest['artifacts']['corresponding-source.tar.gz']
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='corresponding source'):
        verify_bundle(tmp_path, release=True)


def test_runtime_rejects_wrong_source_pin(tmp_path):
    manifest = release_bundle(tmp_path)
    manifest['tvheadend_commit'] = 'c' * 40
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='source pin'):
        verify_bundle(tmp_path)


def test_runtime_and_linux_packaging_share_source_pin():
    text = (Path(__file__).resolve().parents[1] / 'packaging/tvheadend/pins.env').read_text()
    assert f'TVHEADEND_COMMIT={TVHEADEND_COMMIT}\n' in text


@pytest.mark.skipif(shutil.which('apt-get') is None, reason='Requires Linux APT')
def test_snapshot_index_failure_cannot_silently_succeed(tmp_path):
    class UnavailableIndex(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_error(503, 'Simulated snapshot outage')

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), UnavailableIndex)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sources = tmp_path / 'test.list'
        sources.write_text(f'deb [trusted=yes] http://127.0.0.1:{server.server_port}/snapshot bookworm main\n')
        status = tmp_path / 'status'
        status.touch()
        common = [
            'apt-get', '-o', f'Dir::Etc::sourcelist={sources}', '-o', 'Dir::Etc::sourceparts=-',
            '-o', f'Dir::State::status={status}', '-o', f'APT::Sandbox::User={getpass.getuser()}',
            '-o', 'Acquire::Retries=0', '-o', 'Acquire::http::Proxy::127.0.0.1=DIRECT',
        ]
        config = Path(__file__).resolve().parents[1] / 'windows/backend/apt-snapshot.conf'
        results = []
        for name, extra in [('default', []), ('snapshot', ['-c', str(config)])]:
            lists = tmp_path / name / 'lists'
            (lists / 'partial').mkdir(parents=True)
            result = subprocess.run(
                [common[0], *extra, *common[1:], '-o', f'Dir::State::lists={lists}', 'update'],
                text=True, capture_output=True, timeout=15, env=dict(os.environ, LC_ALL='C'),
            )
            results.append(result)
        # Ordinary apt-get update reports a transient outage as a warning and
        # returns success. Our actual build config must turn it into a failure.
        assert results[0].returncode == 0, results[0].stderr
        assert results[1].returncode != 0
        assert 'Failed to fetch' in results[1].stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_corresponding_sources_cover_every_runtime_repository():
    root = Path(__file__).resolve().parents[1] / 'windows/backend'

    def repositories(path, kind):
        result = set()
        for stanza in path.read_text().split('\n\n'):
            fields = dict(line.split(': ', 1) for line in stanza.splitlines()
                          if ': ' in line and not line.startswith('#'))
            if kind in fields.get('Types', '').split():
                for uri in fields['URIs'].split():
                    for suite in fields['Suites'].split():
                        for component in fields['Components'].split():
                            result.add((uri, suite, component))
        return result

    runtime = repositories(root / 'debian.sources', 'deb')
    source = repositories(root / 'base-sources.sources', 'deb-src')
    assert runtime and runtime <= source

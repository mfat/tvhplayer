import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'windows' / 'backend'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

import artifact_store
import fingerprint
from tvhplayer.core.backend_bundle import TVHEADEND_COMMIT, RELEASE_ARTIFACTS, file_digest, verify_bundle


def test_identical_inputs_produce_the_same_fingerprint():
    assert fingerprint.compute_fingerprint(ROOT) == fingerprint.compute_fingerprint(ROOT)
    assert len(fingerprint.compute_fingerprint(ROOT)) == 64


def test_application_only_changes_do_not_invalidate_backend(tmp_path):
    import shutil
    repo = tmp_path / 'repo'
    shutil.copytree(ROOT / 'windows' / 'backend', repo / 'windows' / 'backend')
    shutil.copytree(ROOT / 'packaging' / 'tvheadend', repo / 'packaging' / 'tvheadend',
                    ignore=shutil.ignore_patterns('work'))
    (repo / 'tvhplayer').mkdir()
    (repo / 'tvhplayer' / 'tvhplayer.py').write_text('print("ui")\n', encoding='utf-8')
    before = fingerprint.compute_fingerprint(repo)
    (repo / 'tvhplayer' / 'tvhplayer.py').write_text('print("ui changed")\n', encoding='utf-8')
    (repo / 'windows' / 'build-windows.sh').write_text('# packaging only\n', encoding='utf-8')
    assert fingerprint.compute_fingerprint(repo) == before


def test_backend_input_change_invalidates_fingerprint(tmp_path):
    import shutil
    repo = tmp_path / 'repo'
    shutil.copytree(ROOT / 'windows' / 'backend', repo / 'windows' / 'backend')
    shutil.copytree(ROOT / 'packaging' / 'tvheadend', repo / 'packaging' / 'tvheadend',
                    ignore=shutil.ignore_patterns('work'))
    before = fingerprint.compute_fingerprint(repo)
    sources = repo / 'windows' / 'backend' / 'debian.sources'
    sources.write_text(sources.read_text(encoding='utf-8').replace('20261104T000000Z', '20261105T000000Z'), encoding='utf-8')
    assert fingerprint.compute_fingerprint(repo) != before


def test_builder_policy_change_invalidates_fingerprint(monkeypatch):
    before = fingerprint.compute_fingerprint(ROOT)
    monkeypatch.setattr(fingerprint, 'BUILDER_POLICY', fingerprint.BUILDER_POLICY + '-changed')
    assert fingerprint.compute_fingerprint(ROOT) != before


def test_release_tag_is_immutable_identity():
    digest = 'a' * 64
    assert fingerprint.release_tag(digest) == f'backend-{digest}'
    with pytest.raises(ValueError):
        fingerprint.release_tag('latest')


def test_manifest_snapshots_follow_sources_files():
    primary, extra = fingerprint.manifest_snapshots(ROOT)
    assert primary == '20261104T000000Z'
    assert extra == '20261105T000000Z'


def _fake_bundle(directory: Path, fingerprint_value: str):
    directory.mkdir(parents=True, exist_ok=True)
    for name in RELEASE_ARTIFACTS:
        (directory / name).write_bytes(name.encode())
    manifest = {
        'schema': 2,
        'image': 'sha256:' + 'b' * 64,
        'tvheadend_commit': TVHEADEND_COMMIT,
        'sha256': file_digest(directory / 'tvheadend.tar'),
        'artifacts': {name: file_digest(directory / name) for name in RELEASE_ARTIFACTS},
    }
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (directory / 'TVHplayer-LICENSE.txt').write_text('license\n', encoding='utf-8')
    (directory / 'tvheadend-source.md').write_text('source\n', encoding='utf-8')
    artifact_store.write_inputs_document(directory, ROOT, fingerprint_value)
    verify_bundle(directory, release=True)


def test_inputs_document_rejects_wrong_fingerprint(tmp_path):
    fp = fingerprint.compute_fingerprint(ROOT)
    _fake_bundle(tmp_path, fp)
    with pytest.raises(ValueError, match='does not match'):
        artifact_store.verify_inputs_document(tmp_path, 'c' * 64)


def test_corrupt_artifact_rejected_on_cache_hit(tmp_path):
    fp = fingerprint.compute_fingerprint(ROOT)
    _fake_bundle(tmp_path, fp)
    (tmp_path / 'tvheadend.tar').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        verify_bundle(tmp_path, release=True)


def test_resolve_reuses_existing_release(tmp_path, monkeypatch):
    fp = 'a' * 64
    built = {'count': 0}

    def exists(fingerprint, **_kwargs):
        assert fingerprint == fp
        return True

    def download(fingerprint, directory, **_kwargs):
        _fake_bundle(Path(directory), fingerprint)

    def build():
        built['count'] += 1

    monkeypatch.setattr(artifact_store, 'release_exists', exists)
    monkeypatch.setattr(artifact_store, 'download_release', download)
    result = artifact_store.resolve_bundle(tmp_path / 'dist', fingerprint=fp, build_command=build)
    assert result['reused'] is True
    assert built['count'] == 0
    assert (tmp_path / 'dist' / 'manifest.json').is_file()


def test_resolve_builds_on_miss(tmp_path, monkeypatch):
    fp = 'b' * 64
    built = {'count': 0}

    monkeypatch.setattr(artifact_store, 'release_exists', lambda *_a, **_k: False)

    def build():
        built['count'] += 1
        _fake_bundle(tmp_path / 'dist', fp)

    result = artifact_store.resolve_bundle(
        tmp_path / 'dist', fingerprint=fp, build_command=build, allow_publish=False,
    )
    assert result['reused'] is False
    assert built['count'] == 1


def test_resolve_missing_without_build_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, 'release_exists', lambda *_a, **_k: False)
    with pytest.raises(LookupError, match='No published backend'):
        artifact_store.resolve_bundle(tmp_path / 'dist', fingerprint='d' * 64)


def test_publish_refuses_overwrite(tmp_path, monkeypatch):
    fp = 'e' * 64
    _fake_bundle(tmp_path, fp)
    monkeypatch.setattr(artifact_store, 'release_exists', lambda *_a, **_k: True)
    with pytest.raises(FileExistsError, match='already exists'):
        artifact_store.publish_release(fp, tmp_path)


def test_concurrent_publish_prefers_existing_release(tmp_path, monkeypatch):
    fp = 'f' * 64
    winner = tmp_path / 'winner'
    local = tmp_path / 'local'
    _fake_bundle(winner, fp)

    def exists(fingerprint, **_kwargs):
        return False

    def publish(fingerprint, directory, **_kwargs):
        raise FileExistsError('already exists')

    def download(fingerprint, directory, **_kwargs):
        import shutil
        shutil.copytree(winner, directory, dirs_exist_ok=True)

    def build():
        _fake_bundle(local, fp)

    monkeypatch.setattr(artifact_store, 'release_exists', exists)
    monkeypatch.setattr(artifact_store, 'publish_release', publish)
    monkeypatch.setattr(artifact_store, 'download_release', download)
    result = artifact_store.resolve_bundle(
        local, fingerprint=fp, build_command=build, allow_publish=True,
    )
    assert result['reused'] is True
    assert (local / 'inputs.json').is_file()


def test_line_ending_normalization_keeps_fingerprint_stable(tmp_path):
    import shutil
    repo = tmp_path / 'repo'
    shutil.copytree(ROOT / 'windows' / 'backend', repo / 'windows' / 'backend')
    shutil.copytree(ROOT / 'packaging' / 'tvheadend', repo / 'packaging' / 'tvheadend',
                    ignore=shutil.ignore_patterns('work'))
    before = fingerprint.compute_fingerprint(repo)
    path = repo / 'windows' / 'backend' / 'entrypoint.sh'
    path.write_bytes(path.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8'))
    assert fingerprint.compute_fingerprint(repo) == before


@pytest.mark.parametrize('failure', ['interrupted', 'checksum'])
def test_publish_resumes_draft_and_only_exposes_verified_assets(tmp_path, monkeypatch, failure):
    import hashlib
    import urllib.parse

    fp = 'a' * 64
    _fake_bundle(tmp_path, fp)
    release = None
    assets = {}
    uploads = []
    fail = True

    def request(url, *, method='GET', data=None, **kwargs):
        nonlocal release, fail
        if '/tags/' in url:
            if release is None:
                raise LookupError(': 404 missing')
            result = release
        elif method == 'GET' and '?per_page=100&page=' in url:
            result = [release] if release else []
        elif method == 'POST' and '/uploads?' not in url:
            assert release is None
            release = dict(json.loads(data), id=1, upload_url='https://example.com/uploads{?name}')
            assert release['draft'] is True
            result = release
        elif method == 'GET' and '/assets?' in url:
            result = list(assets.values())
        elif method == 'DELETE':
            name = next(name for name, asset in assets.items() if asset['url'] == url)
            del assets[name]
            result = {}
        elif method == 'POST':
            assert release['draft'] is True
            name = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['name'][0]
            uploads.append(name)
            if fail and len(assets) == 1:
                fail = False
                if failure == 'interrupted':
                    raise LookupError('Upload interrupted')
                digest = 'sha256:' + '0' * 64
            else:
                digest = 'sha256:' + hashlib.sha256(data).hexdigest()
            result = dict(name=name, state='uploaded', digest=digest, url=f'https://example.com/assets/{name}')
            assets[name] = result
        elif method == 'PATCH':
            assert set(assets) == set(artifact_store.BUNDLE_FILES)
            for name, asset in assets.items():
                assert asset['digest'] == 'sha256:' + file_digest(tmp_path / name)
            release.update(json.loads(data))
            result = release
        else:
            raise AssertionError((url, method))
        return 200, json.dumps(result).encode(), {}

    monkeypatch.setattr(artifact_store, '_request', request)
    with pytest.raises((LookupError, ValueError)):
        artifact_store.publish_release(fp, tmp_path)
    assert release['draft'] is True
    assert artifact_store.release_exists(fp) is False
    first_uploaded = artifact_store.BUNDLE_FILES[0]
    assert artifact_store.publish_release(fp, tmp_path) == fingerprint.release_tag(fp)
    assert uploads.count(first_uploaded) == 1
    assert release['draft'] is False
    assert artifact_store.release_exists(fp) is True
    with pytest.raises(FileExistsError):
        artifact_store.publish_release(fp, tmp_path)


def test_download_rejects_unpublished_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, '_release_metadata', lambda *a, **k: {'draft': True})
    with pytest.raises(ValueError, match='draft'):
        artifact_store.download_release('a' * 64, tmp_path)

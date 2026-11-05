import json
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

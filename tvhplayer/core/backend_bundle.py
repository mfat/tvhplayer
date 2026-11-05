"""Offline backend identity and artifact verification, shared by runtime and packaging."""
import hashlib
import json
import re
from pathlib import Path

TVHEADEND_COMMIT = '40e88d4cef2c81e44474e75fd2f1edb232575ceb'
RELEASE_ARTIFACTS = {'tvheadend.tar', 'sbom.spdx.json', 'licenses.tar.gz', 'corresponding-source.tar.gz'}


def file_digest(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while data := handle.read(4 * 1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise ValueError('Backend operation cancelled.')
            digest.update(data)
    return digest.hexdigest()


def verify_bundle(directory, *, release=False, cancel=None):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8-sig'))
    if not isinstance(manifest, dict):
        raise ValueError('Invalid backend bundle manifest')
    if manifest.get('schema') not in (1, 2) or manifest.get('tvheadend_commit') != TVHEADEND_COMMIT:
        raise ValueError('Backend bundle must use the current TVHeadend source pin')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', manifest.get('image', '')):
        raise ValueError('Expected immutable backend image identity')
    if not re.fullmatch(r'[0-9a-f]{64}', manifest.get('sha256', '')):
        raise ValueError('Invalid backend archive SHA256')
    if (directory / 'tvheadend.tar').is_symlink() or file_digest(directory / 'tvheadend.tar', cancel) != manifest['sha256']:
        raise ValueError('Backend image checksum mismatch')
    if release:
        artifacts = manifest.get('artifacts', {})
        if manifest.get('schema') != 2 or set(artifacts) != RELEASE_ARTIFACTS:
            raise ValueError('Release bundle requires its SBOM, licenses and corresponding source')
        for name, digest in artifacts.items():
            if not re.fullmatch(r'[0-9a-f]{64}', digest) or (directory / name).is_symlink():
                raise ValueError('Invalid backend artifact digest')
            if file_digest(directory / name, cancel) != digest:
                raise ValueError(f'Backend artifact checksum mismatch: {name}')
    return manifest

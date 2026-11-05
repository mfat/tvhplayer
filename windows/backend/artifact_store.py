"""GitHub Release storage for immutable backend bundles (backend-<fingerprint>)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tvhplayer.core.backend_bundle import RELEASE_ARTIFACTS, verify_bundle  # noqa: E402
import fingerprint as backend_fingerprint  # noqa: E402

BUILDER_POLICY = backend_fingerprint.BUILDER_POLICY
compute_fingerprint = backend_fingerprint.compute_fingerprint
input_digests = backend_fingerprint.input_digests
release_tag = backend_fingerprint.release_tag

BUNDLE_FILES = sorted(
    RELEASE_ARTIFACTS | {'manifest.json', 'TVHplayer-LICENSE.txt', 'tvheadend-source.md', 'inputs.json'}
)
USER_AGENT = 'tvhplayer-backend-artifact'


def _repo_slug(repository: str | None = None) -> str:
    slug = repository or os.environ.get('GITHUB_REPOSITORY') or 'mfat/tvhplayer'
    if slug.count('/') != 1:
        raise ValueError(f'Invalid GitHub repository slug: {slug}')
    return slug


def _token(token: str | None = None) -> str | None:
    return token or os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')


def _request(url: str, *, token: str | None = None, method: str = 'GET', data: bytes | None = None,
             content_type: str | None = None, accept: str = 'application/vnd.github+json'):
    headers = {
        'Accept': accept,
        'User-Agent': USER_AGENT,
        'X-GitHub-Api-Version': '2022-11-28',
    }
    auth = _token(token)
    if auth:
        headers['Authorization'] = f'Bearer {auth}'
    if content_type:
        headers['Content-Type'] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')
        raise LookupError(f'GitHub API {method} {url} failed: {error.code} {detail}') from error


def write_inputs_document(directory: Path, root: Path = ROOT, fingerprint: str | None = None) -> dict:
    directory = Path(directory)
    fingerprint = fingerprint or compute_fingerprint(root)
    document = {
        'schema': 1,
        'fingerprint': fingerprint,
        'builder_policy': BUILDER_POLICY,
        'files': input_digests(root),
    }
    (directory / 'inputs.json').write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    return document


def verify_inputs_document(directory: Path, fingerprint: str) -> dict:
    document = json.loads((Path(directory) / 'inputs.json').read_text(encoding='utf-8-sig'))
    if document.get('schema') != 1 or document.get('fingerprint') != fingerprint:
        raise ValueError('Backend inputs document does not match the requested fingerprint')
    if document.get('builder_policy') != BUILDER_POLICY:
        raise ValueError('Backend inputs document uses a different builder policy')
    return document


def release_exists(fingerprint: str, *, repository: str | None = None, token: str | None = None) -> bool:
    tag = release_tag(fingerprint)
    owner, repo = _repo_slug(repository).split('/')
    url = f'https://api.github.com/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(tag)}'
    try:
        _request(url, token=token)
        return True
    except LookupError as error:
        if ': 404 ' in str(error):
            return False
        raise


def _release_metadata(fingerprint: str, *, repository: str | None = None, token: str | None = None) -> dict:
    tag = release_tag(fingerprint)
    owner, repo = _repo_slug(repository).split('/')
    url = f'https://api.github.com/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(tag)}'
    _status, body, _headers = _request(url, token=token)
    return json.loads(body.decode('utf-8'))


def download_release(fingerprint: str, directory: Path, *, repository: str | None = None,
                     token: str | None = None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    release = _release_metadata(fingerprint, repository=repository, token=token)
    assets = {asset['name']: asset for asset in release.get('assets', [])}
    missing = [name for name in BUNDLE_FILES if name not in assets]
    if missing:
        raise ValueError('Backend release is incomplete: ' + ', '.join(missing))
    for name in BUNDLE_FILES:
        asset = assets[name]
        _status, body, _headers = _request(asset['url'], token=token, accept='application/octet-stream')
        (directory / name).write_bytes(body)
    verify_inputs_document(directory, fingerprint)
    verify_bundle(directory, release=True)
    return directory


def publish_release(fingerprint: str, directory: Path, *, repository: str | None = None,
                    token: str | None = None, target_commitish: str | None = None) -> str:
    """Create an immutable backend-<fingerprint> release. Fails if the tag already exists."""
    directory = Path(directory)
    write_inputs_document(directory, fingerprint=fingerprint)
    verify_inputs_document(directory, fingerprint)
    verify_bundle(directory, release=True)
    for name in BUNDLE_FILES:
        if not (directory / name).is_file():
            raise FileNotFoundError(f'Missing bundle file for publish: {name}')
    if release_exists(fingerprint, repository=repository, token=token):
        raise FileExistsError(f'Backend release already exists for {release_tag(fingerprint)}')

    owner, repo = _repo_slug(repository).split('/')
    tag = release_tag(fingerprint)
    payload = {
        'tag_name': tag,
        'name': f'TVHplayer backend {fingerprint[:12]}',
        'body': (
            'Immutable offline Windows TVHeadend backend bundle.\n\n'
            f'- Fingerprint: `{fingerprint}`\n'
            f'- Builder policy: `{BUILDER_POLICY}`\n\n'
            'Do not retag or replace assets. Application releases may reuse this bundle.'
        ),
        'draft': False,
        'prerelease': True,
        'make_latest': 'false',
    }
    if target_commitish:
        payload['target_commitish'] = target_commitish
    try:
        _status, body, _headers = _request(
            f'https://api.github.com/repos/{owner}/{repo}/releases',
            token=token,
            method='POST',
            data=json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )
    except LookupError as error:
        if ': 422 ' in str(error) or ': 409 ' in str(error):
            raise FileExistsError(f'Backend release already exists for {tag}') from error
        raise
    release = json.loads(body.decode('utf-8'))
    upload_url = release['upload_url'].split('{', 1)[0]
    for name in BUNDLE_FILES:
        path = directory / name
        query = urllib.parse.urlencode({'name': name})
        _request(
            f'{upload_url}?{query}',
            token=token,
            method='POST',
            data=path.read_bytes(),
            content_type='application/octet-stream',
        )
    return tag


def resolve_bundle(directory: Path, *, fingerprint: str | None = None, force_rebuild: bool = False,
                   repository: str | None = None, token: str | None = None,
                   allow_publish: bool = False, build_command=None, target_commitish: str | None = None) -> dict:
    """Reuse a verified backend release when possible; otherwise build and optionally publish."""
    directory = Path(directory)
    fingerprint = fingerprint or compute_fingerprint()
    reused = False
    if not force_rebuild and release_exists(fingerprint, repository=repository, token=token):
        download_release(fingerprint, directory, repository=repository, token=token)
        reused = True
    else:
        if build_command is None:
            raise LookupError(f'No published backend for {release_tag(fingerprint)}')
        directory.mkdir(parents=True, exist_ok=True)
        build_command()
        write_inputs_document(directory, fingerprint=fingerprint)
        verify_bundle(directory, release=True)
        if allow_publish:
            try:
                publish_release(
                    fingerprint, directory, repository=repository, token=token,
                    target_commitish=target_commitish,
                )
            except FileExistsError:
                if force_rebuild:
                    # Keep the local rebuild for this run; never overwrite the published tag.
                    pass
                else:
                    # Lost a publish race: prefer the immutable winner.
                    download_release(fingerprint, directory, repository=repository, token=token)
                    reused = True
    return {'fingerprint': fingerprint, 'tag': release_tag(fingerprint), 'reused': reused}

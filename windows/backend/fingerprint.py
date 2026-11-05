"""Deterministic identity for the Windows offline TVHeadend backend inputs."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Bump deliberately when the CI builder/toolchain contract changes
# (runner image major, Docker assumptions, hashing rules).
BUILDER_POLICY = 'ubuntu-24.04-docker-v1'

# Paths relative to the repository root. Unrelated app/UI changes must not
# appear here. Text files are hashed with LF newlines for cross-OS stability.
TEXT_INPUTS = (
    'windows/backend/Containerfile',
    'windows/backend/apt-snapshot.conf',
    'windows/backend/debian.sources',
    'windows/backend/base-sources.sources',
    'windows/backend/entrypoint.sh',
    'windows/backend/build-bundle.py',
    'windows/backend/fingerprint.py',
    'windows/backend/artifact_store.py',
    'packaging/tvheadend/pins.env',
)

TEXT_GLOBS = (
    ('packaging/tvheadend', '*.sh'),
)

SNAPSHOT_RE = re.compile(r'/archive/(?:debian|debian-security)/(\d{8}T\d{6}Z)')


def _text_bytes(path: Path) -> bytes:
    return path.read_text(encoding='utf-8').replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')


def input_paths(root: Path = ROOT) -> list[Path]:
    root = Path(root).resolve()
    paths = [root / relative for relative in TEXT_INPUTS]
    for directory, pattern in TEXT_GLOBS:
        paths.extend(sorted((root / directory).glob(pattern)))
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError('Missing backend fingerprint inputs: ' + ', '.join(map(str, missing)))
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def input_digests(root: Path = ROOT) -> dict[str, str]:
    root = Path(root).resolve()
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(_text_bytes(path)).hexdigest()
        for path in input_paths(root)
    }


def compute_fingerprint(root: Path = ROOT) -> str:
    root = Path(root).resolve()
    digest = hashlib.sha256()
    digest.update(BUILDER_POLICY.encode('utf-8'))
    for path in input_paths(root):
        relative = path.relative_to(root).as_posix()
        digest.update(b'\0')
        digest.update(relative.encode('utf-8'))
        digest.update(b'\0')
        digest.update(_text_bytes(path))
    return digest.hexdigest()


def release_tag(fingerprint: str) -> str:
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('Backend fingerprint must be a SHA-256 hex digest')
    return f'backend-{fingerprint}'


def snapshot_timestamps(path: Path) -> list[str]:
    found = SNAPSHOT_RE.findall(Path(path).read_text(encoding='utf-8'))
    if not found:
        raise ValueError(f'No Debian snapshot timestamps in {path}')
    return found


def manifest_snapshots(root: Path = ROOT) -> tuple[str, str]:
    """Primary binary snapshot and the extra source snapshot used for base apt."""
    root = Path(root).resolve()
    binary = snapshot_timestamps(root / 'windows/backend/debian.sources')
    sources = snapshot_timestamps(root / 'windows/backend/base-sources.sources')
    primary = binary[0]
    if any(stamp != primary for stamp in binary):
        # Multiple binary snapshots are allowed only when identical; keep explicit.
        raise ValueError('debian.sources mixes multiple snapshot timestamps')
    extra = [stamp for stamp in sources if stamp != primary]
    if not extra:
        raise ValueError('base-sources.sources must include a snapshot beyond the binary pin')
    return primary, extra[-1]

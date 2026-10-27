"""Channel logos from a picon pack, for channels the server has no logo for. No Qt imports.

The pack is the picons project's service-name set (utf8snp): one PNG per
channel name, such as ``bbc one lon hd.png`` or ``bbconelondon.png``. Names are
matched loosely: case, spaces and punctuation are ignored, and a trailing
quality such as HD may be dropped or added.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tarfile
import tempfile
import unicodedata
from pathlib import Path
from typing import Callable, Dict, Optional

import requests

from .proxy import configure_session

# The web page redirects to the newest release's tag. GitHub's API would say the same but
# allows few calls an hour without a login.
LATEST_URL = 'https://github.com/picons/picons/releases/latest'
DOWNLOAD_URL = 'https://github.com/picons/picons/releases/download/{tag}/{name}'
_TAG = re.compile(r'/releases/tag/([^/?#]+)$')
# 100x60 is plenty for the channel list; light logos suit a dark window, dark ones a light window.
ASSET_PREFIX = 'utf8snp-full.100x60-86x46.{style}.on.transparent_'
ASSET_SUFFIX = '.symlink.tar.xz'
STYLE_LIGHT = 'light'
STYLE_DARK = 'dark'
QUALITY = ('uhd', 'fhd', 'hd', 'sd', '4k', 'hevc')
TIMEOUT = 30
CHUNK = 256 * 1024
MAX_DOWNLOAD = 200 * 1024 * 1024
REPLACEMENTS = (('&', 'and'), ('+', 'plus'), ('*', 'star'))
_BRACKETS = re.compile(r'[\(\[\{][^\)\]\}]*[\)\]\}]')


def default_picon_dir() -> Path:
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'TVHplayer' / 'picons'
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home()) / 'TVHplayer' / 'picons'
    xdg = os.environ.get('XDG_DATA_HOME')
    base = Path(xdg) if xdg else Path.home() / '.local' / 'share'
    return base / 'tvhplayer' / 'picons'


def picon_key(name: str) -> str:
    """Letters and digits of ``name`` in lower case, with & + * spelled out."""
    text = unicodedata.normalize('NFKC', name or '').lower()
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return ''.join(c for c in text if c.isalnum())


def name_keys(name: str):
    """Keys to try for a channel name, best first."""
    plain = _BRACKETS.sub(' ', name or '')
    base = picon_key(plain)
    if not base:
        return []
    keys = [picon_key(name), base]
    for quality in QUALITY:
        if base.endswith(quality) and len(base) > len(quality) + 1:
            keys.append(base[:-len(quality)])
            break
    keys.append(base + 'hd')
    return [key for key in dict.fromkeys(keys) if key]


class PiconIndex:
    """The PNGs of a picon folder, by ``picon_key`` of their names."""

    def __init__(self, folder: Optional[Path] = None):
        self.folder = Path(folder) if folder else None
        # File names, not Paths: a pack has tens of thousands, read while the window is built.
        self._files: Dict[str, str] = {}
        if self.folder is not None and self.folder.is_dir():
            # Names can start with a dot, such as '.red.png' for the channel '.red'.
            names = [n for n in os.listdir(self.folder) if n.endswith('.png')]
            # Shorter names first, so a plain name wins over a regional variant with the same key.
            names.sort(key=lambda n: (len(n), n))
            for name in names:
                stem = name[:-4]
                # Most pack names are their own key already.
                if not (stem.isascii() and stem.isalnum() and stem == stem.lower()):
                    stem = picon_key(stem)
                self._files.setdefault(stem, name)

    def __len__(self):
        return len(self._files)

    def find(self, channel_name: str) -> Optional[Path]:
        for key in name_keys(channel_name):
            name = self._files.get(key)
            if name is not None:
                return self.folder / name
        return None


def latest_tag(location: str) -> str:
    """The release tag from the latest-release redirect, or ''."""
    match = _TAG.search(location or '')
    return match.group(1) if match else ''


def pack_url(tag: str, style: str) -> str:
    """Release files are named after the tag, such as ``…light.on.transparent_<tag>.symlink.tar.xz``."""
    name = f'{ASSET_PREFIX.format(style=style)}{tag}{ASSET_SUFFIX}'
    return DOWNLOAD_URL.format(tag=tag, name=name)


def download_pack(
    folder: Path,
    style: str = STYLE_LIGHT,
    progress: Callable[[int, int], None] = lambda done, total: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> int:
    """Fetch the newest pack into ``folder``, replacing what was there. Returns the number of logos."""
    folder = Path(folder)
    session = requests.Session()
    configure_session(session, LATEST_URL)
    with session:
        response = session.head(LATEST_URL, timeout=TIMEOUT, allow_redirects=False)
        tag = latest_tag(response.headers.get('Location', ''))
        if not tag:
            raise ValueError('Could not find the newest picon pack')
        folder.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder.parent, prefix='.picons-') as work:
            archive = Path(work) / 'pack.tar.xz'
            done = 0
            with session.get(pack_url(tag, style), timeout=TIMEOUT, stream=True) as download:
                download.raise_for_status()
                total = int(download.headers.get('Content-Length') or 0)
                if total > MAX_DOWNLOAD:
                    raise ValueError('The picon pack is larger than expected')
                with archive.open('wb') as out:
                    for chunk in download.iter_content(CHUNK):
                        if cancelled():
                            raise InterruptedError('Cancelled')
                        done += len(chunk)
                        if done > MAX_DOWNLOAD:
                            raise ValueError('The picon pack is larger than expected')
                        out.write(chunk)
                        progress(done, total)
            extracted = Path(work) / 'pack'
            extract_pack(archive, extracted)
            tops = [path for path in extracted.iterdir() if path.is_dir()]
            source = tops[0] if len(tops) == 1 else extracted
            old = Path(work) / 'old'
            if folder.exists():
                folder.rename(old)
            try:
                shutil.move(str(source), str(folder))
            except OSError:
                if old.exists() and not folder.exists():
                    old.rename(folder)
                raise
    return len(PiconIndex(folder))


def extract_pack(archive: Path, target: Path) -> None:
    """Unpack only regular files, folders, and links that stay inside ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:xz') as tar:
        tar.extractall(target, filter='data')

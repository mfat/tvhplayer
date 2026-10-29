"""Ask GitHub whether a newer TVHplayer has been released. No Qt imports."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import requests

LATEST_RELEASE_API = 'https://api.github.com/repos/mfat/tvhplayer/releases/latest'
RELEASES_PAGE = 'https://github.com/mfat/tvhplayer/releases/latest'
# The automatic check runs at most this often; GitHub allows 60 unauthenticated requests an hour.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 10

_VERSION = re.compile(r'^v?(\d+(?:\.\d+)*)$')


class UpdateCheckError(Exception):
    """The latest release could not be read."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str


def version_key(text):
    """``'v4.2.1'`` -> ``(4, 2, 1)``; None for anything that is not a plain version."""
    match = _VERSION.match((text or '').strip())
    if not match:
        return None
    parts = [int(part) for part in match.group(1).split('.')]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(latest, current):
    latest_key, current_key = version_key(latest), version_key(current)
    return latest_key is not None and current_key is not None and latest_key > current_key


def check_due(last_check, now, interval=CHECK_INTERVAL_SECONDS):
    """A clock set back is treated as due, so the check is not put off for good."""
    try:
        last = float(last_check or 0)
    except (TypeError, ValueError):
        return True
    return not last or now < last or now - last >= interval


def fetch_latest(current_version, get=requests.get):
    """Return the latest published release, skipping drafts and pre-releases."""
    try:
        response = get(
            LATEST_RELEASE_API,
            headers={
                'Accept': 'application/vnd.github+json',
                'User-Agent': f'TVHplayer/{current_version}',
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise UpdateCheckError(f'GitHub could not be reached: {e}') from e
    except ValueError as e:
        raise UpdateCheckError('GitHub sent an answer that cannot be read') from e
    tag = data.get('tag_name') if isinstance(data, dict) else None
    if version_key(tag) is None:
        raise UpdateCheckError(f'The latest release has no version number: {tag!r}')
    url = data.get('html_url')
    if not isinstance(url, str) or not url.startswith('https://'):
        url = RELEASES_PAGE
    return Release(version=tag.strip().lstrip('v'), url=url)


def installed_by_flatpak(environ=None, info_file=Path('/.flatpak-info')):
    environ = os.environ if environ is None else environ
    return bool(environ.get('FLATPAK_ID')) or info_file.exists()

import json

import pytest
import requests

from tvhplayer.core.config import ConfigStore, default_config
from tvhplayer.core.updates import (
    LATEST_RELEASE_API,
    RELEASES_PAGE,
    UpdateCheckError,
    check_due,
    fetch_latest,
    installed_by_flatpak,
    is_newer,
    version_key,
)


class Response:
    def __init__(self, data=None, status=200, bad_json=False):
        self._data = data
        self._status = status
        self._bad_json = bad_json

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f'{self._status} Error')

    def json(self):
        if self._bad_json:
            raise ValueError('not json')
        return self._data


def test_version_key_reads_tags_and_ignores_trailing_zeros():
    assert version_key('v4.2.1') == (4, 2, 1)
    assert version_key('4.2') == version_key('4.2.0') == (4, 2)
    assert version_key('4.2.1-rc1') is None
    assert version_key('') is None
    assert version_key(None) is None


def test_is_newer_compares_numbers_not_text():
    assert is_newer('4.10', '4.9.3')
    assert is_newer('v4.2.2', '4.2.1')
    assert not is_newer('4.2.1', '4.2.1')
    assert not is_newer('4.2.0', '4.2')
    assert not is_newer('4.1', '4.2.1')
    assert not is_newer('nightly', '4.2.1')


def test_check_due_once_a_day():
    day = 24 * 60 * 60
    assert check_due(0, 1000)
    assert check_due('broken', 1000)
    assert not check_due(1000, 1000 + day - 1)
    assert check_due(1000, 1000 + day)
    # A clock set back does not put the check off.
    assert check_due(1000 + day, 1000)


def test_fetch_latest_reads_the_release():
    calls = []

    def get(url, headers, timeout):
        calls.append((url, headers))
        return Response({'tag_name': 'v4.2.2', 'html_url': 'https://github.com/mfat/tvhplayer/releases/tag/v4.2.2'})

    release = fetch_latest('4.2.1', get=get)
    assert release.version == '4.2.2'
    assert release.url.endswith('/v4.2.2')
    assert calls[0][0] == LATEST_RELEASE_API
    assert calls[0][1]['User-Agent'] == 'TVHplayer/4.2.1'


def test_fetch_latest_falls_back_to_the_releases_page():
    release = fetch_latest('4.2.1', get=lambda *a, **k: Response({'tag_name': '4.3', 'html_url': 'javascript:x'}))
    assert release.url == RELEASES_PAGE


@pytest.mark.parametrize('response', [
    Response(status=403),
    Response(bad_json=True),
    Response({'tag_name': 'latest'}),
    Response(['not', 'a', 'dict']),
])
def test_fetch_latest_reports_what_it_cannot_read(response):
    with pytest.raises(UpdateCheckError):
        fetch_latest('4.2.1', get=lambda *a, **k: response)


def test_fetch_latest_reports_network_errors():
    def get(*_a, **_k):
        raise requests.ConnectionError('offline')

    with pytest.raises(UpdateCheckError, match='offline'):
        fetch_latest('4.2.1', get=get)


def test_installed_by_flatpak(tmp_path):
    missing = tmp_path / 'none'
    assert installed_by_flatpak({'FLATPAK_ID': 'io.github.mfat.tvhplayer'}, missing)
    assert not installed_by_flatpak({}, missing)
    info = tmp_path / '.flatpak-info'
    info.write_text('[Application]\n')
    assert installed_by_flatpak({}, info)


def test_update_settings_default_and_survive_bad_values(tmp_path):
    defaults = default_config()
    assert defaults['check_for_updates'] is True
    assert defaults['last_update_check'] == 0.0
    assert defaults['skipped_update_version'] == ''
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({
        'check_for_updates': 0, 'last_update_check': 'soon', 'skipped_update_version': 4,
    }), encoding='utf-8')
    data = ConfigStore(path).data
    assert data['check_for_updates'] is False
    assert data['last_update_check'] == 0.0
    assert data['skipped_update_version'] == ''

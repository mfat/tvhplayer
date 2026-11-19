"""An early channel snapshot must not trigger server configuration writes."""
import io
import json
from types import SimpleNamespace
import urllib.error

import pytest

from tvhplayer.core import builtin_server


@pytest.mark.parametrize('payload,ready', [
    ({'name': 'Tvheadend'}, True),
    ({'name': 'Tvheadend', 'inputs_loaded': False}, False),
    ({'name': 'Tvheadend', 'inputs_loaded': True}, True),
    ({'name': 'Tvheadend', 'inputs_loaded': None}, False),
    ({'inputs_loaded': True}, False),
    ([], False),
])
def test_serverinfo_readiness(monkeypatch, payload, ready):
    def open_response(url, timeout):
        assert url == 'http://127.0.0.1:9981/api/serverinfo'
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(builtin_server, '_direct_opener',
                        lambda *args: SimpleNamespace(open=open_response))
    assert builtin_server.serverinfo_ok(9981) is ready


def test_readiness_rechecks_loading_server_and_recovers_from_timeout(monkeypatch):
    responses = iter([False, urllib.error.URLError('timed out'), True])

    def open_response(url, timeout):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(json.dumps({'sw_version': 'test', 'inputs_loaded': result}).encode())

    monkeypatch.setattr(builtin_server, '_direct_opener',
                        lambda *args: SimpleNamespace(open=open_response))
    assert not builtin_server.serverinfo_ok(9981)
    assert not builtin_server.serverinfo_ok(9981)
    assert builtin_server.serverinfo_ok(9981)

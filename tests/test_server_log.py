import json

import pytest

from tvhplayer.core.errors import TvhAuthError
from tvhplayer.core.server_log import ServerLogFeed


class _Response:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self.text = json.dumps({} if payload is None else payload)


class _Session:
    def __init__(self, *replies):
        self.calls = []
        self.replies = list(replies)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.replies.pop(0)

    def close(self):
        return None


def _feed(*replies):
    feed = ServerLogFeed({'url': 'http://box:9981/tvh', 'username': 'u', 'password': 'p'})
    feed._session.close()
    feed._session = _Session(*replies)
    return feed


def test_first_poll_opens_a_mailbox_and_reads_admin():
    feed = _feed(
        _Response({'boxid': 'b1', 'messages': [
            {'notificationClass': 'accessUpdate', 'admin': 1},
            {'notificationClass': 'setServerIpPort', 'port': 9981},
        ]}),
        _Response({'boxid': 'b1', 'messages': [
            {'notificationClass': 'logmessage', 'logtxt': '12:00 subscription: start'},
            {'notificationClass': 'diskspaceUpdate'},
        ]}),
    )
    first = feed.poll()
    assert first.admin is True
    assert first.lines == []
    url, kwargs = feed._session.calls[0]
    assert url == 'http://box:9981/tvh/comet/poll'
    assert kwargs['data'] == {'immediate': '1'}

    second = feed.poll()
    assert second.admin is None
    assert second.lines == ['12:00 subscription: start']
    assert feed._session.calls[1][1]['data'] == {'boxid': 'b1', 'immediate': '0'}


def test_non_admin_login_is_reported():
    feed = _feed(_Response({'boxid': 'b1', 'messages': [{'notificationClass': 'accessUpdate', 'admin': 0}]}))
    assert feed.poll().admin is False


def test_rejected_login_raises_auth_error():
    feed = _feed(_Response(status=401))
    with pytest.raises(TvhAuthError):
        feed.poll()

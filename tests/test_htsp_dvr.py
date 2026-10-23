import socket

from tvhplayer.core.htsmsg import serialize
from tvhplayer.core.htsp_backend import HtspBackend
from tvhplayer.core.htsp_connection import HtspConnection
from tvhplayer.core.models import ServerConfig


def _backend():
    return HtspBackend(ServerConfig(name='box', url='http://127.0.0.1:9981', protocol='htsp'))


def test_dvr_update_keeps_title_and_marks_recording():
    backend = _backend()
    backend._store_dvr({
        'id': 7,
        'method': 'dvrEntryAdd',
        'title': 'News',
        'channelName': 'IRINN',
        'start': 100,
        'stop': 700,
        'state': 'scheduled',
    })
    backend._store_dvr({
        'id': 7,
        'method': 'dvrEntryUpdate',
        'state': 'recording',
        'dataSize': 4096,
    })
    entry = backend._dvr[7]
    assert entry.title == 'News'
    assert entry.channel_name == 'IRINN'
    assert entry.start == 100
    assert entry.duration == 600
    assert entry.category() == 'recording'
    assert entry.htsp_id == 7


def test_drain_async_reads_complete_messages_only():
    left, right = socket.socketpair()
    left.settimeout(1)
    right.settimeout(1)
    conn = HtspConnection('127.0.0.1', 9982)
    conn._sock = left
    payload = serialize({'method': 'dvrEntryUpdate', 'id': 7, 'state': 'recording'})
    try:
        right.sendall(payload[:2])
        assert conn.drain_async() == 0

        seen = []
        right.sendall(payload[2:])
        assert conn.drain_async(seen.append) == 1
        assert seen[0]['state'] == 'recording'
        assert seen[0]['id'] == 7

        right.sendall(payload)
        msg = conn._recv()
        assert msg['method'] == 'dvrEntryUpdate'
    finally:
        left.close()
        right.close()

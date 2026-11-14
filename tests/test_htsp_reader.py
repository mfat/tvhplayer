"""Exercise the reader against real sockets, including fragmented frames."""
import socket
import threading
import time

import pytest

from tvhplayer.core.errors import TvhConnectionError
from tvhplayer.core.htsmsg import read_message, serialize
from tvhplayer.core.htsp_backend import HtspBackend
from tvhplayer.core.htsp_connection import HtspConnection
from tvhplayer.core.models import ServerConfig


def read(sock):
    def exact(n):
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise EOFError()
            data += chunk
        return data
    return read_message(exact)


def pair():
    left, right = socket.socketpair()
    left.settimeout(2)
    right.settimeout(2)
    conn = HtspConnection('localhost', 9982, timeout=2)
    conn._sock = left
    return conn, right


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, 'condition timed out'
        time.sleep(.005)


def test_reader_dispatches_fragmented_metadata_and_sequenced_rpc():
    conn, server = pair()
    seen = []
    conn.start_reader(seen.append)
    result = []
    worker = threading.Thread(target=lambda: result.append(conn.rpc('getProfiles')))
    try:
        worker.start()
        request = read(server)
        frame = serialize({'method': 'channelAdd', 'channelId': 1})
        server.sendall(frame[:2])
        time.sleep(.02)
        assert not seen
        server.sendall(frame[2:7])
        time.sleep(.02)
        assert not seen
        server.sendall(frame[7:] + serialize({'seq': request['seq'] + 50, 'ignored': 1}) +
                       serialize({'seq': request['seq'], 'profiles': []}))
        worker.join(2)
        assert not worker.is_alive()
        assert result[0]['profiles'] == []
        assert seen == [{'method': 'channelAdd', 'channelId': 1}]
        # Updates arrive with no RPC or drain call from the consumer.
        server.sendall(serialize({'method': 'channelDelete', 'channelId': 1}))
        until(lambda: len(seen) == 2)
        assert seen[-1]['method'] == 'channelDelete'
    finally:
        conn.close()
        server.close()
        worker.join(2)
    assert conn._reader is None


def test_disconnect_wakes_rpc_waiter_and_close_stops_idle_reader():
    conn, server = pair()
    errors = []
    conn.start_reader(lambda msg: None)
    def call():
        try:
            conn.rpc('blocked', timeout=20)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=call)
    worker.start()
    read(server)
    server.close()
    worker.join(2)
    assert not worker.is_alive()
    assert isinstance(errors[0], TvhConnectionError)
    conn.close()

    conn, server = pair()
    conn.start_reader(lambda msg: None)
    reader = conn._reader
    conn.close()
    assert not reader.is_alive()
    server.close()


def test_initial_channels_are_available_before_sync_and_updates_coalesce():
    conn, server = pair()
    backend = HtspBackend(ServerConfig(name='test', url='http://localhost', protocol='htsp'))
    backend._conn = conn
    backend._ready = True
    result = []
    worker = threading.Thread(target=lambda: result.append(backend.get_channels()))
    try:
        worker.start()
        request = read(server)
        assert request['method'] == 'enableAsyncMetadata' and request['epg'] == 0
        server.sendall(serialize({'seq': request['seq']}) + serialize({
            'method': 'channelAdd', 'channelId': 1, 'channelName': 'First', 'channelNumber': 1,
        }))
        until(lambda: bool(backend._channels))
        changes, tags, reset = backend.take_channel_changes()
        assert changes[1].name == 'First'
        assert worker.is_alive()  # Initial list is already visible to the UI.
        server.sendall(serialize({'method': 'channelUpdate', 'channelId': 1, 'channelName': 'Latest'}) +
                       serialize({'method': 'initialSyncCompleted'}))
        worker.join(2)
        assert result[0][0].name == 'Latest'
        server.sendall(serialize({'method': 'channelUpdate', 'channelId': 1, 'channelName': 'Idle update'}) +
                       serialize({'method': 'channelAdd', 'channelId': 2, 'channelName': 'Temporary'}) +
                       serialize({'method': 'channelDelete', 'channelId': 2}))
        until(lambda: backend._channel_changes.get(1) is not None and
              backend._channel_changes[1].name == 'Idle update' and 2 in backend._channel_changes and
              backend._channel_changes[2] is None)
        changes, _, _ = backend.take_channel_changes()
        assert changes[1].name == 'Idle update' and changes[2] is None
        assert backend.take_channel_changes()[0] == {}
    finally:
        backend.close()
        server.close()
        worker.join(2)


def test_rpc_timeout_and_reconnect_do_not_keep_old_reader(monkeypatch):
    conn, server = pair()
    conn.start_reader(lambda msg: None)
    old_reader = conn._reader
    with pytest.raises(TvhConnectionError, match='timed out'):
        conn.rpc('unanswered', timeout=.03)
    assert not old_reader.is_alive()
    server.close()
    left, right = socket.socketpair()
    monkeypatch.setattr(socket, 'create_connection', lambda *args: left)
    seen = []
    try:
        conn.connect()
        conn.start_reader(seen.append)
        right.sendall(serialize({'method': 'channelAdd', 'channelId': 99}))
        until(lambda: bool(seen))
        assert seen[0]['channelId'] == 99
        assert conn._reader is not old_reader
    finally:
        conn.close()
        right.close()


def test_backend_reconnect_replaces_old_metadata(monkeypatch):
    backend = HtspBackend(ServerConfig(name='test', url='http://localhost', protocol='htsp'))
    pairs = [socket.socketpair(), socket.socketpair()]
    clients = iter(left for left, _ in pairs)
    monkeypatch.setattr(socket, 'create_connection', lambda *args: next(clients))
    finish = threading.Event()
    errors = []
    def serve(sock, channel_id):
        sock.settimeout(3)
        try:
            request = read(sock)
            assert request['method'] == 'hello'
            sock.sendall(serialize({'seq': request['seq'], 'htspversion': 38, 'challenge': b'challenge'}))
            request = read(sock)
            assert request['method'] == 'authenticate'
            sock.sendall(serialize({'seq': request['seq']}))
            request = read(sock)
            assert request['method'] == 'enableAsyncMetadata'
            sock.sendall(serialize({'seq': request['seq']}) + serialize({
                'method': 'channelAdd', 'channelId': channel_id, 'channelName': str(channel_id),
            }) + serialize({'method': 'initialSyncCompleted'}))
            finish.wait(3)
        except Exception as exc:
            errors.append(exc)
    workers = [threading.Thread(target=serve, args=(right, i + 1)) for i, (_, right) in enumerate(pairs)]
    try:
        workers[0].start()
        assert [c.htsp_id for c in backend.get_channels()] == [1]
        pairs[0][1].close()
        until(lambda: backend.metadata_disconnected)
        workers[1].start()
        assert [c.htsp_id for c in backend.get_channels()] == [2]
        changes, _, reset = backend.take_channel_changes()
        assert reset and set(changes) == {2}
        assert not backend.metadata_disconnected
        backend._synced = False
        assert backend.channel_snapshot() is None
    finally:
        finish.set()
        backend.close()
        for left, right in pairs:
            left.close()
            right.close()
        for worker in workers:
            if worker.ident is not None:
                worker.join(3)
    assert not errors


def test_channel_batches_are_bounded_and_keep_latest_pending_changes():
    backend = HtspBackend(ServerConfig(name='test', url='http://localhost', protocol='htsp'))
    for i in range(5000):
        backend._on_async({'method': 'channelAdd', 'channelId': i, 'channelName': str(i)})
    first, _, _ = backend.take_channel_changes(limit=2000)
    assert len(first) == 2000 and backend.pending_channel_count == 3000
    backend._on_async({'method': 'channelUpdate', 'channelId': 4000, 'channelName': 'Latest'})
    second, _, _ = backend.take_channel_changes(limit=2000)
    third, _, _ = backend.take_channel_changes(limit=2000)
    assert len(second) == 2000 and len(third) == 1000
    assert third[4000].name == 'Latest'
    assert backend.pending_channel_count == 0


def test_synced_dvr_entries_never_connects():
    from tvhplayer.core.htsp_backend import HtspBackend
    from tvhplayer.core.models import ServerConfig

    backend = HtspBackend(ServerConfig.from_dict({'url': 'http://127.0.0.1:1', 'protocol': 'htsp', 'htsp_port': 1}))
    backend._conn.connect = lambda: (_ for _ in ()).throw(AssertionError('must not connect'))
    assert backend.synced_dvr_entries() is None
    backend._metadata = True
    backend._metadata_requested = True
    backend._conn._sock = object()
    backend._dvr = {7: 'entry'}
    assert backend.synced_dvr_entries() == ['entry']
    backend._conn._sock = None
    assert backend.synced_dvr_entries() is None

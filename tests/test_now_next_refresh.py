"""Regressions for periodic Now/Next updates without a full HTSP metadata sync."""

from tvhplayer.core.backend import TvhBackend
from tvhplayer.core.channel_info import NowNext
from tvhplayer.core.models import Channel, EpgEvent
from tvhplayer.tvhplayer import NowNextFetch


def _channel(event_id):
    return Channel.from_raw({
        'channelId': 42, 'channelIdStr': 'channel', 'channelName': 'Channel',
        'eventId': event_id, 'nextEventId': event_id + 1,
    })


def test_background_refresh_uses_lightweight_now_grid_without_sync():
    old = _channel(100)
    answer = {'channel': NowNext()}
    calls = []

    class Backend:
        def get_channels(self):
            raise AssertionError('Periodic refresh must not start HTSP metadata sync')

        def get_now_next(self, channels):
            raise AssertionError('Must not use stale channel event IDs')

        def get_now_next_live(self, channels):
            calls.append(('now-grid', channels))
            assert channels == [old]
            return answer

        def close(self):
            calls.append(('close',))

    fetch = NowNextFetch(
        {'url': 'http://localhost:9981'}, [old],
        open_backend=lambda _: Backend(),
    )
    completed = []
    fetch.done.connect(lambda key, data: completed.append((key, data)))
    fetch._run()

    assert calls == [('now-grid', [old]), ('close',)]
    assert completed == [('http://localhost:9981', answer)]


def test_live_now_grid_uses_current_events_not_stale_htsp_event_ids():
    old = _channel(100)
    current = EpgEvent(
        start=1200, stop=1800, title='New programme',
        event_id=200, channel_uuid='channel', next_event_id=201,
    )
    following = EpgEvent(
        start=1800, stop=2400, title='Following programme',
        event_id=201, channel_uuid='channel',
    )
    calls = []

    class Backend:
        def query_epg(self, query):
            calls.append(('grid', query.mode, query.limit))
            assert query.mode == 'now'
            return [current]

        def load_events(self, ids):
            calls.append(('load', ids))
            return [following]

        def get_channels(self):
            raise AssertionError('A now-grid request does not need channel metadata')

    result = TvhBackend.get_now_next_live(Backend(), [old])
    assert result['channel'].now is current
    assert result['channel'].next is following
    assert calls == [('grid', 'now', 10000), ('load', [201])]


def test_background_refresh_failure_does_not_query_stale_ids():
    calls = []

    class Backend:
        def get_channels(self):
            raise AssertionError('No metadata sync on this connection')

        def get_now_next(self, channels):
            raise AssertionError('Do not fall back to stale event IDs on failure')

        def get_now_next_live(self, channels):
            raise RuntimeError('EPG unavailable')

        def close(self):
            calls.append('close')

    fetch = NowNextFetch(
        {'url': 'http://localhost:9981'}, [_channel(100)],
        open_backend=lambda _: Backend(),
    )
    completed = []
    fetch.done.connect(lambda key, data: completed.append(data))
    fetch._run()

    assert calls == ['close']
    assert completed == [None]


def test_background_refresh_falls_back_for_older_backend_implementations():
    """Test doubles and third-party backends can still implement get_now_next only."""
    old = _channel(100)
    result = {'channel': NowNext()}
    calls = []

    class Backend:
        def get_channels(self):
            raise AssertionError('Do not resync channels')

        def get_now_next(self, channels):
            assert channels == [old]
            calls.append('get_now_next')
            return result

        def close(self):
            calls.append('close')

    fetch = NowNextFetch(
        {'url': 'http://localhost:9981'}, [old],
        open_backend=lambda _: Backend(),
    )
    fetch._run()
    assert calls == ['get_now_next', 'close']

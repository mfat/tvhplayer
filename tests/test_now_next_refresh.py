"""Regressions for background Now/Next updates when programmes roll over."""

from tvhplayer.core.channel_info import NowNext
from tvhplayer.core.models import Channel
from tvhplayer.tvhplayer import NowNextFetch


def test_background_now_next_uses_fresh_channel_event_ids():
    """A loaded channel may still carry last programme's HTSP eventId."""
    old = Channel.from_raw({
        'channelId': 42, 'channelIdStr': 'channel', 'channelName': 'Channel',
        'eventId': 100, 'nextEventId': 101,
    })
    fresh = Channel.from_raw({
        'channelId': 42, 'channelIdStr': 'channel', 'channelName': 'Channel',
        'eventId': 200, 'nextEventId': 201,
    })
    now_next = {'channel': NowNext()}
    calls = []

    class Backend:
        def get_channels(self):
            calls.append('get_channels')
            return [fresh]

        def get_now_next(self, channels):
            calls.append(('get_now_next', channels[0].raw['eventId']))
            assert channels == [fresh]
            return now_next

        def close(self):
            calls.append('close')

    fetch = NowNextFetch(
        {'url': 'http://localhost:9981'}, [old],
        open_backend=lambda _: Backend(),
    )
    answers = []
    fetch.done.connect(lambda key, data: answers.append((key, data)))
    fetch._run()  # Synchronous worker invocation; no server required.

    assert calls == ['get_channels', ('get_now_next', 200), 'close']
    assert answers == [('http://localhost:9981', now_next)]


def test_background_refresh_does_not_use_stale_ids_if_channel_fetch_fails():
    calls = []

    class Backend:
        def get_channels(self):
            raise RuntimeError('Channel metadata unavailable')

        def get_now_next(self, channels):
            raise AssertionError('Must not fetch events using old channel metadata')

        def close(self):
            calls.append('close')

    fetch = NowNextFetch(
        {'url': 'http://localhost:9981'}, [],
        open_backend=lambda _: Backend(),
    )
    answers = []
    fetch.done.connect(lambda key, data: answers.append(data))
    fetch._run()

    assert calls == ['close']
    assert answers == [None]

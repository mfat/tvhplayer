from tvhplayer.core.models import SubscriptionStatus
from tvhplayer.core.playback_status import (
    NOT_WORKING,
    RECEIVING,
    RETRYING,
    SLOW,
    STARTING,
    WAITING,
    find_subscription,
    starting_caption,
)


def _sub(state, channel='TBN', title='HTTP', start=1, received=0):
    return SubscriptionStatus(channel=channel, title=title, state=state, start=start, raw={'in': received})


def test_the_newest_stream_subscription_for_the_channel_is_used():
    subs = [_sub('Running', start=1), _sub('Testing', start=5), _sub('Testing', title='scan', start=9),
            _sub('Running', channel='Other', start=9)]
    assert find_subscription(subs, 'TBN') is subs[1]
    assert find_subscription(subs, 'Missing') is None


def test_captions_follow_the_server_state():
    assert starting_caption(None, 0, False) == (STARTING, False)
    assert starting_caption(_sub('Testing'), 2, False) == (WAITING, False)
    assert starting_caption(_sub('Testing'), 12, False) == (SLOW, False)
    assert starting_caption(_sub('Bad'), 16, False) == (RETRYING, False)
    assert starting_caption(_sub('Testing'), 18, True) == (RETRYING, False)
    assert starting_caption(_sub('Testing', received=188), 20, True) == (RECEIVING, False)
    assert starting_caption(_sub('Running'), 70, True) == (RECEIVING, False)
    assert starting_caption(_sub('Testing'), 60, True) == (NOT_WORKING, True)

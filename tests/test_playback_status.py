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


def test_vlc_titled_streams_are_found():
    from tvhplayer.core.playback_status import is_player_stream

    subs = [_sub('Running', title='Lavf/62.3.100', start=9), _sub('Testing', title='VLC/3.0.23 LibVLC/3.0.23', start=5)]
    assert find_subscription(subs, 'TBN') is subs[1]
    assert not is_player_stream(_sub('Running', title='DVR'))


def test_the_tuner_of_a_subscription_and_its_signal():
    from tvhplayer.core.models import InputStatus
    from tvhplayer.core.playback_status import (
        SIGNAL_FAIR,
        SIGNAL_GOOD,
        SIGNAL_NONE,
        SIGNAL_POOR,
        find_tuner,
        signal_report,
    )

    sub = SubscriptionStatus(channel='BBC ONE', title='HTTP', service='Si2168 #0 : DVB-T #0/Freeview/482MHz/BBC ONE')
    other = InputStatus(name='Si2168 #1 : DVB-T #1', stream='506MHz in Freeview')
    tuner = InputStatus(name='Si2168 #0 : DVB-T #0', stream='482MHz in Freeview', snr=22000, snr_scale=2, bps=1)
    assert find_tuner(sub, [other, tuner]) is tuner
    assert find_tuner(SubscriptionStatus(service='IPTV'), [tuner]) is None
    assert find_tuner(None, [tuner]) is None

    assert signal_report(tuner) == (SIGNAL_GOOD, 'Signal good (SNR 22 dB)')
    tuner.unc = 4
    assert signal_report(tuner)[0] == SIGNAL_FAIR
    assert signal_report(InputStatus(snr=10000, snr_scale=2, bps=1))[0] == SIGNAL_FAIR
    assert signal_report(InputStatus(snr=5000, snr_scale=2, bps=1))[0] == SIGNAL_POOR
    assert signal_report(InputStatus(snr=5000, snr_scale=2, bps=0))[0] == SIGNAL_NONE
    assert signal_report(InputStatus(signal=0, signal_scale=1, snr=0, snr_scale=1))[0] == SIGNAL_NONE
    assert signal_report(InputStatus(signal=50000, signal_scale=1, bps=1)) == (SIGNAL_GOOD, 'Signal good (strength 76%)')
    assert signal_report(InputStatus(name='IPTV', signal=0, signal_scale=0)) is None
    assert signal_report(None) is None



def test_the_log_says_why_this_stream_did_not_start():
    from tvhplayer.core.playback_status import stream_path, stream_reason

    path = stream_path('http://user:pw@tv.local:9981/tvh/stream/channel/abc123?profile=pass')
    assert path == '/tvh/stream/channel/abc123'
    line = "2026-10-26 12:00:01.123 webui: Couldn't start streaming /tvh/stream/channel/abc123?profile=pass, No free adapter"
    assert stream_reason(line, path) == 'No free adapter'
    assert stream_reason(line, '/tvh/stream/channel/other') is None
    assert stream_reason('2026-10-26 12:00:01 subscription: 0001: something else', path) is None


def test_the_log_says_why_a_stream_stopped():
    from tvhplayer.core.playback_status import stream_reason

    path = '/stream/channelid/42'
    assert stream_reason('t webui: Stop streaming /stream/channelid/42, Subscription overridden', path) == \
        'Subscription overridden'
    assert stream_reason(
        't webui: Stop streaming /stream/channelid/42, timeout (20 secs) waiting for data packets to start', path
    ) == 'timeout (20 secs) waiting for data packets to start'
    assert stream_reason('t webui: Stop streaming /stream/channelid/42, User request', path) is None
    assert stream_reason('t webui: Stop streaming /stream/channelid/42, client hung up', path) is None


def test_an_undecodable_service_named_like_the_channel_is_reported():
    from tvhplayer.core.playback_status import scrambled_notice

    line = 't descrambler: cannot decode packets for service "BBC One HD"'
    assert scrambled_notice(line, 'bbc one hd') == 'cannot decode packets for service "BBC One HD"'
    assert scrambled_notice(line, 'BBC Two HD') is None

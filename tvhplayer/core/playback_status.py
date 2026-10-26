"""Words for a channel that is starting, from Tvheadend's subscription status. No Qt imports.

Tvheadend shows a stream subscription as ``Testing`` until its source sends
data, ``Running`` once it does, and ``Bad`` when the source stayed silent
past the network's timeout; it then tries the source again.

Why a stream did not start, or stopped, is only in the server's log, in
``webui`` lines that name the stream's path. The app shows those reasons in
the server's own words.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple
from urllib.parse import urlsplit

from .models import InputStatus, SubscriptionStatus

STARTING = 'Starting…'
WAITING = 'Waiting for channel'
SLOW = 'This channel is slow to start. Still waiting…'
RECEIVING = 'Receiving the channel…'
RETRYING = 'The channel is not answering. Trying again…'
NOT_WORKING = 'This channel is not working right now.'

SLOW_SECONDS = 10
GIVE_UP_SECONDS = 60

# Signal levels, worst last. The words go with the colour, so it is not colour alone.
SIGNAL_GOOD = 'good'
SIGNAL_FAIR = 'fair'
SIGNAL_POOR = 'poor'
SIGNAL_NONE = 'none'
# SNR in dB, and relative readings in percent, at or above which the signal is good or fair.
SNR_DB_GOOD = 15
SNR_DB_FAIR = 8
PERCENT_GOOD = 60
PERCENT_FAIR = 35
RELATIVE_FULL = 65535


def is_player_stream(subscription: SubscriptionStatus) -> bool:
    """A stream opened by the player. Older Tvheadend titles it HTTP, newer ones after the player."""
    title = subscription.title or ''
    return title == 'HTTP' or title.startswith('VLC/') or 'LibVLC' in title


def find_subscription(subscriptions: Iterable[SubscriptionStatus], channel_name: str) -> Optional[SubscriptionStatus]:
    """The newest player stream subscription for this channel."""
    matches = [sub for sub in subscriptions if is_player_stream(sub) and sub.channel == channel_name]
    return max(matches, key=lambda sub: (sub.start, sub.id or 0), default=None)


def find_tuner(subscription: Optional[SubscriptionStatus], inputs: Iterable[InputStatus]) -> Optional[InputStatus]:
    """The input a subscription is tuned with.

    Tvheadend names the service ``input/network/mux/service`` and the input's
    stream ``mux in network``.
    """
    if subscription is None or not subscription.service:
        return None
    parts = [part.strip() for part in subscription.service.split('/')]
    if len(parts) < 4:
        return None
    network, mux = parts[-3], parts[-2]
    adapter = '/'.join(parts[:-3])
    inputs = list(inputs)
    stream = f'{mux} in {network}'
    for tuner in inputs:
        if tuner.stream == stream and (not adapter or tuner.name == adapter):
            return tuner
    return next((tuner for tuner in inputs if tuner.stream == stream), None)


def _percent(value) -> int:
    return round(int(value) * 100 / RELATIVE_FULL)


def signal_report(tuner: Optional[InputStatus]) -> Optional[Tuple[str, str]]:
    """``(level, words)`` for a tuner's reception, or None when it gives no reading, as IPTV does."""
    if tuner is None:
        return None
    if tuner.snr_scale == 2 and tuner.snr is not None:
        snr = tuner.snr / 1000
        if snr >= SNR_DB_GOOD:
            level = SIGNAL_GOOD
        elif snr >= SNR_DB_FAIR:
            level = SIGNAL_FAIR
        else:
            level = SIGNAL_POOR
        reading = f'SNR {snr:.0f} dB'
    elif tuner.snr_scale == 1 and tuner.snr is not None:
        level = _level_from_percent(_percent(tuner.snr))
        reading = f'quality {_percent(tuner.snr)}%'
    elif tuner.signal_scale == 1 and tuner.signal is not None:
        level = _level_from_percent(_percent(tuner.signal))
        reading = f'strength {_percent(tuner.signal)}%'
    else:
        return None
    readings = [value for value, scale in ((tuner.signal, tuner.signal_scale), (tuner.snr, tuner.snr_scale)) if scale]
    # Nothing at all, or too weak for any data to come through.
    if not any(readings) or (level == SIGNAL_POOR and not tuner.bps):
        return SIGNAL_NONE, 'No signal: check the aerial, dish, or cable'
    if level == SIGNAL_GOOD and tuner.unc:
        level = SIGNAL_FAIR
    words = {
        SIGNAL_GOOD: f'Signal good ({reading})',
        SIGNAL_FAIR: f'Signal weak ({reading}): the picture may break up',
        SIGNAL_POOR: f'Signal too weak ({reading}): check the aerial, dish, or cable',
    }[level]
    return level, words


def _level_from_percent(percent: int) -> str:
    if percent >= PERCENT_GOOD:
        return SIGNAL_GOOD
    if percent >= PERCENT_FAIR:
        return SIGNAL_FAIR
    return SIGNAL_POOR


def receiving(subscription: Optional[SubscriptionStatus]) -> bool:
    if subscription is None:
        return False
    return subscription.state == 'Running' or (subscription.get('in') or 0) > 0


def starting_caption(subscription: Optional[SubscriptionStatus], elapsed: float, retried: bool) -> Tuple[str, bool]:
    """Caption for the spinner, and whether to stop waiting.

    ``retried`` says the server already gave up on the source once during this start.
    """
    if receiving(subscription):
        return RECEIVING, False
    if elapsed >= GIVE_UP_SECONDS:
        return NOT_WORKING, True
    if subscription is not None and subscription.state == 'Bad':
        return RETRYING, False
    if retried:
        return RETRYING, False
    if subscription is None:
        return STARTING, False
    return (SLOW if elapsed >= SLOW_SECONDS else WAITING), False



# Not a problem: the player or a person ended the stream.
_NOT_A_PROBLEM = {'OK', 'Forced OK', 'User request', 'Aborted by user', 'client hung up', 'Source reconfigured'}

_STREAM_LINE = re.compile(r"webui: (?:Couldn't start|Stop) streaming (\S+), (.+?)\s*$")
_UNDECODABLE = re.compile(r'descrambler: (cannot decode packets for service "(.*)")\s*$')


def stream_path(url: str) -> str:
    """The part of a stream URL that the server's log names the stream by."""
    return urlsplit(url or '').path


def stream_reason(line: str, path: str) -> Optional[str]:
    """Tvheadend's reason the stream at ``path`` did not start or stopped, from one log line.

    None when the line is about another stream, or the stream ended on request.
    """
    match = _STREAM_LINE.search(line or '')
    if match is None or not path or urlsplit(match.group(1)).path != path:
        return None
    reason = match.group(2)
    return None if reason in _NOT_A_PROBLEM else reason


def scrambled_notice(line: str, channel_name: str) -> Optional[str]:
    """The server's words when it cannot decode a service named like the channel.

    Tvheadend names services this way by default.
    """
    match = _UNDECODABLE.search(line or '')
    if match is None or not channel_name or match.group(2).casefold() != channel_name.casefold():
        return None
    return match.group(1)

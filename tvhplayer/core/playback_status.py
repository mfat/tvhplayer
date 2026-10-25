"""Words for a channel that is starting, from Tvheadend's subscription status. No Qt imports.

Tvheadend shows a stream subscription as ``Testing`` until its source sends
data, ``Running`` once it does, and ``Bad`` when the source stayed silent
past the network's timeout; it then tries the source again.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from .models import SubscriptionStatus

STARTING = 'Starting…'
WAITING = 'Waiting for channel'
SLOW = 'This channel is slow to start. Still waiting…'
RECEIVING = 'Receiving the channel…'
RETRYING = 'The channel is not answering. Trying again…'
NOT_WORKING = 'This channel is not working right now.'

SLOW_SECONDS = 10
GIVE_UP_SECONDS = 60


def find_subscription(subscriptions: Iterable[SubscriptionStatus], channel_name: str) -> Optional[SubscriptionStatus]:
    """The newest web stream subscription for this channel."""
    matches = [sub for sub in subscriptions if sub.title == 'HTTP' and sub.channel == channel_name]
    return max(matches, key=lambda sub: (sub.start, sub.id or 0), default=None)


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

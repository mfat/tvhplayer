"""When the computer must not go to sleep. No Qt imports.

A recording made on this computer is lost if the computer sleeps: one written
by TVHplayer itself, or one a Tvheadend on this computer writes (the built-in
server, or a local instance at a loopback address). A recording on a server
somewhere else does not care.
"""

from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import urlparse

from .builtin_server import is_builtin_server

LOOPBACK_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})

LOCAL_REASON = 'Recording to this computer'
SERVER_REASON = 'Recording on the server on this computer'
SCHEDULED_REASON = 'A recording is scheduled on the server on this computer'


def server_on_this_computer(server) -> bool:
    if not server:
        return False
    if is_builtin_server(server):
        return True
    try:
        host = urlparse((server.get('url') or '').strip()).hostname or ''
    except ValueError:
        return False
    return host.lower() in LOOPBACK_HOSTS or host.startswith('127.')


def awake_reason(
    entries: Optional[Iterable] = None,
    now: int = 0,
    local_recording: bool = False,
    keep_for_scheduled: bool = True,
) -> str:
    """Why the computer has to stay awake, or '' when it may sleep.

    ``entries`` are DVR entries of servers on this computer. A scheduled one
    counts until it ends, so a recording that starts while nobody uses the
    computer still finds it awake.
    """
    if local_recording:
        return LOCAL_REASON
    entries = list(entries or [])
    if any(entry.category() == 'recording' for entry in entries):
        return SERVER_REASON
    if keep_for_scheduled:
        for entry in entries:
            if entry.category() != 'upcoming':
                continue
            if int(entry.start or 0) + int(entry.duration or 0) > now:
                return SCHEDULED_REASON
    return ''

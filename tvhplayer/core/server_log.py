"""Live log of a remote Tvheadend server. No Qt imports.

The web UI's log panel reads ``logmessage`` notifications from
``/comet/poll``. The first poll opens a mailbox and returns its ``boxid``
plus an ``accessUpdate`` that says whether this login is an admin.
Later polls pass the ``boxid`` and wait up to about ten seconds for news.
Tvheadend sends log lines only to admin logins, and only lines logged after
the mailbox opened. An expired ``boxid`` gets a new mailbox.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from .errors import TvhAuthError, TvhConnectionError, TvhError
from .proxy import configure_session
from .urls import http_auth, http_base_url

# Longer than the server's own wait, so a quiet server is not a timeout.
POLL_TIMEOUT = 30


@dataclass
class LogPoll:
    lines: List[str] = field(default_factory=list)
    # None until the server says; it says on every new mailbox.
    admin: Optional[bool] = None


class ServerLogFeed:
    def __init__(self, server):
        server = server.to_dict() if hasattr(server, 'to_dict') else dict(server or {})
        self._base = http_base_url(server.get('url'))
        self._auth = http_auth(server)
        self._session = requests.Session()
        configure_session(self._session, self._base)
        self._boxid = ''

    def close(self):
        self._session.close()

    def poll(self) -> LogPoll:
        """Return the log lines since the last poll. Waits when there are none."""
        data = {'boxid': self._boxid, 'immediate': '0'} if self._boxid else {'immediate': '1'}
        try:
            response = self._session.post(
                f'{self._base}/comet/poll', data=data, auth=self._auth, timeout=POLL_TIMEOUT
            )
        except requests.RequestException as exc:
            raise TvhConnectionError(str(exc)) from exc
        if response.status_code in (401, 403):
            raise TvhAuthError(f'HTTP {response.status_code} for comet/poll')
        if response.status_code >= 400:
            raise TvhError(f'HTTP {response.status_code} for comet/poll')
        try:
            payload = json.loads(response.text, strict=False)
        except ValueError as exc:
            raise TvhError('Invalid JSON from comet/poll') from exc
        self._boxid = str(payload.get('boxid') or '')
        result = LogPoll()
        for message in payload.get('messages') or []:
            if not isinstance(message, dict):
                continue
            kind = message.get('notificationClass')
            if kind == 'logmessage' and message.get('logtxt'):
                result.lines.append(str(message['logtxt']))
            elif kind == 'accessUpdate':
                result.admin = bool(message.get('admin'))
        return result

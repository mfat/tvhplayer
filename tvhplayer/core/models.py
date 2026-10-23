from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PROTOCOL_HTTP = 'http'
PROTOCOL_HTSP = 'htsp'


@dataclass
class ServerConfig:
    name: str
    url: str
    username: str = ''
    password: str = ''
    protocol: str = PROTOCOL_HTTP
    htsp_port: int = 9982

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        protocol = (data.get('protocol') or PROTOCOL_HTTP).lower()
        if protocol not in (PROTOCOL_HTTP, PROTOCOL_HTSP):
            protocol = PROTOCOL_HTTP
        try:
            htsp_port = int(data.get('htsp_port') or 9982)
        except (TypeError, ValueError):
            htsp_port = 9982
        return cls(
            name=data.get('name') or '',
            url=data.get('url') or '',
            username=data.get('username') or '',
            password=data.get('password') or '',
            protocol=protocol,
            htsp_port=htsp_port,
        )

    def to_dict(self):
        return {
            'name': self.name,
            'url': self.url,
            'username': self.username,
            'password': self.password,
            'protocol': self.protocol,
            'htsp_port': self.htsp_port,
        }


@dataclass
class Channel:
    uuid: str
    name: str
    number: int = 0
    htsp_id: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_raw(self):
        """Shape expected by the existing table UserRole payload."""
        data = dict(self.raw)
        data['uuid'] = self.uuid
        data['name'] = self.name
        data['number'] = self.number
        if self.htsp_id is not None:
            data['htsp_id'] = self.htsp_id
        return data

    @classmethod
    def from_raw(cls, data):
        data = data or {}
        htsp_id = data.get('htsp_id')
        if htsp_id is None:
            htsp_id = data.get('channelId')
        try:
            htsp_id = int(htsp_id) if htsp_id is not None else None
        except (TypeError, ValueError):
            htsp_id = None
        number = data.get('number', data.get('channelNumber', 0)) or 0
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = 0
        return cls(
            uuid=str(data.get('uuid') or data.get('channelIdStr') or ('' if htsp_id is None else htsp_id)),
            name=data.get('name') or data.get('channelName') or 'Unknown Channel',
            number=number,
            htsp_id=htsp_id,
            raw=data,
        )


@dataclass
class EpgEvent:
    start: int
    stop: int
    title: str
    description: str = ''
    channel_uuid: str = ''
    event_id: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DvrEntry:
    uuid: str
    title: str
    channel_name: str
    start: int
    duration: int
    status: str = ''
    sched_status: str = ''
    errors: int = 0
    errorcode: int = 0
    error: str = ''
    htsp_id: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def category(self):
        """Bucket used by the DVR status dialog: recording, upcoming, finished, failed."""
        status = self.status or ''
        sched = (self.sched_status or '').lower()
        status_l = status.lower()
        # sched_status "recording" covers Running plus the in-progress labels
        # Tvheadend uses before the file is open ("Waiting for stream",
        # "Commercial break", and so on). Those must not be treated as upcoming.
        if sched == 'recording' or status == 'Running' or status_l in (
            'recording',
            'running',
            'waiting for stream',
            'waiting for program start',
            'commercial break',
            'waiting for epg running flag',
        ):
            return 'recording'
        if self.errors or self.errorcode or 'failed' in status_l or 'invalid' in status_l or 'error' in status_l or 'missed' in status_l:
            return 'failed'
        if 'completed' in status_l or status_l == 'finished':
            return 'finished'
        if 'scheduled' in status_l or sched == 'scheduled':
            return 'upcoming'
        return 'upcoming'

    def matches_channel(self, channel) -> bool:
        """True when this DVR entry is for the given channel."""
        if channel is None:
            return False
        raw = self.raw or {}
        raw_channel = raw.get('channel')
        raw_id = _as_int(raw_channel)
        channel_id = _as_int(getattr(channel, 'htsp_id', None))
        if raw_id is not None and channel_id is not None:
            return raw_id == channel_id
        channel_uuid = str(getattr(channel, 'uuid', '') or '')
        if raw_channel not in (None, '') and channel_uuid and raw_id is None:
            return str(raw_channel) == channel_uuid
        target = (getattr(channel, 'name', None) or '').strip().casefold()
        if not target:
            return False
        for candidate in (self.channel_name, raw.get('channelName'), raw.get('channelname')):
            if candidate and str(candidate).strip().casefold() == target:
                return True
        return False


def recordings_to_stop(entries, channel=None):
    """Running jobs the Stop button should end.

    One running job is stopped on its own. Several running jobs are narrowed
    to the active channel so the others keep recording.
    """
    running = [entry for entry in entries if entry.category() == 'recording']
    if len(running) <= 1:
        return running
    if channel is None:
        return []
    return [entry for entry in running if entry.matches_channel(channel)]


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


@dataclass
class ServerInfo:
    name: str = ''
    version: str = ''
    api_version: str = ''
    capabilities: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

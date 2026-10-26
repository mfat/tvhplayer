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
    protocol: str = PROTOCOL_HTSP
    htsp_port: int = 9982
    builtin: bool = False

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        # A saved server with no protocol is from before HTSP support: it used HTTP.
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
            builtin=bool(data.get('builtin')),
        )

    def to_dict(self):
        return {
            'name': self.name,
            'url': self.url,
            'username': self.username,
            'password': self.password,
            'protocol': self.protocol,
            'htsp_port': self.htsp_port,
            'builtin': self.builtin,
        }


def _optional_int(value):
    if isinstance(value, bool) or value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _id_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    ids = []
    for item in value:
        if isinstance(item, dict):
            item = item.get('uuid') or item.get('tagId') or item.get('channelId') or item.get('id')
        if item in (None, ''):
            continue
        ids.append(str(item))
    return ids


def _enabled_flag(data, default=True) -> bool:
    if not isinstance(data, dict) or 'enabled' not in data:
        return default
    value = data.get('enabled')
    if isinstance(value, str):
        return value.strip().lower() not in ('0', 'false', 'no', '')
    return bool(value)


@dataclass
class Channel:
    uuid: str
    name: str
    number: int = 0
    htsp_id: Optional[int] = None
    icon: str = ''
    tag_ids: List[str] = field(default_factory=list)
    number_minor: Optional[int] = None
    enabled: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_raw(self):
        """Shape expected by the existing table UserRole payload."""
        data = dict(self.raw)
        data['uuid'] = self.uuid
        data['name'] = self.name
        data['number'] = self.number
        if self.htsp_id is not None:
            data['htsp_id'] = self.htsp_id
        if self.icon:
            data['icon'] = self.icon
        if self.tag_ids:
            data['tags'] = list(self.tag_ids)
        if self.number_minor is not None:
            data['number_minor'] = self.number_minor
        data['enabled'] = self.enabled
        return data

    @classmethod
    def from_raw(cls, data):
        data = data or {}
        htsp_id = data.get('htsp_id')
        if htsp_id is None:
            htsp_id = data.get('channelId')
        htsp_id = _optional_int(htsp_id)
        number = _optional_int(data.get('number', data.get('channelNumber', 0))) or 0
        return cls(
            uuid=str(data.get('uuid') or data.get('channelIdStr') or ('' if htsp_id is None else htsp_id)),
            name=data.get('name') or data.get('channelName') or 'Unknown Channel',
            number=number,
            htsp_id=htsp_id,
            icon=str(data.get('icon') or data.get('channelIcon') or ''),
            tag_ids=_id_list(data.get('tags')),
            number_minor=_optional_int(data.get('number_minor', data.get('channelNumberMinor'))),
            enabled=_enabled_flag(data),
            raw=data,
        )


@dataclass
class ChannelTag:
    """One channel tag from ``channeltag/grid`` or HTSP ``tagAdd``.

    HTTP ``uuid`` matches ``Channel.tag_ids``. HTSP ``tag_ids`` are the
    decimal ``tagId`` and match ``str(htsp_id)``. ``tagIdStr`` is ``uuid``
    when the server sends it.
    """

    uuid: str
    name: str = ''
    index: int = 0
    icon: str = ''
    member_ids: List[str] = field(default_factory=list)
    htsp_id: Optional[int] = None
    enabled: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EpgEvent:
    """One programme. Times are Unix seconds. ``genre`` values are ETSI content nibbles.

    Image fields are Tvheadend references such as ``imagecache/38``, not
    fetched bytes. ``description`` falls back to ``summary`` when the
    event has no long description.
    """

    start: int
    stop: int
    title: str
    description: str = ''
    channel_uuid: str = ''
    event_id: Optional[int] = None
    subtitle: str = ''
    summary: str = ''
    channel_name: str = ''
    channel_number: int = 0
    genre: List[int] = field(default_factory=list)
    image: str = ''
    image_poster: str = ''
    image_backdrop: str = ''
    image_still: str = ''
    serieslink_uri: str = ''
    episode_uri: str = ''
    next_event_id: Optional[int] = None
    dvr_uuid: str = ''
    dvr_state: str = ''
    widescreen: bool = False
    subtitled: bool = False
    hd: bool = False
    age_rating: Optional[int] = None
    rating_label: str = ''
    rating_label_icon: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EpgQuery:
    """Filters for ``query_epg``. ``None`` means that parameter is not sent.

    ``channel`` is a ``Channel``. ``channel_tag`` is a ``ChannelTag``.
    ``mode`` is ``now`` or omitted. ``limit`` is a row count and ``offset``
    is the grid start index (HTTP ``start``), not a programme time.
    ``fulltext`` asks HTTP for an exact title match. ``ends_after`` and
    ``starts_before`` are Unix seconds that keep programmes overlapping
    that span; they go to the HTTP grid as start/stop filters.
    """

    title: Optional[str] = None
    fulltext: Optional[bool] = None
    channel: Optional[Channel] = None
    channel_tag: Optional[ChannelTag] = None
    content_type: Optional[int] = None
    duration_min: Optional[int] = None
    duration_max: Optional[int] = None
    mode: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    lang: Optional[str] = None
    ends_after: Optional[int] = None
    starts_before: Optional[int] = None


@dataclass
class ContentType:
    """One genre id from ``epg/content_type/list``. ``key`` 0 is the empty type."""

    key: int
    name: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamProfile:
    """A streaming profile (``pass``, ``matroska``, and the server's own names)."""

    uuid: str
    name: str = ''
    comment: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)


class RawGet:
    """Dict-style lookup of the server payload stored on ``raw``."""

    def get(self, key, default=None):
        raw = getattr(self, 'raw', None) or {}
        if isinstance(raw, dict):
            return raw.get(key, default)
        return default


@dataclass
class InputStatus(RawGet):
    """One tuner row from ``status/inputs``.

    ``signal_scale`` and ``snr_scale`` are ``1`` for a relative reading
    (65535 = 100%), ``2`` for absolute (1000 = 1 dB), and ``0`` when the
    reading is not valid. ``.get()`` reads the original JSON keys, including
    ``input``.
    """

    name: str = ''
    uuid: str = ''
    signal: Optional[int] = None
    signal_scale: int = 0
    snr: Optional[int] = None
    snr_scale: int = 0
    stream: str = ''
    weight: Optional[int] = None
    subscribers: Optional[int] = None
    ber: Optional[int] = None
    unc: Optional[int] = None
    bps: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectionStatus(RawGet):
    """One client connection from ``status/connections``. ``kind`` is the JSON ``type``."""

    id: Optional[int] = None
    peer: str = ''
    user: str = ''
    started: int = 0
    kind: str = ''
    server: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubscriptionStatus(RawGet):
    """One live subscription from ``status/subscriptions``.

    ``channel`` is a display string. ``.get('channel')`` still returns the
    original value, which may be a dict.
    """

    id: Optional[int] = None
    channel: str = ''
    username: str = ''
    title: str = ''
    service: str = ''
    state: str = ''
    start: int = 0
    errors: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServerActivity(RawGet):
    """Wake-up summary from ``status/activity`` (Tvheadend 4.3-2405 and later).

    Times are Unix seconds. ``0`` means that activity has nothing scheduled.
    ``activities`` keys are ``dvr``, ``ota_grabber``, ``int_grabber``, and
    ``mux_scheduler`` when the server sends them.
    """

    current_time: int = 0
    next_activity: int = 0
    activities: Dict[str, int] = field(default_factory=dict)
    subscription_count: int = 0
    connection_count: int = 0
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


@dataclass
class DvrEntryUpdate:
    """Fields to change on one DVR entry. ``None`` leaves the stored value alone.

    ``start`` and ``stop`` are Unix timestamps in seconds.

    ``start_extra`` and ``stop_extra`` use the protocol's own unit. HTSP
    documents ``startExtra`` and ``stopExtra`` as minutes. HTTP writes the
    idnode fields ``start_extra`` and ``stop_extra`` unchanged.

    ``priority`` is sent as HTSP ``priority`` and HTTP ``pri``. HTSP defines
    0 important, 1 high, 2 normal, 3 low, 4 unimportant, and 5 not set.

    ``config_name`` is a DVR configuration name or UUID. ``channel`` is a
    ``Channel``: HTTP uses its UUID and HTSP uses its numeric channel id.
    """

    start: Optional[int] = None
    stop: Optional[int] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    comment: Optional[str] = None
    channel: Optional[Channel] = None
    start_extra: Optional[int] = None
    stop_extra: Optional[int] = None
    retention: Optional[int] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    config_name: Optional[str] = None


@dataclass
class DvrConfig:
    """One server DVR profile (HTTP ``dvr/config/grid``)."""

    uuid: str
    name: str = ''
    comment: str = ''
    storage: str = ''
    profile: str = ''
    enabled: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DvrCutpoint:
    """One HTSP cutpoint. ``type`` is 0 cut, 1 mute, 2 scene, 3 commercial break."""

    start_ms: int
    end_ms: int
    type: int
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return {
            0: 'cut',
            1: 'mute',
            2: 'scene',
            3: 'commercial',
        }.get(self.type, 'unknown')


@dataclass
class AutorecSpec:
    """Series-timer fields. ``None`` means do not send that field.

    ``days_of_week`` is the HTSP bitmask: Monday is ``0x01``, Sunday is
    ``0x40``. ``0`` means not set. HTTP receives the same days as a list of
    1–7 (Monday–Sunday).

    ``start`` and ``start_window`` are minutes from midnight, matching HTSP.
    ``start_extra`` and ``stop_extra`` are minutes on HTSP (``startExtra`` /
    ``stopExtra``). HTTP receives those integers as ``start_extra`` and
    ``stop_extra``.

    ``priority`` uses the HTSP scale documented on ``DvrEntryUpdate``. HTTP
    sends it as ``pri``. ``dup_detect`` is HTSP ``dupDetect`` only.
    ``broadcast_type`` is HTSP ``broadcastType`` and HTTP ``btype``.
    ``directory`` is sent only on HTSP.
    """

    title: Optional[str] = None
    enabled: Optional[bool] = None
    name: Optional[str] = None
    channel: Optional[Channel] = None
    fulltext: Optional[bool] = None
    directory: Optional[str] = None
    config_name: Optional[str] = None
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    days_of_week: Optional[int] = None
    priority: Optional[int] = None
    start: Optional[int] = None
    start_window: Optional[int] = None
    start_extra: Optional[int] = None
    stop_extra: Optional[int] = None
    comment: Optional[str] = None
    dup_detect: Optional[int] = None
    broadcast_type: Optional[int] = None


@dataclass
class AutorecEntry:
    """A series timer returned by ``dvr/autorec/grid``."""

    uuid: str
    title: str
    name: str = ''
    enabled: bool = True
    channel_uuid: str = ''
    comment: str = ''
    days_of_week: int = 0
    priority: Optional[int] = None
    min_duration: int = 0
    max_duration: int = 0
    htsp_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimerecSpec:
    """Time-based timer fields. ``None`` means do not send that field.

    ``start`` and ``stop`` are minutes from midnight (HTSP). HTTP receives
    ``HH:MM``. ``days_of_week`` and ``priority`` match ``AutorecSpec``.
    ``directory`` is sent only on HTSP.
    """

    title: Optional[str] = None
    name: Optional[str] = None
    enabled: Optional[bool] = None
    channel: Optional[Channel] = None
    directory: Optional[str] = None
    config_name: Optional[str] = None
    days_of_week: Optional[int] = None
    priority: Optional[int] = None
    start: Optional[int] = None
    stop: Optional[int] = None
    retention: Optional[int] = None
    comment: Optional[str] = None


@dataclass
class TimerecEntry:
    """A time-based timer returned by ``dvr/timerec/grid``."""

    uuid: str
    title: str
    name: str = ''
    enabled: bool = True
    channel_uuid: str = ''
    start_minute: Optional[int] = None
    stop_minute: Optional[int] = None
    retention: int = 0
    priority: Optional[int] = None
    days_of_week: int = 0
    comment: str = ''
    htsp_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

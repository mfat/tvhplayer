"""Extra per-channel details for the channel list. No Qt imports.

The list can show a logo, the programme on now and next, the kind of
service (radio, HD, UHD), encryption, and a recording mark. Which of
these show is a user setting stored under ``channel_list`` in the config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .models import Channel, ChannelTag, DvrEntry, EpgEvent, _optional_int

# Columns the user can show or hide. Name is always shown.
COLUMN_NUMBER = 'number'
COLUMN_NAME = 'name'
COLUMN_NOW = 'now'
COLUMN_NEXT = 'next'
COLUMN_TYPE = 'type'
COLUMN_STATUS = 'status'
OPTIONAL_COLUMNS = (COLUMN_NUMBER, COLUMN_NOW, COLUMN_NEXT, COLUMN_TYPE, COLUMN_STATUS)
# Left-to-right order the list starts with. The user can drag columns around.
DEFAULT_ORDER = (COLUMN_NUMBER, COLUMN_NAME, COLUMN_NOW, COLUMN_NEXT, COLUMN_TYPE, COLUMN_STATUS)

CHANNEL_LIST_DEFAULTS = {
    'columns': {
        COLUMN_NUMBER: True,
        COLUMN_NOW: True,
        COLUMN_NEXT: False,
        COLUMN_TYPE: False,
        COLUMN_STATUS: True,
    },
    'logos': True,
    'now_progress': True,
    'recording_status': True,
    'tag_filter': True,
    'hide_disabled': True,
    'tag': '',
    'order': list(DEFAULT_ORDER),
}

# DVB service_type values from the Tvheadend MPEGts API page.
_RADIO_TYPES = {0x02, 0x07, 0x0a}
_HD_TYPES = {0x11, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x91, 0xa0, 0xa4, 0xa6}
_UHD_TYPES = {0x1f}

KIND_RADIO = 'Radio'
KIND_SD = 'SD'
KIND_HD = 'HD'
KIND_UHD = 'UHD'
_KIND_RANK = {'': 0, KIND_SD: 1, KIND_RADIO: 2, KIND_HD: 3, KIND_UHD: 4}

# Names of the tags Tvheadend creates by itself ("TV channels", "SDTV", ...).
_TAG_KINDS = {'radio': KIND_RADIO, 'sdtv': KIND_SD, 'hdtv': KIND_HD, 'uhdtv': KIND_UHD, 'fhdtv': KIND_HD}


def channel_list_options(raw) -> dict:
    """Return the ``channel_list`` setting with every key present."""
    options = {
        key: (type(value)(value) if isinstance(value, (dict, list)) else value)
        for key, value in CHANNEL_LIST_DEFAULTS.items()
    }
    if not isinstance(raw, dict):
        return options
    columns = raw.get('columns')
    if isinstance(columns, dict):
        for key in OPTIONAL_COLUMNS:
            if key in columns:
                options['columns'][key] = bool(columns[key])
    for key in ('logos', 'now_progress', 'recording_status', 'tag_filter', 'hide_disabled'):
        if key in raw:
            options[key] = bool(raw[key])
    if isinstance(raw.get('tag'), str):
        options['tag'] = raw['tag']
    order = raw.get('order')
    if isinstance(order, list):
        known = [key for key in order if key in DEFAULT_ORDER]
        known = list(dict.fromkeys(known))
        options['order'] = known + [key for key in DEFAULT_ORDER if key not in known]
    return options


def channel_key(channel: Channel) -> str:
    """Stable id for one channel in the list: the UUID, else the HTSP id."""
    if channel.uuid:
        return str(channel.uuid)
    return '' if channel.htsp_id is None else str(channel.htsp_id)


def channel_icon_reference(channel: Channel) -> str:
    """Icon path the server can serve: the imagecache URL first, then the user icon.

    ``file://`` icons point at the server's own disk and cannot be loaded here.
    """
    raw = channel.raw or {}
    for value in (raw.get('icon_public_url'), channel.icon, raw.get('channelIcon')):
        value = str(value or '').strip()
        if value and not value.startswith('file:'):
            return value
    return ''


@dataclass
class NowNext:
    now: Optional[EpgEvent] = None
    next: Optional[EpgEvent] = None


def event_ids_for_channels(channels: Iterable[Channel]) -> List[int]:
    """Current and next event ids that HTSP sends with each channel."""
    ids = []
    for channel in channels:
        raw = channel.raw or {}
        for key in ('eventId', 'nextEventId'):
            event_id = _optional_int(raw.get(key))
            if event_id:
                ids.append(event_id)
    return ids


def next_event_ids(events: Iterable[EpgEvent]) -> List[int]:
    return [event.next_event_id for event in events if event.next_event_id]


def match_now_next(channels: Iterable[Channel], events: Iterable[EpgEvent]) -> Dict[str, NowNext]:
    """Pair each channel with its current and next programme.

    A channel's own ``eventId`` / ``nextEventId`` (HTSP) wins. Otherwise
    the current programme is the event whose ``channelUuid`` matches and
    whose time covers now, and the next one is its ``nextEventId``.
    """
    events = list(events)
    by_id = {event.event_id: event for event in events if event.event_id is not None}
    current_by_channel = {}
    for event in events:
        if event.channel_uuid:
            current_by_channel.setdefault(event.channel_uuid, []).append(event)
    result = {}
    for channel in channels:
        raw = channel.raw or {}
        now_event = by_id.get(_optional_int(raw.get('eventId')))
        if now_event is None:
            candidates = current_by_channel.get(channel.uuid) or []
            now_event = _current(candidates)
        next_event = by_id.get(_optional_int(raw.get('nextEventId')))
        if next_event is None and now_event is not None:
            next_event = by_id.get(now_event.next_event_id)
        if now_event is not None or next_event is not None:
            result[channel_key(channel)] = NowNext(now_event, next_event)
    return result


def _current(events):
    """Earliest-starting event among those for one channel."""
    if not events:
        return None
    return min(events, key=lambda event: event.start or 0)


def progress(event: Optional[EpgEvent], now: int) -> Optional[float]:
    """Share of ``event`` already shown, 0 to 1, or None without valid times."""
    if event is None or not event.start or not event.stop or event.stop <= event.start:
        return None
    return min(1.0, max(0.0, (now - event.start) / (event.stop - event.start)))


@dataclass
class ChannelKind:
    kind: str = ''
    encrypted: bool = False
    provider: str = ''

    def label(self) -> str:
        parts = [self.kind] if self.kind else []
        if self.encrypted:
            parts.append('Encrypted')
        return ', '.join(parts)


def _service_kind(value) -> str:
    """Kind from a DVB service_type number or an HTSP service type string."""
    if isinstance(value, str):
        text = value.strip().lower()
        if text.startswith('radio'):
            return KIND_RADIO
        if text.startswith('uhd'):
            return KIND_UHD
        if text.startswith(('hd', 'fhd')):
            return KIND_HD
        if text.startswith('sd'):
            return KIND_SD
        value = _optional_int(text)
    number = _optional_int(value)
    if number is None or number <= 0:
        return ''
    if number in _RADIO_TYPES:
        return KIND_RADIO
    if number in _UHD_TYPES:
        return KIND_UHD
    if number in _HD_TYPES:
        return KIND_HD
    return KIND_SD


def _better(current: str, candidate: str) -> str:
    return candidate if _KIND_RANK.get(candidate, 0) > _KIND_RANK.get(current, 0) else current


def channel_kinds(
    channels: Iterable[Channel],
    services: Iterable[dict] = (),
    tags: Iterable[ChannelTag] = (),
) -> Dict[str, ChannelKind]:
    """Kind, encryption, and provider for each channel.

    Sources, in order: HTSP ``services`` sent with the channel, HTTP
    ``mpegts/service/grid`` rows (``channel``, ``dvb_servicetype``,
    ``encrypted``, ``provider``), then the SDTV/HDTV/Radio tags Tvheadend
    adds on its own. A channel with several services takes the best kind.
    """
    by_service_channel: Dict[str, List[dict]] = {}
    for row in services or []:
        if not isinstance(row, dict):
            continue
        for owner in row.get('channel') or []:
            by_service_channel.setdefault(str(owner), []).append(row)
    tag_kind = {}
    for tag in tags or []:
        kind = _TAG_KINDS.get((tag.name or '').strip().lower())
        if kind:
            for tag_id in (tag.uuid, None if tag.htsp_id is None else str(tag.htsp_id)):
                if tag_id:
                    tag_kind[tag_id] = kind
    result = {}
    for channel in channels:
        info = ChannelKind()
        raw = channel.raw or {}
        for service in raw.get('services') or []:
            if not isinstance(service, dict):
                continue
            info.kind = _better(info.kind, _service_kind(service.get('type')))
            if service.get('caid') or service.get('caname'):
                info.encrypted = True
            info.provider = info.provider or str(service.get('providername') or '')
        for row in by_service_channel.get(channel.uuid) or []:
            info.kind = _better(info.kind, _service_kind(row.get('dvb_servicetype')))
            if row.get('encrypted') in (True, 1, '1', 'true'):
                info.encrypted = True
            info.provider = info.provider or str(row.get('provider') or '')
        if not info.kind:
            for tag_id in channel.tag_ids:
                info.kind = _better(info.kind, tag_kind.get(tag_id, ''))
        if info.kind or info.encrypted or info.provider:
            result[channel_key(channel)] = info
    return result


def recording_channel_keys(channels: Iterable[Channel], entries: Iterable[DvrEntry]) -> set:
    """Keys of the channels with a server recording running now."""
    running = [entry for entry in entries or [] if entry.category() == 'recording']
    if not running:
        return set()
    return {
        channel_key(channel)
        for channel in channels
        if any(entry.matches_channel(channel) for entry in running)
    }


def channels_in_tag(channels: Iterable[Channel], tag: Optional[ChannelTag]) -> List[Channel]:
    """Channels that carry ``tag``. None keeps every channel."""
    channels = list(channels)
    if tag is None:
        return channels
    ids = {tag.uuid}
    if tag.htsp_id is not None:
        ids.add(str(tag.htsp_id))
    members = set(tag.member_ids or [])
    return [
        channel
        for channel in channels
        if ids.intersection(channel.tag_ids)
        or channel.uuid in members
        or (channel.htsp_id is not None and str(channel.htsp_id) in members)
    ]

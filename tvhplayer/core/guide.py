"""Parsers for channels, the programme guide, profiles, and server status."""

from __future__ import annotations

import json
from typing import List, Optional

from .dvr import localized_text
from .errors import TvhError
from .models import (
    Channel,
    ChannelTag,
    ConnectionStatus,
    ContentType,
    EpgEvent,
    EpgQuery,
    InputStatus,
    ServerActivity,
    StreamProfile,
    SubscriptionStatus,
    _enabled_flag,
    _id_list,
    _optional_int,
)


def sort_channel_tags(tags: List[ChannelTag]) -> List[ChannelTag]:
    tags.sort(key=lambda tag: (tag.index, (tag.name or '').lower()))
    return tags


def parse_channel_tag(raw) -> ChannelTag:
    raw = raw or {}
    htsp_id = _optional_int(raw.get('htsp_id', raw.get('tagId')))
    uuid = raw.get('uuid') or raw.get('tagIdStr')
    if not uuid:
        uuid = '' if htsp_id is None else str(htsp_id)
    index = _optional_int(raw.get('index', raw.get('tagIndex'))) or 0
    return ChannelTag(
        uuid=str(uuid),
        name=raw.get('name') or raw.get('tagName') or '',
        index=index,
        icon=str(raw.get('icon') or raw.get('tagIcon') or ''),
        member_ids=_id_list(raw.get('members')),
        htsp_id=htsp_id,
        enabled=_enabled_flag(raw),
        raw=raw,
    )


def _genre(raw) -> List[int]:
    values = raw.get('genre')
    if values is None and raw.get('contentType') is not None:
        values = [raw.get('contentType')]
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    genres = []
    for item in values:
        parsed = _optional_int(item)
        if parsed is not None:
            genres.append(parsed)
    return genres


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes')
    return value in (1, True)


def _text(raw, *names) -> str:
    for name in names:
        if raw.get(name) not in (None, ''):
            return localized_text(raw.get(name))
    return ''


def parse_epg_event(raw, channel: Optional[Channel] = None) -> EpgEvent:
    raw = raw or {}
    summary = _text(raw, 'summary')
    description = _text(raw, 'description') or summary
    channel_uuid = str(raw.get('channelUuid') or raw.get('channelIdStr') or '')
    if not channel_uuid and channel is not None:
        channel_uuid = channel.uuid
    event_id = _optional_int(raw.get('eventId'))
    if event_id is None:
        event_id = _optional_int(raw.get('event_id'))
    number = _optional_int(raw.get('channelNumber', raw.get('channel_number'))) or 0
    return EpgEvent(
        start=_optional_int(raw.get('start')) or 0,
        stop=_optional_int(raw.get('stop')) or 0,
        title=_text(raw, 'title') or 'No title',
        description=description,
        channel_uuid=channel_uuid,
        event_id=event_id,
        subtitle=_text(raw, 'subtitle'),
        summary=summary,
        channel_name=_text(raw, 'channelName', 'channelname'),
        channel_number=number,
        genre=_genre(raw),
        image=str(raw.get('image') or ''),
        image_poster=str(raw.get('imagePoster') or ''),
        image_backdrop=str(raw.get('imageBackdrop') or ''),
        image_still=str(raw.get('imageStill') or ''),
        serieslink_uri=str(raw.get('serieslinkUri') or ''),
        episode_uri=str(raw.get('episodeUri') or ''),
        next_event_id=_optional_int(raw.get('nextEventId')),
        dvr_uuid=str(raw.get('dvrUuid') or ''),
        dvr_state=str(raw.get('dvrState') or ''),
        widescreen=_flag(raw.get('widescreen')),
        subtitled=_flag(raw.get('subtitled')),
        hd=_flag(raw.get('hd')),
        age_rating=_optional_int(raw.get('ageRating')),
        rating_label=str(raw.get('ratingLabel') or ''),
        rating_label_icon=str(raw.get('ratingLabelIcon') or ''),
        raw=raw,
    )


def epg_http_params(query: Optional[EpgQuery]) -> dict:
    """Query string for ``api/epg/events/grid``. Omitted fields are not sent."""
    query = query or EpgQuery()
    params = {}
    if query.limit is not None:
        params['limit'] = int(query.limit)
    if query.offset:
        params['start'] = int(query.offset)
    if query.title:
        params['title'] = query.title
    if query.fulltext:
        params['fulltext'] = 1
    if query.channel is not None:
        params['channel'] = query.channel.uuid or query.channel.name
    if query.channel_tag is not None:
        params['channelTag'] = query.channel_tag.uuid or query.channel_tag.name
    if query.content_type is not None:
        params['contentType'] = int(query.content_type)
    if query.duration_min is not None:
        params['durationMin'] = int(query.duration_min)
    if query.duration_max is not None:
        params['durationMax'] = int(query.duration_max)
    if query.mode:
        if query.mode != 'now':
            raise TvhError('EPG mode must be now')
        params['mode'] = 'now'
    if query.lang:
        params['lang'] = query.lang
    # The server's comparisons include the bound, so a programme that ends
    # exactly at the start of the span (or starts at its end) is left out.
    filters = []
    if query.ends_after is not None:
        filters.append({'field': 'stop', 'type': 'numeric', 'value': int(query.ends_after) + 1, 'comparison': 'gt'})
    if query.starts_before is not None:
        filters.append({'field': 'start', 'type': 'numeric', 'value': int(query.starts_before) - 1, 'comparison': 'lt'})
    if filters:
        params['filter'] = json.dumps(filters)
    return params


def epg_htsp_transport(query: Optional[EpgQuery]) -> str:
    """``epgQuery``, ``getEvents``, or ``http`` for one HTSP guide read.

    ``epgQuery`` needs a title. ``getEvents`` is a single channel with no
    other filter. Exact title match, ``mode``, a non-zero grid offset, and
    a time span exist only on the HTTP grid, so those use the ``api`` proxy.
    """
    query = query or EpgQuery()
    if query.fulltext or query.mode or query.offset:
        return 'http'
    if query.ends_after is not None or query.starts_before is not None:
        return 'http'
    if query.title:
        if query.channel is not None and query.channel.htsp_id is None:
            return 'http'
        if query.channel_tag is not None and query.channel_tag.htsp_id is None:
            return 'http'
        return 'epgQuery'
    channel_only = (
        query.channel is not None
        and query.channel.htsp_id is not None
        and query.channel_tag is None
        and query.content_type is None
        and query.duration_min is None
        and query.duration_max is None
        and not query.lang
    )
    if channel_only:
        return 'getEvents'
    return 'http'


def epg_htsp_args(query: Optional[EpgQuery]) -> dict:
    """Arguments for HTSP ``epgQuery``. ``full`` asks for event bodies."""
    query = query or EpgQuery()
    args = {'query': query.title or '', 'full': 1}
    if query.channel is not None and query.channel.htsp_id is not None:
        args['channelId'] = int(query.channel.htsp_id)
    if query.channel_tag is not None and query.channel_tag.htsp_id is not None:
        args['tagId'] = int(query.channel_tag.htsp_id)
    if query.content_type is not None:
        args['contentType'] = int(query.content_type)
    if query.duration_min is not None:
        args['minduration'] = int(query.duration_min)
    if query.duration_max is not None:
        args['maxduration'] = int(query.duration_max)
    if query.lang:
        args['language'] = query.lang
    return args


def parse_content_type(raw) -> ContentType:
    raw = raw or {}
    return ContentType(
        key=_optional_int(raw.get('key')) or 0,
        name=str(raw.get('val') if raw.get('val') is not None else raw.get('name') or ''),
        raw=raw,
    )


def parse_profile(raw) -> StreamProfile:
    raw = raw or {}
    if 'uuid' not in raw and 'key' in raw:
        return StreamProfile(
            uuid=str(raw.get('key') or ''),
            name=str(raw.get('val') or ''),
            comment='',
            raw=raw,
        )
    return StreamProfile(
        uuid=str(raw.get('uuid') or ''),
        name=str(raw.get('name') or ''),
        comment=str(raw.get('comment') or ''),
        raw=raw,
    )


def _rows(data, key='entries') -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get(key)
        if rows is None:
            rows = data.get('entries')
        return rows or []
    return []


def parse_events(rows, channel: Optional[Channel] = None) -> List[EpgEvent]:
    return [parse_epg_event(row, channel) for row in rows or [] if isinstance(row, dict)]


def parse_input_status(raw) -> InputStatus:
    raw = raw or {}
    return InputStatus(
        name=str(raw.get('input') or ''),
        uuid=str(raw.get('uuid') or ''),
        signal=_optional_int(raw.get('signal')),
        signal_scale=_optional_int(raw.get('signal_scale')) or 0,
        snr=_optional_int(raw.get('snr')),
        snr_scale=_optional_int(raw.get('snr_scale')) or 0,
        stream=str(raw.get('stream') or ''),
        weight=_optional_int(raw.get('weight')),
        subscribers=_optional_int(raw.get('subs')),
        ber=_optional_int(raw.get('ber')),
        unc=_optional_int(raw.get('unc')),
        bps=_optional_int(raw.get('bps')),
        raw=raw,
    )


def _channel_label(value) -> str:
    if isinstance(value, dict):
        return str(value.get('name') or value.get('channelName') or '')
    if value is None:
        return ''
    return str(value)


def parse_connection(raw) -> ConnectionStatus:
    raw = raw or {}
    return ConnectionStatus(
        id=_optional_int(raw.get('id')),
        peer=str(raw.get('peer') or ''),
        user=str(raw.get('user') or ''),
        started=_optional_int(raw.get('started')) or 0,
        kind=str(raw.get('type') or ''),
        server=str(raw.get('server') or ''),
        raw=raw,
    )


def parse_subscription(raw) -> SubscriptionStatus:
    raw = raw or {}
    return SubscriptionStatus(
        id=_optional_int(raw.get('id')),
        channel=_channel_label(raw.get('channel') if raw.get('channel') not in (None, '') else raw.get('title')),
        username=str(raw.get('username') or raw.get('user') or ''),
        title=str(raw.get('title') or ''),
        service=str(raw.get('service') or ''),
        state=str(raw.get('state') or ''),
        start=_optional_int(raw.get('start')) or 0,
        errors=_optional_int(raw.get('errors')) or 0,
        raw=raw,
    )


def parse_activity(raw) -> ServerActivity:
    raw = raw or {}
    activities = {}
    source = raw.get('activities') if isinstance(raw.get('activities'), dict) else {}
    for key, value in source.items():
        parsed = _optional_int(value)
        if parsed is not None:
            activities[str(key)] = parsed
    return ServerActivity(
        current_time=_optional_int(raw.get('current_time')) or 0,
        next_activity=_optional_int(raw.get('next_activity')) or 0,
        activities=activities,
        subscription_count=_optional_int(raw.get('subscription_count')) or 0,
        connection_count=_optional_int(raw.get('connection_count')) or 0,
        raw=raw,
    )

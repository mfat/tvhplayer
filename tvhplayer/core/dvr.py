"""Shared DVR payloads, parsers, and recording-file access.

Public operations live on ``TvhBackend``. Protocol mapping is documented in
``docs/dvr-backend.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import requests

from .errors import TvhConnectionError, TvhError
from .models import (
    AutorecEntry,
    AutorecSpec,
    DvrConfig,
    DvrCutpoint,
    DvrEntry,
    DvrEntryUpdate,
    TimerecEntry,
    TimerecSpec,
)

GRID_LIMIT = 10000


def grid_rows(fetch, params=None) -> list:
    """Every row of a grid call, GRID_LIMIT rows a request.

    ``fetch(params)`` returns the call's reply. A caller's own ``limit`` asks
    once. Otherwise pages follow while the reply's ``total`` says more remain.
    """
    params = dict(params or {})
    if 'limit' in params:
        return _grid_entries(fetch(params))
    rows = []
    start = int(params.pop('start', 0) or 0)
    while True:
        data = fetch(dict(params, start=start, limit=GRID_LIMIT))
        batch = _grid_entries(data)
        rows.extend(batch)
        start += len(batch)
        total = data.get('total') if isinstance(data, dict) else None
        if len(batch) < GRID_LIMIT or not isinstance(total, int) or start >= total:
            return rows


def _grid_entries(data) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    return data.get('entries') or []


def instant_recording_title(channel_name: str, when: datetime) -> str:
    """Title Tvheadend uses as ``$t`` when naming an instant recording.

    The DVR create API has no separate filename. A channel plus the local
    start time keeps each file distinct under a pathname of ``$t``.
    """
    name = (channel_name or '').strip() or 'Unknown Channel'
    return f"{name} {when.strftime('%Y-%m-%d %H:%M:%S')}"


RERECORD_ACTIONS = ('allow', 'deny', 'toggle')
PREVREC_ACTIONS = ('set', 'unset', 'toggle')
MOVE_CATEGORIES = ('finished', 'failed')
WEEKDAY_MASK = 0x7F

DVR_UPDATE_FIELDS = (
    'start',
    'stop',
    'title',
    'subtitle',
    'description',
    'comment',
    'channel',
    'start_extra',
    'stop_extra',
    'retention',
    'priority',
    'enabled',
    'config_name',
)

AUTOREC_FIELDS = (
    'title',
    'enabled',
    'name',
    'channel',
    'fulltext',
    'directory',
    'config_name',
    'min_duration',
    'max_duration',
    'days_of_week',
    'priority',
    'start',
    'start_window',
    'start_extra',
    'stop_extra',
    'comment',
    'dup_detect',
    'broadcast_type',
)

TIMEREC_FIELDS = (
    'title',
    'name',
    'enabled',
    'channel',
    'directory',
    'config_name',
    'days_of_week',
    'priority',
    'start',
    'stop',
    'retention',
    'comment',
)


def localized_text(value, default=''):
    """First non-empty string from a TVHeadend language map or plain value."""
    if isinstance(value, dict):
        if value.get('eng'):
            return str(value['eng'])
        for item in value.values():
            if item:
                return str(item)
        return default
    if value is None:
        return default
    return str(value)


def entry_uuid(entry) -> str:
    uuid = str(getattr(entry, 'uuid', '') or '')
    if not uuid:
        raise TvhError('DVR entry has no uuid')
    return uuid


def entry_htsp_id(entry) -> int:
    htsp_id = getattr(entry, 'htsp_id', None)
    if htsp_id is None:
        raise TvhError('DVR entry has no HTSP id')
    return int(htsp_id)


def rule_htsp_id(entry) -> Optional[str]:
    htsp_id = getattr(entry, 'htsp_id', None)
    if htsp_id in (None, ''):
        return None
    return str(htsp_id)


def check_choice(value, allowed, label) -> str:
    if value not in allowed:
        raise TvhError(f'{label} must be one of: {", ".join(allowed)}')
    return value


def response_id(data) -> str:
    """UUID or id from a create response. Empty when the server omits one."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ('uuid', 'id'):
            if data.get(key) not in (None, ''):
                return str(data[key])
    return ''


def minutes_to_clock(minutes: int) -> str:
    """Convert minutes from midnight to ``HH:MM`` for the HTTP timerec API."""
    value = int(minutes)
    if value < 0 or value > 1439:
        raise TvhError('Time must be minutes from midnight in the range 0..1439')
    return f'{value // 60:02d}:{value % 60:02d}'


def clock_to_minutes(value):
    """Parse ``HH:MM`` or an integer minute count. ``Any`` and blanks are None."""
    if value is None or value == '' or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text or text.lower() == 'any' or ':' not in text:
        return None
    hour, minute = text.split(':', 1)
    try:
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def weekdays_from_mask(mask: int) -> List[int]:
    """HTSP bitmask to HTTP weekday numbers (Monday 1 … Sunday 7)."""
    value = int(mask)
    if value < 0 or value > WEEKDAY_MASK:
        raise TvhError('days_of_week must fit in 7 bits (Monday 0x01 through Sunday 0x40)')
    return [day + 1 for day in range(7) if value & (1 << day)]


def mask_from_weekdays(days) -> int:
    mask = 0
    for day in days or []:
        number = int(day)
        if number < 1 or number > 7:
            continue
        mask |= 1 << (number - 1)
    return mask


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _as_int(value, default=0) -> int:
    if value in (None, ''):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _lang(text: str) -> dict:
    return {'eng': text}


def _any_set(obj, names) -> bool:
    return any(getattr(obj, name) is not None for name in names)


def _require_days(mask: int) -> int:
    value = int(mask)
    if value < 0 or value > WEEKDAY_MASK:
        raise TvhError('days_of_week must fit in 7 bits (Monday 0x01 through Sunday 0x40)')
    return value


def _channel_uuid(channel) -> str:
    uuid = str(getattr(channel, 'uuid', '') or '')
    if not uuid:
        raise TvhError('Channel has no uuid')
    return uuid


def _channel_htsp_id(channel) -> int:
    htsp_id = getattr(channel, 'htsp_id', None)
    if htsp_id is None:
        raise TvhError('Channel has no HTSP id')
    return int(htsp_id)


def parse_dvr_entry(raw) -> DvrEntry:
    """Map one HTTP ``dvr/entry`` object onto ``DvrEntry``."""
    raw = raw or {}
    start = int(raw.get('start') or 0)
    duration = int(raw.get('duration') or 0)
    if not duration:
        stop = int(raw.get('stop') or 0)
        duration = max(0, stop - start)
    return DvrEntry(
        uuid=str(raw.get('uuid') or ''),
        title=localized_text(raw.get('disp_title') or raw.get('title'), 'Unknown'),
        channel_name=raw.get('channelname') or 'Unknown',
        start=start,
        duration=duration,
        status=raw.get('status') or '',
        sched_status=raw.get('sched_status') or '',
        errors=int(raw.get('errors') or 0),
        errorcode=int(raw.get('errorcode') or 0),
        error=raw.get('error') or '',
        raw=raw,
    )


def parse_dvr_config(raw) -> DvrConfig:
    raw = raw or {}
    return DvrConfig(
        uuid=str(raw.get('uuid') or ''),
        name=str(raw.get('name') or ''),
        comment=str(raw.get('comment') or ''),
        storage=str(raw.get('storage') or ''),
        profile=str(raw.get('profile') or ''),
        enabled=_as_bool(raw.get('enabled'), True),
        raw=raw,
    )


def parse_autorec_entry(raw) -> AutorecEntry:
    raw = raw or {}
    priority = raw.get('pri', raw.get('priority'))
    return AutorecEntry(
        uuid=str(raw.get('uuid') or ''),
        title=localized_text(raw.get('title'), ''),
        name=str(raw.get('name') or ''),
        enabled=_as_bool(raw.get('enabled'), True),
        channel_uuid=str(raw.get('channel') or ''),
        comment=str(raw.get('comment') or ''),
        days_of_week=mask_from_weekdays(raw.get('weekdays')),
        priority=_optional_int(priority),
        min_duration=_as_int(raw.get('minduration', raw.get('minDuration'))),
        max_duration=_as_int(raw.get('maxduration', raw.get('maxDuration'))),
        raw=raw,
    )


def parse_timerec_entry(raw) -> TimerecEntry:
    raw = raw or {}
    priority = raw.get('pri', raw.get('priority'))
    return TimerecEntry(
        uuid=str(raw.get('uuid') or ''),
        title=localized_text(raw.get('title'), ''),
        name=str(raw.get('name') or ''),
        enabled=_as_bool(raw.get('enabled'), True),
        channel_uuid=str(raw.get('channel') or ''),
        start_minute=clock_to_minutes(raw.get('start')),
        stop_minute=clock_to_minutes(raw.get('stop')),
        retention=_as_int(raw.get('retention')),
        priority=_optional_int(priority),
        days_of_week=mask_from_weekdays(raw.get('weekdays')),
        comment=str(raw.get('comment') or ''),
        raw=raw,
    )


def parse_cutpoints(rows) -> List[DvrCutpoint]:
    points = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        points.append(
            DvrCutpoint(
                start_ms=_as_int(raw.get('start')),
                end_ms=_as_int(raw.get('end')),
                type=_as_int(raw.get('type')),
                raw=raw,
            )
        )
    return points


def dvr_update_http_node(entry, update: DvrEntryUpdate) -> dict:
    if not isinstance(update, DvrEntryUpdate) or not _any_set(update, DVR_UPDATE_FIELDS):
        raise TvhError('No DVR fields to update')
    node = {'uuid': entry_uuid(entry)}
    if update.start is not None:
        node['start'] = int(update.start)
    if update.stop is not None:
        node['stop'] = int(update.stop)
    if update.title is not None:
        node['title'] = _lang(update.title)
    if update.subtitle is not None:
        node['subtitle'] = _lang(update.subtitle)
    if update.description is not None:
        node['description'] = _lang(update.description)
    if update.comment is not None:
        node['comment'] = update.comment
    if update.channel is not None:
        node['channel'] = _channel_uuid(update.channel)
    if update.start_extra is not None:
        node['start_extra'] = int(update.start_extra)
    if update.stop_extra is not None:
        node['stop_extra'] = int(update.stop_extra)
    if update.retention is not None:
        node['retention'] = int(update.retention)
    if update.priority is not None:
        node['pri'] = int(update.priority)
    if update.enabled is not None:
        node['enabled'] = bool(update.enabled)
    if update.config_name is not None:
        node['config_name'] = update.config_name
    return node


def dvr_update_htsp_args(entry, update: DvrEntryUpdate) -> dict:
    if not isinstance(update, DvrEntryUpdate) or not _any_set(update, DVR_UPDATE_FIELDS):
        raise TvhError('No DVR fields to update')
    args = {'id': entry_htsp_id(entry)}
    if update.start is not None:
        args['start'] = int(update.start)
    if update.stop is not None:
        args['stop'] = int(update.stop)
    if update.title is not None:
        args['title'] = update.title
    if update.subtitle is not None:
        args['subtitle'] = update.subtitle
    if update.description is not None:
        args['description'] = update.description
    if update.comment is not None:
        args['comment'] = update.comment
    if update.channel is not None:
        args['channelId'] = _channel_htsp_id(update.channel)
    if update.start_extra is not None:
        args['startExtra'] = int(update.start_extra)
    if update.stop_extra is not None:
        args['stopExtra'] = int(update.stop_extra)
    if update.retention is not None:
        args['retention'] = int(update.retention)
    if update.priority is not None:
        args['priority'] = int(update.priority)
    if update.enabled is not None:
        args['enabled'] = 1 if update.enabled else 0
    if update.config_name is not None:
        args['configName'] = update.config_name
    return args


def autorec_http_conf(spec: AutorecSpec, creating=False) -> dict:
    if not isinstance(spec, AutorecSpec):
        raise TvhError('Autorec spec is required')
    if creating and not spec.title:
        raise TvhError('Autorec requires a title')
    if not creating and not _any_set(spec, AUTOREC_FIELDS):
        raise TvhError('No autorec fields to update')
    conf = {}
    if spec.title is not None:
        conf['title'] = spec.title
    if spec.enabled is not None:
        conf['enabled'] = bool(spec.enabled)
    if spec.name is not None:
        conf['name'] = spec.name
    if spec.channel is not None:
        conf['channel'] = _channel_uuid(spec.channel)
    if spec.fulltext is not None:
        conf['fulltext'] = bool(spec.fulltext)
    if spec.config_name is not None:
        conf['config_name'] = spec.config_name
    if spec.min_duration is not None:
        conf['minduration'] = int(spec.min_duration)
    if spec.max_duration is not None:
        conf['maxduration'] = int(spec.max_duration)
    if spec.days_of_week is not None:
        conf['weekdays'] = weekdays_from_mask(spec.days_of_week)
    if spec.priority is not None:
        conf['pri'] = int(spec.priority)
    if spec.start is not None:
        conf['start'] = int(spec.start)
    if spec.start_window is not None:
        conf['start_window'] = int(spec.start_window)
    if spec.start_extra is not None:
        conf['start_extra'] = int(spec.start_extra)
    if spec.stop_extra is not None:
        conf['stop_extra'] = int(spec.stop_extra)
    if spec.comment is not None:
        conf['comment'] = spec.comment
    if spec.broadcast_type is not None:
        conf['btype'] = int(spec.broadcast_type)
    if not creating and not conf:
        raise TvhError('No autorec fields apply to the HTTP API')
    return conf


def autorec_htsp_args(spec: AutorecSpec, htsp_id=None, creating=False) -> dict:
    if not isinstance(spec, AutorecSpec):
        raise TvhError('Autorec spec is required')
    if creating and not spec.title:
        raise TvhError('Autorec requires a title')
    args = {}
    if htsp_id is not None:
        args['id'] = str(htsp_id)
    if spec.title is not None:
        args['title'] = spec.title
    if spec.enabled is not None:
        args['enabled'] = 1 if spec.enabled else 0
    if spec.name is not None:
        args['name'] = spec.name
    if spec.channel is not None:
        args['channelId'] = _channel_htsp_id(spec.channel)
    if spec.fulltext is not None:
        args['fulltext'] = 1 if spec.fulltext else 0
    if spec.directory is not None:
        args['directory'] = spec.directory
    if spec.config_name is not None:
        args['configName'] = spec.config_name
    if spec.min_duration is not None:
        args['minDuration'] = int(spec.min_duration)
    if spec.max_duration is not None:
        args['maxDuration'] = int(spec.max_duration)
    if spec.days_of_week is not None:
        args['daysOfWeek'] = _require_days(spec.days_of_week)
    if spec.priority is not None:
        args['priority'] = int(spec.priority)
    if spec.start is not None:
        args['start'] = int(spec.start)
    if spec.start_window is not None:
        args['startWindow'] = int(spec.start_window)
    if spec.start_extra is not None:
        args['startExtra'] = int(spec.start_extra)
    if spec.stop_extra is not None:
        args['stopExtra'] = int(spec.stop_extra)
    if spec.comment is not None:
        args['comment'] = spec.comment
    if spec.dup_detect is not None:
        args['dupDetect'] = int(spec.dup_detect)
    if spec.broadcast_type is not None:
        args['broadcastType'] = int(spec.broadcast_type)
    if not creating and len(args) == (1 if htsp_id is not None else 0):
        raise TvhError('No autorec fields to update')
    return args


def timerec_http_conf(spec: TimerecSpec, creating=False) -> dict:
    if not isinstance(spec, TimerecSpec):
        raise TvhError('Timerec spec is required')
    if creating and not spec.title:
        raise TvhError('Timerec requires a title')
    if not creating and not _any_set(spec, TIMEREC_FIELDS):
        raise TvhError('No timerec fields to update')
    conf = {}
    if spec.title is not None:
        conf['title'] = spec.title
    if spec.name is not None:
        conf['name'] = spec.name
    if spec.enabled is not None:
        conf['enabled'] = bool(spec.enabled)
    if spec.channel is not None:
        conf['channel'] = _channel_uuid(spec.channel)
    if spec.config_name is not None:
        conf['config_name'] = spec.config_name
    if spec.days_of_week is not None:
        conf['weekdays'] = weekdays_from_mask(spec.days_of_week)
    if spec.priority is not None:
        conf['pri'] = int(spec.priority)
    if spec.start is not None:
        conf['start'] = minutes_to_clock(spec.start)
    if spec.stop is not None:
        conf['stop'] = minutes_to_clock(spec.stop)
    if spec.retention is not None:
        conf['retention'] = int(spec.retention)
    if spec.comment is not None:
        conf['comment'] = spec.comment
    if not creating and not conf:
        raise TvhError('No timerec fields apply to the HTTP API')
    return conf


def timerec_htsp_args(spec: TimerecSpec, htsp_id=None, creating=False) -> dict:
    if not isinstance(spec, TimerecSpec):
        raise TvhError('Timerec spec is required')
    if creating and not spec.title:
        raise TvhError('Timerec requires a title')
    args = {}
    if htsp_id is not None:
        args['id'] = str(htsp_id)
    if spec.title is not None:
        args['title'] = spec.title
    if spec.name is not None:
        args['name'] = spec.name
    if spec.enabled is not None:
        args['enabled'] = 1 if spec.enabled else 0
    if spec.channel is not None:
        args['channelId'] = _channel_htsp_id(spec.channel)
    if spec.directory is not None:
        args['directory'] = spec.directory
    if spec.config_name is not None:
        args['configName'] = spec.config_name
    if spec.days_of_week is not None:
        args['daysOfWeek'] = _require_days(spec.days_of_week)
    if spec.priority is not None:
        args['priority'] = int(spec.priority)
    if spec.start is not None:
        args['start'] = int(spec.start)
    if spec.stop is not None:
        args['stop'] = int(spec.stop)
    if spec.retention is not None:
        args['retention'] = int(spec.retention)
    if spec.comment is not None:
        args['comment'] = spec.comment
    if not creating and len(args) == (1 if htsp_id is not None else 0):
        raise TvhError('No timerec fields to update')
    return args


def file_move_args(src: str, dst: str) -> dict:
    source = str(src or '').strip()
    destination = str(dst or '').strip()
    if not source or not destination:
        raise TvhError('File move requires both a source path and a destination path')
    return {'src': source, 'dst': destination}


def ticket_url(base: str, path: str, ticket: str) -> str:
    """Join an HTSP ``getTicket`` path and ticket onto an HTTP origin."""
    if not path:
        raise TvhError('getTicket returned no path')
    suffix = path if str(path).startswith('/') else f'/{path}'
    url = f'{base.rstrip("/")}{suffix}'
    if ticket:
        joiner = '&' if '?' in url else '?'
        url = f'{url}{joiner}ticket={quote(str(ticket), safe="")}'
    return url


class RecordingFile:
    """Byte access to one server-side recording.

    ``read(size, offset)`` is the portable call: ``offset`` is an absolute
    byte position. ``seek`` on HTTP uses a signed offset (``SEEK_END`` with a
    negative offset moves back from the end). HTSP forwards ``seek`` to
    ``fileSeek``, whose offset is unsigned and whose ``SEEK_END`` moves back
    from the end.

    ``size`` and ``mtime`` come from the server and may be ``None``. The
    object is a context manager.
    """

    def __init__(self, size=None, mtime=None):
        self.size = size
        self.mtime = mtime
        self._offset = 0

    def read(self, size: int, offset: Optional[int] = None) -> bytes:
        raise NotImplementedError

    def seek(self, offset: int, whence: str = 'SEEK_SET') -> int:
        if whence not in ('SEEK_SET', 'SEEK_CUR', 'SEEK_END'):
            raise TvhError('whence must be SEEK_SET, SEEK_CUR, or SEEK_END')
        if whence == 'SEEK_END' and self.size is None:
            raise TvhError('Recording size is unknown')
        origin = 0 if whence == 'SEEK_SET' else self._offset if whence == 'SEEK_CUR' else self.size
        position = origin + int(offset)
        if position < 0:
            raise TvhError('Seek offset is before the start of the file')
        self._offset = position
        return self._offset

    def stat(self):
        """Return ``(size, mtime)``."""
        return (self.size, self.mtime)

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class HttpRecordingFile(RecordingFile):
    """HTTP Range reader for ``dvrfile/<uuid>``."""

    def __init__(self, session, url, auth, timeout, size=None, mtime=None):
        super().__init__(size=size, mtime=mtime)
        self._session = session
        self._url = url
        self._auth = auth
        self._timeout = timeout
        self._closed = False

    def read(self, size: int, offset: Optional[int] = None) -> bytes:
        if self._closed:
            raise TvhError('Recording file is closed')
        size = int(size)
        if size <= 0:
            raise TvhError('Read size must be positive')
        position = self._offset if offset is None else int(offset)
        headers = {'Range': f'bytes={position}-{position + size - 1}'}
        try:
            response = self._session.get(
                self._url,
                auth=self._auth,
                headers=headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise TvhConnectionError(str(exc)) from exc
        if response.status_code not in (200, 206):
            raise TvhError(f'HTTP {response.status_code} reading {self._url}')
        data = response.content or b''
        self._offset = position + len(data)
        return data

    def close(self):
        self._closed = True


class HtspRecordingFile(RecordingFile):
    """HTSP ``fileOpen`` reader for ``/dvrfile/<id>``."""

    def __init__(self, rpc, handle, size=None, mtime=None):
        super().__init__(size=size, mtime=mtime)
        self._rpc = rpc
        self._handle = handle

    def _require_handle(self):
        if self._handle is None:
            raise TvhError('Recording file is closed')
        return self._handle

    def read(self, size: int, offset: Optional[int] = None) -> bytes:
        size = int(size)
        if size <= 0:
            raise TvhError('Read size must be positive')
        position = self._offset if offset is None else int(offset)
        reply = self._rpc(
            'fileRead',
            {'id': self._require_handle(), 'size': size, 'offset': position},
        )
        data = reply.get('data') if isinstance(reply, dict) else b''
        if data is None:
            data = b''
        if not isinstance(data, (bytes, bytearray)):
            raise TvhError('HTSP fileRead returned no binary data')
        data = bytes(data)
        self._offset = position + len(data)
        return data

    def seek(self, offset: int, whence: str = 'SEEK_SET') -> int:
        if whence not in ('SEEK_SET', 'SEEK_CUR', 'SEEK_END'):
            raise TvhError('whence must be SEEK_SET, SEEK_CUR, or SEEK_END')
        reply = self._rpc(
            'fileSeek',
            {'id': self._require_handle(), 'offset': int(offset), 'whence': whence},
        )
        if isinstance(reply, dict) and reply.get('offset') is not None:
            self._offset = int(reply['offset'])
            return self._offset
        return super().seek(offset, whence)

    def stat(self):
        reply = self._rpc('fileStat', {'id': self._require_handle()})
        if isinstance(reply, dict):
            if reply.get('size') is not None:
                self.size = int(reply['size'])
            if reply.get('mtime') is not None:
                self.mtime = int(reply['mtime'])
        return (self.size, self.mtime)

    def close(self):
        handle = self._handle
        self._handle = None
        if handle is None:
            return None
        self._rpc('fileClose', {'id': handle})
        return None

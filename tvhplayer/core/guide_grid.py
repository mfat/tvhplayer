"""The TV guide grid without Qt: time spans, rows, and what is scheduled.

The server never returns programmes that have already ended, so the grid
starts at the half hour before now. Programmes are fetched in fixed spans
of time as the view reaches them and kept per channel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from .channel_info import channel_key
from .models import Channel, DvrEntry, EpgEvent, _optional_int

SLOT_SECONDS = 1800
SPAN_SECONDS = 6 * 3600
# How far ahead the grid reaches. Most guides carry a week or two.
GUIDE_DAYS = 14

RECORDING = 'recording'
SCHEDULED = 'scheduled'


def local_offset(when: int) -> int:
    """Seconds east of UTC at ``when`` in local time."""
    return int(datetime.fromtimestamp(when).astimezone().utcoffset().total_seconds())


def slot_start(when: int) -> int:
    """The local half hour at or before ``when``, so the ruler reads :00 and :30."""
    offset = local_offset(when)
    return (when + offset) // SLOT_SECONDS * SLOT_SECONDS - offset


def local_midnight(when: int) -> int:
    day = datetime.fromtimestamp(when).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day.timestamp())


def span_start(when: int, origin: int) -> int:
    """Start of the fetch span that holds ``when``. Spans are counted from ``origin``."""
    return origin + (when - origin) // SPAN_SECONDS * SPAN_SECONDS


def spans_between(start: int, end: int, origin: int) -> List[int]:
    """Starts of the fetch spans that cover ``start`` up to ``end``."""
    first = span_start(max(start, origin), origin)
    return list(range(first, max(end, first + 1), SPAN_SECONDS))


@dataclass
class Cell:
    """One programme as drawn: its times clipped to the grid and to its neighbours."""

    event: EpgEvent
    start: int
    stop: int


class GuideData:
    """Programmes per channel, filled one span at a time.

    Channels are matched by UUID, then by name, because servers reached over
    older HTSP versions send channels without their UUID.
    """

    def __init__(self, channels: Iterable[Channel] = ()):
        self._by_uuid: Dict[str, str] = {}
        self._by_name: Dict[str, str] = {}
        self._events: Dict[str, Dict[object, EpgEvent]] = {}
        self._cells: Dict[str, List[EpgEvent]] = {}
        self.loaded = set()
        self.set_channels(channels)

    def set_channels(self, channels: Iterable[Channel]):
        self._by_uuid = {}
        self._by_name = {}
        for channel in channels:
            key = channel_key(channel)
            if channel.uuid:
                self._by_uuid.setdefault(str(channel.uuid), key)
            if channel.name:
                self._by_name.setdefault(channel.name.casefold(), key)

    def clear(self):
        self._events.clear()
        self._cells.clear()
        self.loaded.clear()

    def key_for(self, event: EpgEvent) -> Optional[str]:
        key = self._by_uuid.get(event.channel_uuid or '')
        if key is None and event.channel_name:
            key = self._by_name.get(event.channel_name.casefold())
        return key

    def add(self, span: int, events: Iterable[EpgEvent]):
        """Keep ``events`` fetched for ``span``. A programme in two spans is kept once."""
        self.loaded.add(span)
        for event in events:
            key = self.key_for(event)
            if key is None or event.stop <= event.start:
                continue
            ident = event.event_id if event.event_id is not None else (event.start, event.title)
            self._events.setdefault(key, {})[ident] = event
            self._cells.pop(key, None)

    def update_event(self, event: EpgEvent):
        """Replace one programme, for example after it was scheduled."""
        key = self.key_for(event)
        if key is None or event.event_id is None:
            return
        events = self._events.get(key)
        if events is not None and event.event_id in events:
            events[event.event_id] = event
            self._cells.pop(key, None)

    def events(self, key: str) -> List[EpgEvent]:
        """One channel's programmes by start time."""
        cached = self._cells.get(key)
        if cached is None:
            cached = sorted((self._events.get(key) or {}).values(), key=lambda e: (e.start, e.stop))
            self._cells[key] = cached
        return cached

    def all_events(self) -> List[EpgEvent]:
        return [event for events in self._events.values() for event in events.values()]


def row_cells(events: Iterable[EpgEvent], start: int, end: int, min_seconds: int = 60) -> List[Cell]:
    """Programmes that show between ``start`` and ``end``, in order.

    A programme that overlaps the one before it starts where that one ends,
    so cells never cover each other. Slivers shorter than ``min_seconds``
    are left out.
    """
    cells = []
    edge = start
    for event in events:
        if event.stop <= start or event.start >= end:
            continue
        left = max(event.start, edge)
        right = min(event.stop, end)
        if right - left < min_seconds:
            continue
        cells.append(Cell(event, left, right))
        edge = right
    return cells


def cell_at(cells: List[Cell], when: int) -> int:
    """Index of the cell showing at ``when``, else the nearest one. -1 when empty."""
    if not cells:
        return -1
    best = 0
    best_gap = None
    for index, cell in enumerate(cells):
        if cell.start <= when < cell.stop:
            return index
        gap = cell.start - when if cell.start > when else when - cell.stop + 1
        if best_gap is None or gap < best_gap:
            best, best_gap = index, gap
    return best


def _entry_event_id(entry: DvrEntry) -> Optional[int]:
    raw = entry.raw or {}
    for name in ('broadcast', 'eventId'):
        value = _optional_int(raw.get(name))
        if value:
            return value
    return None


def entries_by_event(entries: Iterable[DvrEntry]) -> Dict[int, DvrEntry]:
    """Recordings that are running or still to come, keyed by their programme's id."""
    found = {}
    for entry in entries or []:
        if entry.category() not in (RECORDING, 'upcoming'):
            continue
        event_id = _entry_event_id(entry)
        if event_id is not None:
            found[event_id] = entry
    return found


def recording_state(event: EpgEvent, entries: Optional[Dict[int, DvrEntry]]) -> str:
    """``recording``, ``scheduled``, or empty for one programme.

    ``entries`` is the server's list of recordings from ``entries_by_event``,
    or None while it has not been read. Once read it wins over what the
    guide said when it was fetched, so a timer added or cancelled since
    shows at once.
    """
    if entries is not None:
        entry = entries.get(event.event_id) if event.event_id is not None else None
        if entry is None:
            return ''
        return RECORDING if entry.category() == RECORDING else SCHEDULED
    state = (event.dvr_state or '').lower()
    if not event.dvr_uuid:
        return ''
    if state == RECORDING:
        return RECORDING
    if state == SCHEDULED:
        return SCHEDULED
    return ''


def clock(when: int) -> str:
    return time.strftime('%H:%M', time.localtime(when))


def day_label(when: int, now: int) -> str:
    """Today, Tomorrow, or the weekday and date."""
    days = (local_midnight(when) - local_midnight(now)) // 86400
    if days == 0:
        return 'Today'
    if days == 1:
        return 'Tomorrow'
    day = datetime.fromtimestamp(when)
    return f'{day:%a} {day.day} {day:%b}'


def duration_text(seconds: int) -> str:
    minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f'{hours} h {minutes} min'
    if hours:
        return f'{hours} h'
    return f'{minutes} min'


def timing_text(event: EpgEvent, now: int) -> str:
    """When a programme is on, for the details panel and screen readers."""
    span = f'{clock(event.start)} to {clock(event.stop)}'
    if event.start <= now < event.stop:
        left = duration_text(event.stop - now)
        return f'On now, {span}, {left} left'
    if event.stop <= now:
        return f'Ended, {span}'
    return f'{day_label(event.start, now)}, {span}, {duration_text(event.stop - event.start)}'


def cell_description(channel_name: str, event: EpgEvent, now: int, state: str = '') -> str:
    """What a screen reader says for the focused programme."""
    parts = [event.title or 'No title', channel_name, timing_text(event, now)]
    if state == RECORDING:
        parts.append('recording')
    elif state == SCHEDULED:
        parts.append('recording scheduled')
    return ', '.join(part for part in parts if part)

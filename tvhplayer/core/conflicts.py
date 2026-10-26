"""Recordings that need more tuners than the server has. No Qt imports.

Recordings on one mux share a tuner; IPTV channels need none. When more
muxes overlap than the server has enabled tuners, Tvheadend records the
higher-priority ones and the rest fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional

from .channel_edit import short_id
from .tuners import read_tuners


@dataclass
class TunerUse:
    """How many tuners the server has, and the mux each tuner channel is received on."""

    tuners: int = 0
    channel_mux: Dict[str, str] = field(default_factory=dict)
    # HTSP names channels by a short id; it maps back to the uuid.
    short_ids: Dict[int, str] = field(default_factory=dict)

    def mux_of(self, channel) -> Optional[str]:
        if isinstance(channel, str) and channel in self.channel_mux:
            return self.channel_mux[channel]
        try:
            uuid = self.short_ids.get(int(channel))
        except (TypeError, ValueError):
            return None
        return self.channel_mux.get(uuid) if uuid else None


def read_tuner_use(admin) -> TunerUse:
    tuners = sum(1 for tuner in read_tuners(admin) if tuner.enabled)
    if not tuners:
        return TunerUse()
    muxes = {row['uuid'] for row in admin.list_tuner_muxes() if row.get('uuid')}
    channel_mux = {}
    for service in admin.list_services_all():
        mux = service.get('multiplex_uuid')
        if mux not in muxes or not service.get('enabled', True):
            continue
        for channel in service.get('channel') or []:
            channel_mux.setdefault(channel, mux)
    short_ids = {short_id(uuid): uuid for uuid in channel_mux}
    short_ids.pop(None, None)
    return TunerUse(tuners=tuners, channel_mux=channel_mux, short_ids=short_ids)


def _window(entry):
    start = int(entry.start or 0)
    return start, start + int(entry.duration or 0)


def find_conflicts(entries: Iterable, use: Optional[TunerUse], now: int) -> List[List]:
    """Groups of recordings that overlap on more muxes than there are tuners.

    Each group is every recording running at the moment the shortage starts,
    sorted by start time. A group is returned once even if the shortage lasts.
    """
    if use is None or use.tuners <= 0:
        return []
    timed = []
    for entry in entries:
        if entry.category() not in ('upcoming', 'recording'):
            continue
        if (entry.raw or {}).get('enabled') is False:
            continue
        start, stop = _window(entry)
        mux = use.mux_of((entry.raw or {}).get('channel'))
        if mux and stop > now and stop > start:
            timed.append((start, stop, mux, entry))
    groups: List[List] = []
    seen: set[FrozenSet[str]] = set()
    for moment, _stop, _mux, _entry in sorted(timed, key=lambda item: item[0]):
        active = [item for item in timed if item[0] <= moment < item[1]]
        if len({item[2] for item in active}) <= use.tuners:
            continue
        key = frozenset(item[3].uuid for item in active)
        if key in seen:
            continue
        seen.add(key)
        groups.append([item[3] for item in sorted(active, key=lambda item: item[0])])
    return groups


def conflict_key(group) -> FrozenSet[str]:
    return frozenset(entry.uuid for entry in group)

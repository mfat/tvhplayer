"""Load the programme guides into a server on this computer. No Qt imports.

The server reads XMLTV through its External XMLTV socket. Its own matching
links a guide channel to one TV channel only, by ID or name, and drops the
programmes of guide channels that are not linked yet. So TVHplayer writes a
guide with one guide channel per TV channel, sends it, links each TV channel
to its guide channel through the API, and sends it once more when links were
added.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .errors import PlaylistError
from .guide_feeds import CHANNEL_PREFIX, GuideCache, GuideError, GuideSource, build_index, guide_channel_id, write_server_guide
from .guide_match import Assignment, Choice, ServerChannel, assign
from .xmltv import send_guide, usable_socket

NO_SOCKET = 'The server on this computer did not open its XMLTV socket.'
# The server reads what the socket received on its own time; a big guide takes a while.
LINK_WAIT_SECONDS = 180
# Channels asked whether the server still has their programmes, before skipping a load.
PROBE_CHANNELS = 3


@dataclass
class GuideReport:
    channels: int = 0
    # Channels with programmes from now on, and when the furthest one ends.
    covered: int = 0
    until: int = 0
    unmatched: List[str] = field(default_factory=list)
    # Sources that could not be updated, with the reason; their last copy was used.
    failed: Dict[str, str] = field(default_factory=dict)
    # Nothing changed since the last load and the server still had it, so nothing was sent.
    unchanged: bool = False

    def message(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        if not self.channels:
            return 'The server has no channels for the TV guide.'
        text = f'TV guide loaded for {self.covered} of {self.channels} channels'
        days = int((self.until - now) // 86400) if self.until > now else 0
        if self.covered and days >= 1:
            text += f', up to {days} day ahead' if days == 1 else f', up to {days} days ahead'
        text += '.'
        if self.failed:
            names = ', '.join(sorted(self.failed))
            text += f' Could not update {names}; the last copy was used.'
        return text


def server_channels(admin) -> List[ServerChannel]:
    """The server's channels with the guide IDs of their services."""
    muxes = {row.get('uuid'): row for row in admin.list_all_muxes()}
    service_ids = {}
    for service in admin.list_services_all():
        mux = muxes.get(service.get('multiplex_uuid')) or {}
        epg_id = (mux.get('iptv_epgid') or '').strip()
        if epg_id:
            service_ids[service.get('uuid')] = epg_id
    channels = []
    for row in admin.list_channels():
        uuid = row.get('uuid')
        if not uuid:
            continue
        ids = []
        for service in row.get('services') or []:
            epg_id = service_ids.get(service)
            if epg_id and epg_id not in ids:
                ids.append(epg_id)
        channels.append(ServerChannel(
            uuid=uuid,
            name=str(row.get('name') or ''),
            number=str(row.get('number') or ''),
            epg_ids=tuple(ids),
            enabled=bool(row.get('enabled', True)),
            epggrab=tuple(row.get('epggrab') or ()),
        ))
    return channels


def refresh_sources(
    cache: GuideCache,
    sources: List[GuideSource],
    force: bool = False,
    status: Callable[[str], None] = lambda _text: None,
    progress: Callable[[int, int], None] = lambda _done, _total: None,
    cancelled: Callable[[], bool] = lambda: False,
    now: Optional[float] = None,
) -> Dict[str, str]:
    """Download the sources that are due, or all with ``force``. Returns the failures by name.

    Each source is updated in place: ``tried``, ``updated`` and ``error``.
    """
    failed = {}
    for source in sources:
        if cancelled():
            break
        if not force and not source.is_due(now) and cache.summary(source.location) is not None:
            continue
        status(f'Downloading {source.label()}…')
        source.tried = time.time() if now is None else now
        try:
            cache.refresh(source.location, progress, cancelled)
        except GuideError as exc:
            source.error = str(exc)
            failed[source.label()] = source.error
            continue
        source.updated = source.tried
        source.error = ''
    return failed


# The module id of channels that came in through the External XMLTV socket.
SOCKET_MODULE = 'xmltv'


@dataclass
class GuideChannels:
    """The server's guide channels: ours by ID, and others that came in through the socket."""

    ours: Dict[str, str] = field(default_factory=dict)
    socket: List[str] = field(default_factory=list)


def guide_channels_on_server(
    admin,
    wanted=(),
    wait: float = 0,
    sleep: Callable[[float], None] = time.sleep,
    cancelled: Callable[[], bool] = lambda: False,
) -> GuideChannels:
    """Read the guide channels once every ID in ``wanted`` is there or ``wait`` ran out."""
    deadline = time.monotonic() + wait
    while True:
        found = GuideChannels()
        for row in admin.list_guide_channels():
            channel_id = row.get('id') or ''
            uuid = row.get('uuid')
            if not uuid:
                continue
            if channel_id.startswith(CHANNEL_PREFIX):
                found.ours[channel_id] = uuid
            elif row.get('modid') == SOCKET_MODULE:
                found.socket.append(uuid)
        if set(wanted) <= set(found.ours) or time.monotonic() >= deadline or cancelled():
            return found
        sleep(1)


def link_channels(
    admin,
    channels: List[ServerChannel],
    assignments: Dict[str, Assignment],
    found: GuideChannels,
    take_over: bool = False,
) -> int:
    """Point each TV channel at its own guide channel. Returns how many links were added.

    Channels that lost their guide are unlinked from ours, and guide channels
    of ours nobody uses are deleted. With ``take_over`` the same happens to
    every other guide channel that came in through the socket: on the built-in
    server only TVHplayer sends guides, so those are left from older versions
    or tests. Links to other grabbers' channels are always kept.
    """
    ours = found.ours
    replaced = set(ours.values()) | (set(found.socket) if take_over else set())
    changes = []
    added = 0
    for channel in channels:
        current = list(channel.epggrab)
        keep = [uuid for uuid in current if uuid not in replaced]
        target = ours.get(guide_channel_id(channel.uuid)) if channel.uuid in assignments else None
        wanted = [target] if target else keep
        if target and target not in current:
            added += 1
        if sorted(wanted) != sorted(current):
            changes.append({'uuid': channel.uuid, 'epggrab': wanted})
    if changes:
        admin.save(changes)
    unused = [uuid for channel_id, uuid in ours.items()
              if channel_id[len(CHANNEL_PREFIX):] not in assignments]
    if take_over:
        unused += found.socket
    if unused:
        admin.delete(unused)
    return added


def load_fingerprint(cache: GuideCache, assignments: Dict[str, Assignment], names: Dict[str, str]) -> str:
    """What a load would send: each channel's guide channel and shift, and the guide files' versions."""
    digest = hashlib.sha256()
    for uuid in sorted(assignments):
        assignment = assignments[uuid]
        guide = assignment.channel
        digest.update(f'{uuid}\0{guide.source}\0{guide.id}\0{assignment.shift}\0{names.get(uuid, "")}\n'.encode())
    for location in sorted({assignment.channel.source for assignment in assignments.values()}):
        try:
            info = os.stat(cache.file(location))
        except OSError:
            continue
        digest.update(f'{location}\0{info.st_size}\0{info.st_mtime_ns}\n'.encode())
    return digest.hexdigest()


def _state_path(cache: GuideCache, server):
    key = 'builtin' if server.get('builtin') else (server.get('url') or '').strip().rstrip('/')
    return cache.folder / f'loaded-{hashlib.sha256(key.encode()).hexdigest()[:16]}.json'


def _read_state(cache: GuideCache, server) -> dict:
    try:
        data = json.loads(_state_path(cache, server).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(cache: GuideCache, server, fingerprint: str, last_stop: Dict[str, int]) -> None:
    path = _state_path(cache, server)
    try:
        cache.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'fingerprint': fingerprint, 'last_stop': last_stop}), encoding='utf-8')
    except OSError:
        pass


def server_still_has(admin, state: dict, channels: List[ServerChannel], assignments: Dict[str, Assignment], now) -> bool:
    """Whether the last load is still on the server: every channel linked, and programmes there.

    The server can lose its EPG, for example when its database is deleted.
    """
    linked = {channel.uuid for channel in channels if channel.epggrab}
    if not set(assignments) <= linked:
        return False
    last_stop = state.get('last_stop') or {}
    # Channels whose programmes run on for a while, so a gap in one guide does not count.
    probes = sorted((uuid for uuid, stop in last_stop.items() if uuid in assignments and stop > now + 3600),
                    key=lambda uuid: -last_stop[uuid])[:PROBE_CHANNELS]
    if assignments and not probes:
        return False
    return all(admin.has_programmes(uuid) for uuid in probes)


def update_server_guide(
    admin,
    server,
    cache: GuideCache,
    sources: List[GuideSource],
    choices: Dict[str, Choice],
    force: bool = False,
    status: Callable[[str], None] = lambda _text: None,
    progress: Callable[[int, int], None] = lambda _done, _total: None,
    cancelled: Callable[[], bool] = lambda: False,
    now: Optional[float] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> GuideReport:
    """Update the due sources and load the guide into ``server``, which runs on this computer."""
    report = GuideReport()
    report.failed = refresh_sources(cache, sources, force, status, progress, cancelled, now)
    if cancelled():
        raise GuideError('Stopped.')
    status('Matching channels…')
    channels = server_channels(admin)
    report.channels = len(channels)
    index = build_index(cache, sources)
    assignments = assign(channels, index, choices)
    report.unmatched = [channel.name for channel in channels if channel.uuid not in assignments]
    socket_path = admin.enable_xmltv_socket()
    if not usable_socket(server, socket_path):
        raise GuideError(NO_SOCKET)
    if server.get('builtin'):
        admin.keep_guide_after_import()
    names = {channel.uuid: channel.name for channel in channels}
    moment = time.time() if now is None else now
    fingerprint = load_fingerprint(cache, assignments, names)
    state = _read_state(cache, server)
    if state.get('fingerprint') == fingerprint and server_still_has(admin, state, channels, assignments, moment):
        last_stop = {uuid: stop for uuid, stop in (state.get('last_stop') or {}).items() if uuid in assignments}
        report.unchanged = True
        report.covered = sum(1 for stop in last_stop.values() if stop > moment)
        report.until = max(last_stop.values(), default=0)
        return report
    status('Loading the TV guide into the server…')
    built = write_server_guide(cache, assignments, names, cache.folder, cancelled, now)
    try:
        try:
            send_guide(socket_path, built.path)
            wanted = {guide_channel_id(uuid) for uuid in assignments}
            found = guide_channels_on_server(admin, wanted, LINK_WAIT_SECONDS, sleep, cancelled)
            if link_channels(admin, channels, assignments, found, take_over=bool(server.get('builtin'))):
                # The server dropped the programmes of guide channels that had no TV channel yet.
                send_guide(socket_path, built.path)
        except PlaylistError as exc:
            raise GuideError(str(exc)) from exc
    finally:
        os.unlink(built.path)
    _write_state(cache, server, fingerprint, built.last_stop)
    report.covered = sum(1 for uuid, stop in built.last_stop.items() if stop > moment)
    report.until = max(built.last_stop.values(), default=0)
    return report

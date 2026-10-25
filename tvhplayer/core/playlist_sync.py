"""Write a playlist's channels to a Tvheadend server and keep them in sync. No Qt imports.

Each imported playlist is one IPTV network. Its muxes get their service
without a scan (Service ID 1), and the network's bouquet maps them to
channels. An entry keeps its mux across refreshes through its key, so a
changed stream address or name edits the channel instead of replacing it.

Tvheadend still scans each new mux once, and a refresh scans them all
again. Only a mux whose scan passed keeps its service enabled; disabling a
service makes the bouquet delete its channel, so dead streams never show.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .errors import PlaylistError, TvhAuthError, TvhConnectionError
from .playlist import NO_CHANNELS, ChannelPlan, SkippedEntry

BUILTIN_SERVER_KEY = 'builtin'
# Distro packages and the common Docker images install ffmpeg here. A bare
# name can match ffmpegthumbnailer in Tvheadend's PATH lookup (issue 1632).
REMOTE_FFMPEG = '/usr/bin/ffmpeg'
NO_FFMPEG = 'TVHplayer could not find ffmpeg, which it needs to play imported channels.'
MAX_STREAMS = 2
CHECKPOINT_EVERY = 50
CHECK_POLL_SECONDS = 2
NOT_WORKING = 'It is not working right now.'

# mpegts_mux_t scan_state and scan_result values.
SCAN_IDLE = 0
SCAN_NONE = 0
SCAN_PASSED = (1, 3)  # OK, OK (partial)

NETWORK_CONF = {
    'service_sid': 1,
    'scan_create': False,
    'skipinitscan': True,
    'idlescan': False,
    'max_streams': MAX_STREAMS,
    'max_timeout': 15,
    'bouquet': True,
    'epgauto_default': True,
}


@dataclass
class PlaylistSource:
    """An imported playlist, saved in tvhplayer.conf."""

    name: str
    location: str
    server: str
    network_uuid: str = ''
    muxes: Dict[str, str] = field(default_factory=dict)
    allow_commands: bool = False
    # Channel tag names this playlist's groups created on the server.
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        muxes = data.get('muxes') if isinstance(data.get('muxes'), dict) else {}
        return cls(
            name=str(data.get('name') or ''),
            location=str(data.get('location') or ''),
            server=str(data.get('server') or ''),
            network_uuid=str(data.get('network_uuid') or ''),
            muxes={str(key): str(value) for key, value in muxes.items()},
            allow_commands=bool(data.get('allow_commands')),
            tags=[str(tag) for tag in data.get('tags') or [] if tag],
        )

    def to_dict(self):
        return {
            'name': self.name,
            'location': self.location,
            'server': self.server,
            'network_uuid': self.network_uuid,
            'muxes': dict(self.muxes),
            'allow_commands': self.allow_commands,
            'tags': list(self.tags),
        }


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: List[SkippedEntry] = field(default_factory=list)
    cancelled: bool = False
    guide_failed: bool = False
    # Channels whose stream passed the server's scan, and names of those that failed.
    working: int = 0
    not_working: List[str] = field(default_factory=list)
    check_stopped: bool = False


def server_key(server) -> str:
    """How a playlist source names its server: ``builtin`` or the server URL."""
    if server.get('builtin'):
        return BUILTIN_SERVER_KEY
    return (server.get('url') or '').strip().rstrip('/')


def ffmpeg_for_server(server, which=shutil.which) -> str:
    """The ffmpeg Tvheadend should run. The built-in server shares this app's PATH."""
    if server.get('builtin'):
        path = which('ffmpeg')
        if not path:
            raise PlaylistError(NO_FFMPEG)
        return path
    return REMOTE_FFMPEG


def find_source(sources: List[PlaylistSource], location: str, key: str) -> Optional[PlaylistSource]:
    location = (location or '').strip()
    for source in sources:
        if source.server == key and source.location == location:
            return source
    return None


def unique_name(sources: List[PlaylistSource], name: str, key: str) -> str:
    taken = {source.name for source in sources if source.server == key}
    if name not in taken:
        return name
    number = 2
    while f'{name} {number}' in taken:
        number += 1
    return f'{name} {number}'


def _channels(count: int) -> str:
    return '1 channel' if count == 1 else f'{count} channels'


def result_message(name: str, result: SyncResult, first_import: bool) -> str:
    if result.cancelled:
        return f'Import stopped. {_channels(result.added)} from {name} were added.'
    failed = len(result.not_working)
    if first_import:
        message = f'Added {_channels(result.working)} from {name}.'
        if failed:
            message += (
                ' 1 was left out because it is not working.' if failed == 1
                else f' {failed} were left out because they are not working.'
            )
    elif result.added or result.removed:
        parts = []
        if result.added:
            parts.append(f'{result.added} added')
        if result.removed:
            parts.append(f'{result.removed} removed')
        message = f'Updated the channels from {name}: {", ".join(parts)}.'
    else:
        message = f'The channels from {name} are up to date.'
    if failed and not first_import:
        message += (
            ' 1 channel is not working right now and is hidden.' if failed == 1
            else f' {failed} channels are not working right now and are hidden.'
        )
    if result.check_stopped:
        message += ' Channels that were not checked yet stay hidden.'
    count = sum(1 for entry in result.skipped if entry.reason != NOT_WORKING)
    if count:
        message += ' 1 entry could not be added.' if count == 1 else f' {count} entries could not be added.'
    if result.guide_failed:
        message += ' The program guide could not be loaded.'
    return message


def error_message(exc: Exception, server_name: str, removing: bool = False) -> str:
    """Plain words for a failed import or removal."""
    if isinstance(exc, PlaylistError):
        return str(exc)
    if isinstance(exc, TvhAuthError):
        return (
            f'This account cannot add channels to {server_name}. '
            'Sign in with an administrator account in Manage Servers.'
        )
    if isinstance(exc, TvhConnectionError):
        return f'Could not reach {server_name}. Check that it is running and that its address is right.'
    action = 'remove' if removing else 'add'
    return f'{server_name} could not {action} the channels: {exc}'


def mux_conf(plan: ChannelPlan) -> dict:
    return {
        'enabled': 1,
        'iptv_url': plan.url,
        'iptv_sname': plan.name,
        'iptv_muxname': plan.name,
        'channel_number': plan.number or '0',
        'iptv_icon': plan.icon,
        'iptv_epgid': plan.epg_id,
        'iptv_tags': '\n'.join(plan.groups),
        # Over-the-air EPG would re-tune every watched stream twice a day.
        'epg': 0,
    }


def sync_playlist(
    admin,
    source: PlaylistSource,
    plans: List[ChannelPlan],
    skipped=(),
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    checkpoint: Optional[Callable[[], None]] = None,
) -> SyncResult:
    """Create, update, and remove muxes so the network matches ``plans``.

    ``source`` is updated in place. ``checkpoint`` is called whenever its
    mux map changed, so a cancelled or failed import leaves the saved map
    matching the server.
    """
    if not plans:
        raise PlaylistError(NO_CHANNELS)
    progress = progress or (lambda _done, _total: None)
    cancelled = cancelled or (lambda: False)
    checkpoint = checkpoint or (lambda: None)
    result = SyncResult(skipped=list(skipped))

    admin.check_admin()
    refresh = admin.network_exists(source.network_uuid)
    if not refresh:
        conf = dict(NETWORK_CONF, networkname=source.name)
        source.network_uuid = admin.create_network(conf)
        source.muxes = {}
        checkpoint()
    else:
        admin.enable_network(source.network_uuid)

    rows = {row['uuid']: row for row in admin.list_muxes(source.network_uuid) if row.get('uuid')}
    known = {key: uuid for key, uuid in source.muxes.items() if uuid in rows}
    if known != source.muxes:
        source.muxes = known
        checkpoint()

    # Muxes in this network the saved map lost: an import that stopped before
    # its checkpoint, or an older version that duplicated the playlist. Adopt
    # one per entry by stream address and delete the rest.
    tracked = set(source.muxes.values())
    untracked = {}
    for uuid, row in rows.items():
        if uuid not in tracked:
            untracked.setdefault(row.get('iptv_url') or '', []).append(uuid)
    if untracked:
        for plan in plans:
            if plan.key not in source.muxes:
                spare = untracked.get(mux_conf(plan)['iptv_url'])
                if spare:
                    source.muxes[plan.key] = spare.pop(0)
        leftover = [uuid for uuids in untracked.values() for uuid in uuids]
        if leftover:
            admin.delete(leftover)
            result.removed += len(leftover)
        checkpoint()

    wanted = {plan.key for plan in plans}
    stale = [key for key in source.muxes if key not in wanted]
    total = len(plans) + len(stale)
    done = 0
    changes = []
    created_since_checkpoint = 0
    for plan in plans:
        if cancelled():
            result.cancelled = True
            break
        conf = mux_conf(plan)
        uuid = source.muxes.get(plan.key)
        if uuid:
            if _differs(conf, rows[uuid]):
                changes.append(dict(conf, uuid=uuid))
        else:
            source.muxes[plan.key] = admin.create_mux(source.network_uuid, conf)
            result.added += 1
            created_since_checkpoint += 1
            if created_since_checkpoint >= CHECKPOINT_EVERY:
                checkpoint()
                created_since_checkpoint = 0
        done += 1
        progress(done, total)
    if created_since_checkpoint:
        checkpoint()

    if changes:
        admin.save(changes)
        result.updated = len(changes)

    if not result.cancelled and stale:
        admin.delete([source.muxes[key] for key in stale])
        for key in stale:
            del source.muxes[key]
        result.removed += len(stale)
        checkpoint()
        progress(total, total)

    tags = set(source.tags)
    for plan in plans:
        tags.update(plan.groups)
    source.tags = sorted(tags)
    checkpoint()
    if refresh and not result.cancelled:
        admin.scan_network(source.network_uuid)
    # Hide the new channels before the bouquet maps them.
    apply_checks(admin, source)
    admin.map_network_bouquet(source.network_uuid)
    return result


def apply_checks(admin, source: PlaylistSource):
    """Show channels whose stream passed the server's scan and hide those that failed.

    A mux waiting for its first scan stays hidden; one being scanned again
    keeps its last verdict. Returns (checked, total, names that failed).
    """
    ours = set(source.muxes.values())
    rows = [row for row in admin.list_muxes(source.network_uuid) if row.get('uuid') in ours]
    wanted = {}
    checked = 0
    failed = []
    for row in rows:
        result = row.get('scan_result', SCAN_NONE)
        if row.get('scan_state', SCAN_IDLE) != SCAN_IDLE:
            if result == SCAN_NONE:
                wanted[row['uuid']] = False
            continue
        checked += 1
        if result == SCAN_NONE:
            continue
        wanted[row['uuid']] = result in SCAN_PASSED
        if not wanted[row['uuid']]:
            failed.append(row.get('name') or row.get('iptv_sname') or '')
    changes = []
    for service in admin.list_services(wanted):
        want = wanted.get(service.get('multiplex_uuid'))
        if want is not None and bool(service.get('enabled')) != want:
            changes.append({'uuid': service['uuid'], 'enabled': want})
    if changes:
        admin.save(changes)
    return checked, len(rows), failed


def wait_for_checks(
    admin,
    source: PlaylistSource,
    result: SyncResult,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    sleep=time.sleep,
) -> None:
    """Apply scan verdicts as the server finishes them, until every mux is checked."""
    progress = progress or (lambda _done, _total: None)
    cancelled = cancelled or (lambda: False)
    while True:
        checked, total, failed = apply_checks(admin, source)
        progress(checked, total)
        if checked >= total or cancelled():
            break
        sleep(CHECK_POLL_SECONDS)
    result.check_stopped = checked < total
    result.working = checked - len(failed)
    result.not_working = failed
    result.skipped.extend(SkippedEntry(name, NOT_WORKING) for name in failed)


def remove_playlist(admin, source: PlaylistSource) -> None:
    """Delete the playlist's network, its channels, and tags no other channel uses."""
    if admin.network_exists(source.network_uuid):
        admin.delete_network(source.network_uuid)
    admin.delete_unused_tags(source.tags)
    source.network_uuid = ''
    source.muxes = {}
    source.tags = []


def _differs(conf: dict, row: dict) -> bool:
    for key, value in conf.items():
        if _normal(value) != _normal(row.get(key, '')):
            return True
    return False


def _normal(value) -> str:
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)

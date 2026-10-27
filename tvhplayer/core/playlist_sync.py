"""Write a playlist's channels to a Tvheadend server and keep them in sync. No Qt imports.

Each imported playlist is one IPTV network. Its muxes get their service
without a scan (Service ID 1), and the network's bouquet maps them to
channels. An entry keeps its mux across refreshes through its key, so a
changed stream address or name edits the channel instead of replacing it.

Tvheadend still scans each new mux once, and a refresh scans the muxes
whose stream address changed. Only a mux whose scan passed keeps its
service enabled; disabling a service makes the bouquet delete its channel,
so dead streams never show. Checking a playlist scans all its muxes again.

Tvheadend 4.2 has no network bouquet, so there TVHplayer does its work:
``map_channels`` gives each enabled service a channel and deletes the
channels of disabled ones, and the channels of a mux go before the mux.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .errors import PlaylistError, TvhAuthError, TvhConnectionError
from .ffmpeg_starter import install_starter
from .playlist import NO_CHANNELS, ChannelPlan, SkippedEntry, _quote, ffmpeg_input

BUILTIN_SERVER_KEY = 'builtin'
# Distro packages and the common Docker images install ffmpeg here. A bare
# name can match ffmpegthumbnailer in Tvheadend's PATH lookup (issue 1632).
REMOTE_FFMPEG = '/usr/bin/ffmpeg'
NO_FFMPEG = 'TVHplayer could not find ffmpeg, which it needs to play imported channels.'
# Also how many streams the server tests at once; each failing one waits max_timeout.
# An Xtream Codes account that allows fewer gets its own limit: a stream over it
# would cut off the oldest, and a viewer takes the place of a test, never the reverse.
MAX_STREAMS = 6
CHECKPOINT_EVERY = 50
CHECK_POLL_SECONDS = 2
# Each poll reads every mux and service of the server. A big playlist is read
# less often: a second between polls for every thousand muxes.
MUXES_PER_POLL_SECOND = 1000
CHECK_MUX_FIELDS = ('scan_result', 'scan_state', 'name', 'iptv_sname')
CHECK_SERVICE_FIELDS = ('enabled',)
NOT_WORKING = 'It is not working right now.'
NETWORK_GONE = 'The channels from this playlist are no longer on the server. Import it again.'

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
    # Seconds a source may stay silent. Some streams need 20 s to send their first data.
    'max_timeout': 30,
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
    # Streams the provider account allows at once; 0 when unknown.
    max_streams: int = 0
    # Groups whose channels are added, or None for every group, including
    # groups the playlist gains later. A channel counts as being in its first group.
    chosen_groups: Optional[List[str]] = None
    # Keys of channels left out of the chosen groups.
    left_out: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        muxes = data.get('muxes') if isinstance(data.get('muxes'), dict) else {}
        chosen = data.get('chosen_groups')
        return cls(
            name=str(data.get('name') or ''),
            location=str(data.get('location') or ''),
            server=str(data.get('server') or ''),
            network_uuid=str(data.get('network_uuid') or ''),
            muxes={str(key): str(value) for key, value in muxes.items()},
            allow_commands=bool(data.get('allow_commands')),
            tags=[str(tag) for tag in data.get('tags') or [] if tag],
            max_streams=_count(data.get('max_streams')),
            chosen_groups=[str(group) for group in chosen] if isinstance(chosen, list) else None,
            left_out=[str(key) for key in data.get('left_out') or [] if key],
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
            'max_streams': self.max_streams,
            'chosen_groups': list(self.chosen_groups) if self.chosen_groups is not None else None,
            'left_out': list(self.left_out),
        }

    def stream_limit(self) -> int:
        """The network's max_streams: the account's limit, at most MAX_STREAMS."""
        return min(self.max_streams, MAX_STREAMS) if self.max_streams > 0 else MAX_STREAMS


def _count(value) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: List[SkippedEntry] = field(default_factory=list)
    cancelled: bool = False
    guide_failed: bool = False
    # Films and series episodes the playlist lists, which are not imported.
    films: int = 0
    # Channels whose stream passed the server's scan, names of those that failed,
    # and how many the server finished without a verdict.
    working: int = 0
    not_working: List[str] = field(default_factory=list)
    untested: int = 0
    check_stopped: bool = False


def plan_group(plan: ChannelPlan) -> str:
    """The group a channel is chosen by: its first, or '' when it has none."""
    return plan.groups[0] if plan.groups else ''


def chosen_plans(source: PlaylistSource, plans: List[ChannelPlan]) -> List[ChannelPlan]:
    """The channels of ``plans`` the user chose to add."""
    groups = None if source.chosen_groups is None else set(source.chosen_groups)
    left_out = set(source.left_out)
    return [
        plan for plan in plans
        if plan.key not in left_out and (groups is None or plan_group(plan) in groups)
    ]


def choose_channels(source: PlaylistSource, plans: List[ChannelPlan], keys) -> None:
    """Save that of ``plans`` only those with one of ``keys`` are added.

    With every group kept, groups the playlist gains later are added too;
    otherwise they are left out. New channels in a kept group are added.
    """
    keys = set(keys)
    every = {plan_group(plan) for plan in plans}
    kept = {plan_group(plan) for plan in plans if plan.key in keys}
    source.chosen_groups = None if kept == every else sorted(kept)
    source.left_out = sorted(plan.key for plan in plans if plan.key not in keys and plan_group(plan) in kept)


def server_key(server) -> str:
    """How a playlist source names its server: ``builtin`` or the server URL."""
    if server.get('builtin'):
        return BUILTIN_SERVER_KEY
    return (server.get('url') or '').strip().rstrip('/')


def ffmpeg_for_server(server, which=shutil.which, starter=install_starter) -> str:
    """The ffmpeg Tvheadend should run. The built-in server shares this app's PATH.

    The built-in server runs the app's stand-in, which opens one quality of an HLS stream.
    """
    if server.get('builtin'):
        path = which('ffmpeg')
        if not path:
            raise PlaylistError(NO_FFMPEG)
        return starter(path) or path
    return REMOTE_FFMPEG


def retarget_commands(rows, ffmpeg: str, others) -> List[dict]:
    """Mux changes that make commands starting with one of ``others`` run ``ffmpeg`` instead."""
    wanted = 'pipe://' + _quote(ffmpeg) + ' '
    unwanted = ['pipe://' + _quote(other) + ' ' for other in others if other and other != ffmpeg]
    changes = []
    for row in rows:
        url = row.get('iptv_url') or ''
        for prefix in unwanted:
            if row.get('uuid') and url.startswith(prefix):
                changes.append({'uuid': row['uuid'], 'iptv_url': wanted + url[len(prefix):]})
                break
    return changes


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
        message = f'Added {_channels(result.added)} from {name}.'
        if failed:
            message += (
                ' 1 is hidden because it is not working.' if failed == 1
                else f' {failed} are hidden because they are not working.'
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
        message += ' Channels that were not checked yet stay in the list.'
    count = sum(1 for entry in result.skipped if entry.reason != NOT_WORKING)
    if count:
        message += ' 1 entry could not be added.' if count == 1 else f' {count} entries could not be added.'
    if result.guide_failed:
        message += ' The program guide could not be loaded.'
    if result.films and first_import:
        message += (
            ' 1 film or series episode was left out' if result.films == 1
            else f' {result.films:,} films and series episodes were left out'
        ) + ' because TVHplayer imports only TV channels.'
    return message


def check_message(name: str, result: SyncResult) -> str:
    """What a check of every channel, started from Settings, found."""
    failed = len(result.not_working)
    untested = result.untested
    if result.check_stopped:
        message = f'Stopped checking the channels from {name}.'
    elif failed or untested:
        message = f'Checked the channels from {name}: {result.working} working.'
    else:
        return f'Checked the channels from {name}: all {result.working} are working.'
    if failed:
        message += (
            ' 1 is hidden because it is not working.' if failed == 1
            else f' {failed} are hidden because they are not working.'
        )
    if untested:
        message += (
            ' 1 could not be tested and stays in the list.' if untested == 1
            else f' {untested} could not be tested and stay in the list.'
        )
    return message


def show_all_channels(admin, source: PlaylistSource) -> int:
    """Show every channel of the playlist again. Returns how many were hidden."""
    if not admin.network_exists(source.network_uuid):
        return 0
    shown = apply_checks(admin, source, hide_failed=False)[3]
    if shown:
        _map_without_bouquet(admin, source)
    return shown


def error_message(exc: Exception, server_name: str, verb: str = 'add') -> str:
    """Plain words for a failed import, removal, check, or show (``verb``)."""
    if isinstance(exc, PlaylistError):
        return str(exc)
    if isinstance(exc, TvhAuthError):
        return (
            f'This account cannot add channels to {server_name}. '
            'Sign in with an administrator account in Manage Servers.'
        )
    if isinstance(exc, TvhConnectionError):
        return f'Could not reach {server_name}. Check that it is running and that its address is right.'
    return f'{server_name} could not {verb} the channels: {exc}'


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
    check: bool = True,
) -> SyncResult:
    """Create, update, and remove muxes so the network matches ``plans``.

    With ``check`` a refresh tests the streams whose address changed and
    hides channels known not to work; the others keep their last verdict
    until the playlist is checked. Without it visibility is left alone.
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
        conf = dict(NETWORK_CONF, networkname=source.name, max_streams=source.stream_limit())
        source.network_uuid = admin.create_network(conf)
        source.muxes = {}
        checkpoint()
    else:
        # A switched-off network is never scanned and its channels do not play.
        admin.update_network(source.network_uuid, {
            'enabled': True,
            'max_timeout': NETWORK_CONF['max_timeout'],
            'max_streams': source.stream_limit(),
        })
    bouquets = admin.has_network_bouquets(source.network_uuid)

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
            if not bouquets:
                _delete_channels_of(admin, leftover)
            admin.delete(leftover)
            result.removed += len(leftover)
        checkpoint()

    wanted = {plan.key for plan in plans}
    stale = [key for key in source.muxes if key not in wanted]
    total = len(plans) + len(stale)
    done = 0
    changes = []
    # A new address may work where the old one failed, or fail where it worked.
    retest = []
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
                if _stream_source(conf['iptv_url']) != _stream_source(rows[uuid].get('iptv_url', '')):
                    retest.append(uuid)
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
        if not bouquets:
            _delete_channels_of(admin, [source.muxes[key] for key in stale])
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
    if check and retest and not result.cancelled:
        admin.scan_muxes(retest)
    if check:
        # Hide channels already known not to work before the bouquet maps them.
        apply_checks(admin, source)
    if bouquets:
        admin.map_network_bouquet(source.network_uuid)
        if refresh:
            admin.delete_orphan_channels(source.network_uuid)
    else:
        map_channels(admin, source)
    return result


def map_channels(admin, source: PlaylistSource) -> int:
    """Do the network bouquet's work on a server without one (Tvheadend 4.2).

    Each enabled service gets a channel, which takes its name, number and
    icon from the service, and tags named after the mux's groups. A channel
    whose services are all disabled is deleted. Returns how many channels
    were added or deleted.
    """
    muxes = {row['uuid']: row for row in admin.list_muxes(source.network_uuid, fields=('iptv_tags',))}
    services = admin.list_services(muxes, fields=('enabled',))
    ours = {row['uuid'] for row in services}
    enabled = {row['uuid'] for row in services if row.get('enabled')}
    mapped = set()
    unwanted = []
    for channel in admin.list_channels():
        linked = set(channel.get('services') or [])
        if not linked & ours:
            continue
        mapped |= linked
        # A channel the user also gave another service stays.
        if linked <= ours and not linked & enabled:
            unwanted.append(channel['uuid'])
    admin.delete(unwanted)

    # Tvheadend matches tag names without regard to case.
    tags = {}
    for row in admin.list_channel_tags():
        tags.setdefault((row.get('name') or '').lower(), row.get('uuid'))
    added = 0
    for service in services:
        if service['uuid'] in mapped or service['uuid'] not in enabled:
            continue
        mux = muxes.get(service.get('multiplex_uuid')) or {}
        tag_uuids = []
        for name in (mux.get('iptv_tags') or '').split('\n'):
            name = name.strip()
            if not name:
                continue
            if not tags.get(name.lower()):
                tags[name.lower()] = admin.create_channel_tag({'name': name, 'enabled': True})
            tag_uuids.append(tags[name.lower()])
        admin.create_channel({'enabled': True, 'services': [service['uuid']], 'tags': tag_uuids})
        added += 1
    return added + len(unwanted)


def _map_without_bouquet(admin, source: PlaylistSource) -> None:
    if not admin.has_network_bouquets(source.network_uuid):
        map_channels(admin, source)


def _delete_channels_of(admin, mux_uuids) -> None:
    """Delete the channels of these muxes, which Tvheadend 4.2 keeps without a stream."""
    services = {row['uuid'] for row in admin.list_services(set(mux_uuids), fields=('enabled',))}
    if services:
        admin.delete([
            row['uuid'] for row in admin.list_channels()
            if row.get('services') and set(row['services']) <= services
        ])


def apply_checks(admin, source: PlaylistSource, hide_failed: bool = True):
    """Hide channels whose stream failed the server's scan and show the rest.

    A mux not scanned yet is shown; one being scanned again follows its last
    verdict until the new one arrives. Without ``hide_failed`` every channel
    is shown. Returns (checked, total, names that failed, number of channels
    shown or hidden, number checked without a verdict). A mux the server is
    done with but never scanned, such as a disabled one, counts as checked
    without a verdict.
    """
    ours = set(source.muxes.values())
    rows = [
        row for row in admin.list_muxes(source.network_uuid, fields=CHECK_MUX_FIELDS)
        if row.get('uuid') in ours
    ]
    wanted = {}
    checked = 0
    untested = 0
    failed = []
    for row in rows:
        result = row.get('scan_result', SCAN_NONE)
        dead = result not in SCAN_PASSED and result != SCAN_NONE
        wanted[row['uuid']] = not (dead and hide_failed)
        if row.get('scan_state', SCAN_IDLE) != SCAN_IDLE:
            continue
        checked += 1
        if dead:
            failed.append(row.get('name') or row.get('iptv_sname') or '')
        elif result == SCAN_NONE:
            untested += 1
    changes = []
    for service in admin.list_services(wanted, fields=CHECK_SERVICE_FIELDS):
        want = wanted.get(service.get('multiplex_uuid'))
        if want is not None and bool(service.get('enabled')) != want:
            changes.append({'uuid': service['uuid'], 'enabled': want})
    if changes:
        admin.save(changes)
    return checked, len(rows), failed, len(changes), untested


def wait_for_checks(
    admin,
    source: PlaylistSource,
    result: SyncResult,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    changed: Optional[Callable[[], None]] = None,
    sleep=time.sleep,
) -> None:
    """Apply scan verdicts as the server finishes them, until every mux is checked.

    ``changed`` is called whenever channels were shown or hidden.
    """
    progress = progress or (lambda _done, _total: None)
    cancelled = cancelled or (lambda: False)
    changed = changed or (lambda: None)
    while True:
        checked, total, failed, shown_or_hidden, untested = apply_checks(admin, source)
        if shown_or_hidden:
            _map_without_bouquet(admin, source)
            changed()
        progress(checked, total)
        if checked >= total or cancelled():
            break
        waited = 0
        while waited < max(CHECK_POLL_SECONDS, total / MUXES_PER_POLL_SECOND) and not cancelled():
            sleep(CHECK_POLL_SECONDS)
            waited += CHECK_POLL_SECONDS
    result.check_stopped = checked < total
    result.working = checked - len(failed) - untested
    result.not_working = failed
    result.untested = untested
    result.skipped.extend(SkippedEntry(name, NOT_WORKING) for name in failed)


def remove_playlist(admin, source: PlaylistSource) -> None:
    """Delete the playlist's network, its channels, and tags no other channel uses."""
    if admin.network_exists(source.network_uuid):
        if not admin.has_network_bouquets(source.network_uuid):
            _delete_channels_of(admin, [row['uuid'] for row in admin.list_muxes(source.network_uuid, fields=('uuid',))])
        admin.delete_network(source.network_uuid)
    admin.delete_unused_tags(source.tags)
    source.network_uuid = ''
    source.muxes = {}
    source.tags = []


def _stream_source(url) -> tuple:
    """What a mux plays: the input of an ffmpeg wrapper, which also names the channel, else the address."""
    url = str(url or '')
    wrapped = ffmpeg_input(url[7:]) if url.startswith('pipe://') else None
    if wrapped is None:
        return url, ()
    address, headers = wrapped
    return address, tuple(sorted(headers.items()))


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

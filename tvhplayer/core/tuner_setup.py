"""Set up tuner channels on a server: network, scan, and channels. No Qt imports.

The steps the first-run wizard runs, in order:

1. ``read_tuners`` finds the tuners (``tuners.py``).
2. ``scan_regions`` lists the server's scan tables for the tuner type, from
   the dtv-scan-tables built into Tvheadend.
3. ``create_tuner_network`` makes a network with the chosen table, gives it
   the chosen tuners, and starts the scan.
4. ``scan_progress`` follows the muxes until each has a result, and what
   the tuners saw on each.
5. ``plan_channels`` picks the services to make channels of, and
   ``map_services`` asks the server to make them.
6. ``follow_new_channels`` counts the channels made, and names those whose
   name never arrived.
7. ``scan_summary`` says how it went.

Tvheadend grabs the over-the-air guide on its own once channels exist.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from .errors import TvhError
from .guide import parse_input_status
from .playback_status import SIGNAL_FAIR, SIGNAL_GOOD, SIGNAL_NONE, SIGNAL_POOR, signal_report
from .tuners import Tuner

# Tuner type -> (network class, scan table type).
NETWORKS = {
    'DVB-T': ('dvb_network_dvbt', 'dvbt'),
    'DVB-C': ('dvb_network_dvbc', 'dvbc'),
    'DVB-S': ('dvb_network_dvbs', 'dvbs'),
    'ATSC-T': ('dvb_network_atsc_t', 'atsc-t'),
    'ATSC-C': ('dvb_network_atsc_c', 'atsc-c'),
    'ISDB-T': ('dvb_network_isdb_t', 'isdb-t'),
}
# What each type receives, in words.
KIND_WORDS = {
    'DVB-T': 'Aerial (DVB-T/T2)',
    'DVB-C': 'Cable (DVB-C)',
    'DVB-S': 'Satellite dish (DVB-S/S2)',
    'ATSC-T': 'Aerial (ATSC)',
    'ATSC-C': 'Cable (ATSC/QAM)',
    'ISDB-T': 'Aerial (ISDB-T)',
}
# Mux scan_state and scan_result values (Tvheadend's mpegts.h).
SCAN_IDLE = 0
SCAN_ACTIVE = 3
RESULT_NONE = 0
RESULT_OK = 1
RESULT_FAIL = 2
RESULT_PARTIAL = 3
RESULT_IGNORE = 4
# Tvheadend's names for picture and sound streams (SCT_ISVIDEO and
# SCT_ISAUDIO in esstream.h, named in streaming.c).
AV_STREAMS = {
    'MPEG2VIDEO', 'H264', 'HEVC', 'VP8', 'VP9', 'THEORA',
    'MPEG2AUDIO', 'AC3', 'EAC3', 'AAC', 'AAC-LATM', 'VORBIS', 'OPUS', 'FLAC', 'AC-4',
}
# US broadcast channels: (first, last, centre of first in MHz).
US_RF_BANDS = ((2, 4, 57), (5, 6, 79), (7, 13, 177), (14, 69, 473))


def supported(kind: str) -> bool:
    return kind in NETWORKS


def scan_regions(admin, kind: str, *, canonical=False) -> List[Tuple[str, str]]:
    """``(key, label)`` of every scan table for this tuner type, sorted by label."""
    _class, table = NETWORKS[kind]
    if canonical:
        table = {'dvbt': 'dvb-t', 'dvbc': 'dvb-c', 'dvbs': 'dvb-s', 'isdb-t': 'isdb-t'}.get(table, table)
    # The bundled server loads its tables asynchronously after HTTP is ready.
    # Retry that specific transient 400 only for the Windows built-in path.
    deadline = time.monotonic() + 2
    while True:
        try:
            data = admin.request('api/dvb/scanfile/list', params={'type': table})
            break
        except TvhError as exc:
            if not canonical or not str(exc).startswith('HTTP 400 for api/dvb/scanfile/list:') or time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    rows = data.get('entries') if isinstance(data, dict) else None
    regions = [(row['key'], row.get('val') or row['key']) for row in rows or [] if row.get('key')]
    return sorted(regions, key=lambda item: item[1].lower())


def network_name(kind: str, region_label: str) -> str:
    region = region_label.split(':', 1)[-1].strip() or region_label
    return f'{kind} {region}'.strip()


def tuner_node_for_networks(admin, tuner: Tuner) -> str:
    """The node that takes the tuner's networks.

    A satellite tuner gives its networks to the dish settings below it, when
    the server made them; other tuners take them themselves.
    """
    if tuner.kind != 'DVB-S':
        return tuner.uuid
    for node in admin.hardware_tree(tuner.uuid):
        params = {p.get('id'): p.get('value') for p in node.get('params') or [] if isinstance(p, dict)}
        if 'networks' in params and node.get('uuid'):
            return node['uuid']
        for child in admin.hardware_tree(node.get('uuid') or '') if not node.get('leaf') else []:
            params = {p.get('id'): p.get('value') for p in child.get('params') or [] if isinstance(p, dict)}
            if 'networks' in params and child.get('uuid'):
                return child['uuid']
    return tuner.uuid


def create_tuner_network(admin, kind: str, scanfile: str, name: str, tuners: Iterable[Tuner]) -> str:
    """Make the network, hand it the tuners, and start the scan. Returns the network's uuid."""
    network_class, _table = NETWORKS[kind]
    data = admin.request(
        'api/mpegts/network/create',
        data={'class': network_class, 'conf': json.dumps({
            'networkname': name,
            'scanfile': scanfile,
        })},
    )
    uuid = data.get('uuid') if isinstance(data, dict) else ''
    if not uuid:
        raise ValueError('The server did not create the network')
    nodes = []
    for tuner in tuners:
        nodes.append({'uuid': tuner.uuid, 'enabled': True})
        target = tuner_node_for_networks(admin, tuner)
        networks = list(dict.fromkeys([*tuner.networks, uuid]))
        if target == tuner.uuid:
            nodes[-1]['networks'] = networks
        else:
            nodes.append({'uuid': target, 'enabled': True, 'networks': [uuid]})
    admin.save(nodes)
    admin.scan_network(uuid)
    return uuid


# What a frequency came to, in the scan.
FREQ_WAITING = 'waiting'        # not scanned yet
FREQ_SCANNING = 'scanning'      # a tuner is on it now
FREQ_CHANNELS = 'channels'      # received, with channels
FREQ_EMPTY = 'empty'            # received, but no channels on it
FREQ_NO_SIGNAL = 'no_signal'    # no station, or too weak; normal for most frequencies
FREQ_NO_DATA = 'no_data'        # the tuner locked on, but no data reached the server
FREQ_SKIPPED = 'skipped'        # left out of the scan


@dataclass
class Reception:
    """The best a tuner did on one frequency while it was being scanned."""

    level: str = SIGNAL_NONE
    words: str = ''
    data: bool = False


@dataclass
class Frequency:
    uuid: str
    label: str
    frequency: int = 0
    state: str = FREQ_WAITING
    services: int = 0
    reception: Optional[Reception] = None


@dataclass
class ScanProgress:
    muxes: int = 0
    scanned: int = 0
    working: int = 0
    services: int = 0
    frequencies: List[Frequency] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.muxes > 0 and self.scanned >= self.muxes

    def count(self, state: str) -> int:
        return sum(1 for item in self.frequencies if item.state == state)


def frequency_label(mux: dict) -> str:
    """``RF 26 (545 MHz)`` for ATSC, else the server's name for the mux, like ``554MHz``."""
    name = (mux.get('name') or '').strip()
    if mux.get('delsys') in ('ATSC-T', 'ATSC'):
        channel = us_rf_channel(mux.get('frequency'))
        if channel is not None:
            return f'RF {channel} ({name})' if name else f'RF {channel}'
    return name or 'Frequency'


def _better(old: Optional[Reception], new: Reception) -> Reception:
    if old is None:
        return new
    rank = {SIGNAL_NONE: 0, SIGNAL_POOR: 1, SIGNAL_FAIR: 2, SIGNAL_GOOD: 3}
    best = new if rank.get(new.level, 0) >= rank.get(old.level, 0) else old
    return Reception(best.level, best.words, old.data or new.data)


def _frequency_state(mux: dict, reception: Optional[Reception]) -> str:
    state = int(mux.get('scan_state') or 0)
    result = int(mux.get('scan_result') or 0)
    if state != SCAN_IDLE:
        return FREQ_SCANNING if state == SCAN_ACTIVE else FREQ_WAITING
    if result == RESULT_NONE:
        return FREQ_WAITING
    if result == RESULT_IGNORE:
        return FREQ_SKIPPED
    if result in (RESULT_OK, RESULT_PARTIAL):
        return FREQ_CHANNELS if int(mux.get('num_svc') or 0) else FREQ_EMPTY
    # Failed. Tvheadend does not say why; what the tuner saw while on it does.
    if reception is not None and reception.data:
        return FREQ_EMPTY
    if reception is not None and reception.level in (SIGNAL_GOOD, SIGNAL_FAIR):
        return FREQ_NO_DATA
    return FREQ_NO_SIGNAL


def scan_progress(admin, network_uuid: str, seen: Optional[dict] = None) -> ScanProgress:
    """Where the scan is, frequency by frequency.

    ``seen`` keeps, across calls, what the tuners reported for each frequency
    while it was scanned: a frequency that failed with a good signal but no
    data points at the network between tuner and server, not at the aerial.
    """
    seen = {} if seen is None else seen
    muxes = admin.list_muxes(network_uuid)
    if any(int(mux.get('scan_state') or 0) == SCAN_ACTIVE for mux in muxes):
        _note_reception(admin, muxes, seen)
    progress = ScanProgress()
    for mux in muxes:
        progress.muxes += 1
        state = int(mux.get('scan_state') or 0)
        result = int(mux.get('scan_result') or 0)
        if state == SCAN_IDLE and result != RESULT_NONE:
            progress.scanned += 1
        if result in (RESULT_OK, RESULT_PARTIAL):
            progress.working += 1
        progress.services += int(mux.get('num_svc') or 0)
        uuid = mux.get('uuid') or ''
        progress.frequencies.append(Frequency(
            uuid=uuid,
            label=frequency_label(mux),
            frequency=int(mux.get('frequency') or 0),
            state=_frequency_state(mux, seen.get(uuid)),
            services=int(mux.get('num_svc') or 0),
            reception=seen.get(uuid),
        ))
    progress.frequencies.sort(key=lambda item: (item.frequency, item.label))
    return progress


def _note_reception(admin, muxes, seen: dict) -> None:
    """Record what each busy tuner reports for the frequency it is scanning."""
    data = admin.request('api/status/inputs')
    rows = data.get('entries') if isinstance(data, dict) else None
    by_stream = {f"{mux.get('name')} in {mux.get('network')}": mux.get('uuid') for mux in muxes
                 if int(mux.get('scan_state') or 0) == SCAN_ACTIVE and mux.get('uuid')}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        uuid = by_stream.get(str(row.get('stream') or ''))
        if not uuid:
            continue
        tuner = parse_input_status(row)
        report = signal_report(tuner)
        level, words = report if report else (SIGNAL_NONE, '')
        seen[uuid] = _better(seen.get(uuid), Reception(level, words, bool(tuner.bps)))


def _has_picture_or_sound(admin, service_uuid: str) -> bool:
    data = admin.request('api/service/streams', params={'uuid': service_uuid})
    streams = data.get('streams') if isinstance(data, dict) else None
    return any(isinstance(stream, dict) and stream.get('type') in AV_STREAMS for stream in streams or [])


@dataclass
class ChannelPlan:
    """The services to make channels of, and what the scan left unclear about them."""

    services: List[str] = field(default_factory=list)
    # Named services the server knows no picture or sound for. They are kept,
    # as the streams can still come when the channel is tuned, but some do
    # not play (Tvheadend issue #2372, on ATSC).
    silent: int = 0


def plan_channels(admin, network_uuid: str, include_encrypted: bool = False) -> ChannelPlan:
    """The services to make channels of.

    A service without a name is taken only when it carries picture or sound:
    a real channel whose name table did not arrive in the scan, rather than
    a data or update service. ``follow_new_channels`` names it afterwards.
    """
    muxes = [mux['uuid'] for mux in admin.list_muxes(network_uuid) if mux.get('uuid')]
    plan = ChannelPlan()
    for service in admin.list_services(muxes):
        if not service.get('uuid'):
            continue
        if service.get('encrypted') and not include_encrypted:
            continue
        if service.get('channel'):
            continue
        audible = _has_picture_or_sound(admin, service['uuid'])
        if not (service.get('svcname') or '').strip():
            if not audible:
                continue
        elif not audible:
            plan.silent += 1
        plan.services.append(service['uuid'])
    return plan


def services_to_map(admin, network_uuid: str, include_encrypted: bool = False) -> List[str]:
    return plan_channels(admin, network_uuid, include_encrypted).services


def us_rf_channel(frequency_hz) -> Optional[int]:
    """The US broadcast channel (2-69) whose centre is this frequency, or None."""
    try:
        mhz = float(frequency_hz) / 1e6
    except (TypeError, ValueError):
        return None
    for first, last, centre in US_RF_BANDS:
        channel = first + round((mhz - centre) / 6)
        if first <= channel <= last and abs(mhz - centre - 6 * (channel - first)) < 3:
            return channel
    return None


def fallback_name(mux: dict, sid) -> str:
    """A name for a channel whose name never arrived: ``RF 22 – 3`` for ATSC, else the frequency."""
    program = f' – {sid}' if sid not in (None, '') else ''
    if mux.get('delsys') in ('ATSC-T', 'ATSC'):
        channel = us_rf_channel(mux.get('frequency'))
        if channel is not None:
            return f'RF {channel}{program}'
    place = (mux.get('name') or '').strip()
    if place:
        return f'{place}{program}'
    return f'Channel {sid}' if program else 'Channel'


def follow_new_channels(admin, network_uuid: str, services: Iterable[str], named: set) -> Tuple[int, int]:
    """``(made, waiting)``: services of ``services`` that have a channel now, and those still without.

    The server makes the channels a few seconds after it is asked to, when
    it next saves its settings, and its mapper status still shows the run
    before until then; so this counts the channels themselves.

    Channels of services without a name, which the server names like
    ``net/mux/{PMT:48}``, get a readable name. ``named`` holds the channels
    renamed so far, so each is renamed once.
    """
    wanted = set(services)
    muxes = {mux['uuid']: mux for mux in admin.list_muxes(network_uuid) if mux.get('uuid')}
    nodes = []
    made = waiting = 0
    for service in admin.list_services(muxes):
        if service.get('uuid') not in wanted:
            continue
        channels = [channel for channel in service.get('channel') or [] if channel]
        if not channels:
            waiting += 1
            continue
        made += 1
        if (service.get('svcname') or '').strip():
            continue
        name = fallback_name(muxes.get(service.get('multiplex_uuid')) or {}, service.get('sid'))
        nodes.extend({'uuid': channel, 'name': name} for channel in channels if channel not in named)
    if nodes:
        admin.save(nodes)
        named.update(node['uuid'] for node in nodes)
    return made, waiting


def _count(number: int, one: str, many: str) -> str:
    return f'{number} {one if number == 1 else many}'


def scan_summary(progress: ScanProgress, plan: ChannelPlan, made: int) -> str:
    """What the scan came to, in words: the channels added, and what went wrong if anything did."""
    lines = []
    if made:
        lines.append(f"Added {_count(made, 'channel', 'channels')}.")
    elif plan.services:
        lines.append(f"The server did not add any of the {_count(len(plan.services), 'channel', 'channels')} found.")
    else:
        lines.append('No channels were found.')
    no_data = progress.count(FREQ_NO_DATA)
    if no_data:
        lines.append(
            f"On {_count(no_data, 'frequency', 'frequencies')} the tuner found a signal, but no data reached "
            'the server. A firewall on the server computer, or a weak Wi-Fi or network connection, can cause this.'
        )
    elif not plan.services:
        received = progress.count(FREQ_CHANNELS) + progress.count(FREQ_EMPTY)
        if progress.frequencies and not received:
            lines.append('No frequency had a signal. Check that the aerial, cable, or dish is connected to the tuner, '
                         'and that you chose the right region or satellite.')
        else:
            lines.append('Check that the aerial, cable, or dish is connected to the tuner, '
                         'or run Set Up Channels again with another region.')
    if plan.silent:
        lines.append(f"{_count(plan.silent, 'channel has', 'channels have')} no picture or sound information "
                     'from the scan and may not play.')
    if made:
        lines.append('The TV guide fills in over the next minutes as the channels broadcast it.')
    return ' '.join(lines)


def map_services(admin, services: List[str]) -> None:
    """Make a channel of each service, tagged TV or Radio."""
    if not services:
        return
    admin.request('api/service/mapper/save', data={'node': json.dumps({
        'services': services,
        'check_availability': False,
        'encrypted': True,
        'merge_same_name': False,
        'tidy_channel_name': True,
        'type_tags': True,
        'provider_tags': False,
        'network_tags': False,
    })})


def mapper_progress(admin) -> Tuple[int, int]:
    """``(handled, total)`` of the channel mapping that is running."""
    data = admin.request('api/service/mapper/status')
    if not isinstance(data, dict):
        return 0, 0
    total = int(data.get('total') or 0)
    handled = int(data.get('ok') or 0) + int(data.get('fail') or 0) + int(data.get('ignore') or 0)
    return handled, total


def discover_satip(admin) -> None:
    """Ask the server to look for SAT>IP tuners on the network now."""
    admin.request('api/hardware/satip/discover', data={'op': 'all'})

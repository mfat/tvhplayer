"""Set up tuner channels on a server: network, scan, and channels. No Qt imports.

The steps the first-run wizard runs, in order:

1. ``read_tuners`` finds the tuners (``tuners.py``).
2. ``scan_regions`` lists the server's scan tables for the tuner type, from
   the dtv-scan-tables built into Tvheadend.
3. ``create_tuner_network`` makes a network with the chosen table, gives it
   the chosen tuners, and starts the scan.
4. ``scan_progress`` follows the muxes until each has a result.
5. ``map_services`` turns the services found into channels, and
   ``mapper_progress`` follows that.
6. ``name_unnamed_channels`` names the channels whose name never arrived.

Tvheadend grabs the over-the-air guide on its own once channels exist.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .tuners import Tuner
from .errors import TvhError

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
RESULT_NONE = 0
RESULT_OK = 1
RESULT_PARTIAL = 3
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


@dataclass
class ScanProgress:
    muxes: int = 0
    scanned: int = 0
    working: int = 0
    services: int = 0

    @property
    def done(self) -> bool:
        return self.muxes > 0 and self.scanned >= self.muxes


def scan_progress(admin, network_uuid: str) -> ScanProgress:
    progress = ScanProgress()
    for mux in admin.list_muxes(network_uuid):
        progress.muxes += 1
        state = int(mux.get('scan_state') or 0)
        result = int(mux.get('scan_result') or 0)
        if state == SCAN_IDLE and result != RESULT_NONE:
            progress.scanned += 1
        if result in (RESULT_OK, RESULT_PARTIAL):
            progress.working += 1
        progress.services += int(mux.get('num_svc') or 0)
    return progress


def _has_picture_or_sound(admin, service_uuid: str) -> bool:
    data = admin.request('api/service/streams', params={'uuid': service_uuid})
    streams = data.get('streams') if isinstance(data, dict) else None
    return any(isinstance(stream, dict) and stream.get('type') in AV_STREAMS for stream in streams or [])


def services_to_map(admin, network_uuid: str, include_encrypted: bool = False) -> List[str]:
    """The services to make channels of.

    A service without a name is taken only when it carries picture or sound:
    a real channel whose name table did not arrive in the scan, rather than
    a data or update service. ``name_unnamed_channels`` names it afterwards.
    """
    muxes = [mux['uuid'] for mux in admin.list_muxes(network_uuid) if mux.get('uuid')]
    services = []
    for service in admin.list_services(muxes):
        if not service.get('uuid'):
            continue
        if service.get('encrypted') and not include_encrypted:
            continue
        if service.get('channel'):
            continue
        if not (service.get('svcname') or '').strip() and not _has_picture_or_sound(admin, service['uuid']):
            continue
        services.append(service['uuid'])
    return services


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


def name_unnamed_channels(admin, network_uuid: str, services: Iterable[str], named: set) -> int:
    """Rename the just-made channels of services without a name, which the server names like ``net/mux/{PMT:48}``.

    The server makes the channels a few seconds after it is asked to, so call
    this until it returns 0: the number of such services still without a
    channel. ``named`` holds the channels renamed so far, so each is renamed once.
    """
    wanted = set(services)
    muxes = {mux['uuid']: mux for mux in admin.list_muxes(network_uuid) if mux.get('uuid')}
    nodes = []
    waiting = 0
    for service in admin.list_services(muxes):
        if service.get('uuid') not in wanted or (service.get('svcname') or '').strip():
            continue
        channels = [channel for channel in service.get('channel') or [] if channel]
        if not channels:
            waiting += 1
            continue
        name = fallback_name(muxes.get(service.get('multiplex_uuid')) or {}, service.get('sid'))
        nodes.extend({'uuid': channel, 'name': name} for channel in channels if channel not in named)
    if nodes:
        admin.save(nodes)
        named.update(node['uuid'] for node in nodes)
    return waiting


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

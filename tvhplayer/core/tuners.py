"""The server's tuners, from its hardware tree. No Qt imports.

Tvheadend lists hardware (a DVB adapter, a SAT>IP server, an HDHomeRun) with
its tuners, the frontends, below it. A frontend's class says what it receives,
such as ``linuxdvb_frontend_dvbt`` or ``satip_frontend_dvbs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Frontend class endings and the delivery system they receive.
KINDS = {
    'dvbt': 'DVB-T',
    'dvbc': 'DVB-C',
    'dvbs': 'DVB-S',
    'atsc_t': 'ATSC-T',
    'atsc_c': 'ATSC-C',
    'isdb_t': 'ISDB-T',
    'isdbt': 'ISDB-T',
    'isdb_c': 'ISDB-C',
    'isdb_s': 'ISDB-S',
    'cablecard': 'CableCARD',
    'dab': 'DAB',
}
MAX_DEPTH = 4


@dataclass
class Tuner:
    uuid: str
    name: str
    kind: str
    enabled: bool
    hardware: str = ''
    networks: List[str] = field(default_factory=list)


def tuner_kind(class_name: str) -> str:
    """The delivery system of a frontend class, or '' when it is not a frontend."""
    _prefix, found, rest = (class_name or '').partition('_frontend_')
    if not found:
        return ''
    rest = rest[:-len('_slave')] if rest.endswith('_slave') else rest
    return KINDS.get(rest, rest.upper())


def _params(node) -> dict:
    return {param.get('id'): param.get('value') for param in node.get('params') or [] if isinstance(param, dict)}


def read_tuners(admin) -> List[Tuner]:
    """Every tuner the server found, enabled or not."""
    tuners = []

    def walk(uuid, hardware, depth):
        for node in admin.hardware_tree(uuid):
            if not isinstance(node, dict) or not node.get('uuid'):
                continue
            kind = tuner_kind(node.get('class') or '')
            if kind:
                params = _params(node)
                tuners.append(Tuner(
                    uuid=node['uuid'],
                    name=node.get('text') or params.get('displayname') or kind,
                    kind=kind,
                    enabled=bool(params.get('enabled')),
                    hardware=hardware,
                    networks=[n for n in params.get('networks') or [] if isinstance(n, str)],
                ))
            elif not node.get('leaf') and depth < MAX_DEPTH:
                walk(node['uuid'], hardware or node.get('text') or '', depth + 1)

    walk('root', '', 0)
    return tuners

"""Real Windows + WSLc + HDHomeRun acceptance test.

Starts an isolated built-in server (private config, random ports), points it at
one HDHomeRun, scans a DVB-T region, maps the services that were found, and
plays a channel through the authenticated HTTP MPEG-TS endpoint.

This changes no global WSL setting, firewall rule, or remote server. It does
use the physical tuner, so do not run it while a recording needs that device.

    python windows/backend/hdhomerun-test.py
    python windows/backend/hdhomerun-test.py --region dvbt/auto/dvb-t_auto-Default

Requires the local offline backend bundle and WSLc 2.9.3 or newer.
The default region is Tvheadend's generic auto frequency table.
"""
import argparse
import contextlib
import json
import ipaddress
import socket
import struct
import sys
import threading
import time
import traceback
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QCoreApplication, QTimer
import requests

from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
from tvhplayer.core.builtin_server import read_hdhomerun_transport
from tvhplayer.core.hdhomerun import discover_host_devices, _udp_ports_free
from tvhplayer.core.http_backend import HttpBackend
from tvhplayer.core.logs import sanitize
from tvhplayer.core.models import ServerConfig
from tvhplayer.core.tuner_setup import (create_tuner_network, map_services, mapper_progress,
                                        scan_progress, services_to_map, scan_regions)
from tvhplayer.core.tuners import read_tuners
from tvhplayer.core.tvh_admin import TvhAdmin


def wait_for(predicate, timeout=40, interval=.5, what='condition'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError(f'Timed out waiting for {what}')


class HdHomeRunControl:
    """Minimal libhdhomerun TCP control client (port 65001)."""

    PORT = 65001

    def __init__(self, host):
        self.host = host

    def get(self, name):
        payload = bytes([3, len(name) + 1]) + name.encode() + b'\0'
        packet = struct.pack('>HH', 4, len(payload)) + payload
        packet += struct.pack('<I', zlib.crc32(packet))
        with socket.create_connection((self.host, self.PORT), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(packet)
            kind, length = struct.unpack('>HH', self._read(sock, 4))
            body = self._read(sock, length + 4)
        if kind != 5:
            raise RuntimeError(f'unexpected HDHomeRun reply type {kind}')
        if struct.unpack('<I', body[-4:])[0] != zlib.crc32(struct.pack('>HH', kind, length) + body[:-4]):
            raise RuntimeError('HDHomeRun control reply checksum mismatch')
        tags = {}
        pos = 0
        while pos + 2 <= length:
            tag, size = body[pos], body[pos + 1]
            pos += 2
            if size & 0x80:
                size = (size & 0x7F) | (body[pos] << 7)
                pos += 1
            tags[tag] = body[pos:pos + size].rstrip(b'\0').decode('ascii', 'replace')
            pos += size
        return tags

    @staticmethod
    def _read(sock, count):
        data = b''
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise RuntimeError('HDHomeRun closed the control connection')
            data += chunk
        return data


def transport_targets(control, tuners, transport):
    """Targets the device reports for the frontends, while a scan is running."""
    targets = {}
    for tuner in range(max(1, len(tuners))):
        try:
            value = control.get(f'/tuner{tuner}/target').get(4, '')
        except (OSError, RuntimeError):
            continue
        targets[tuner] = value
    return targets


def concurrent_streams(admin, backend, network, control, transport, tuner_count, seconds=6):
    """Hold channels from two different RF frequencies open and read both."""
    muxes = admin.list_muxes(network)
    services = admin.list_services([mux['uuid'] for mux in muxes])
    channels = {channel.uuid: channel for channel in backend.get_channels()}
    frequencies = {mux['uuid']: mux.get('frequency') for mux in muxes}
    chosen = {}
    for service in services:
        frequency = frequencies.get(service.get('multiplex_uuid'))
        for item in service.get('channel') or []:
            uuid = item.get('uuid') if isinstance(item, dict) else item
            if frequency and uuid in channels:
                chosen.setdefault(frequency, channels[uuid])
    if len(chosen) < 2 or transport.tuner_count < 2:
        print('SKIP: two mapped frequencies and two tuners are required for concurrent streams', flush=True)
        return False
    selected = list(chosen.items())[:2]
    with contextlib.ExitStack() as stack:
        responses = []
        for frequency, channel in selected:
            session = stack.enter_context(requests.Session())
            session.trust_env = False
            response = stack.enter_context(session.get(backend.stream_url(channel, 'pass'),
                                                       stream=True, timeout=(5, 10)))
            response.raise_for_status()
            responses.append(response)
        # Both subscriptions remain open throughout every read and lock check.
        counts = [0, 0]
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for index, response in enumerate(responses):
                payload = response.raw.read(188 * 100)
                assert len(payload) == 188 * 100 and all(payload[i] == 0x47 for i in range(0, len(payload), 188)), 'Invalid concurrent MPEG-TS stream'
                counts[index] += len(payload)
            time.sleep(.05)
        locked_frequencies = set()
        for tuner in range(tuner_count):
            status = control.get(f'/tuner{tuner}/status').get(4, '')
            target = control.get(f'/tuner{tuner}/target').get(4, '')
            fields = dict(part.split('=', 1) for part in status.split() if '=' in part)
            if fields.get('lock') in (None, 'none'):
                continue
            channel = fields.get('ch', '')
            if ':' in channel:
                frequency = int(channel.rsplit(':', 1)[1])
                if frequency in chosen:
                    assert target == f'udp://{transport.local_ip}:{transport.base_port+tuner}', 'Unexpected concurrent tuner target'
                    locked_frequencies.add(frequency)
        assert {frequency for frequency, channel in selected}.issubset(locked_frequencies), 'Both frequencies were not locked simultaneously'
        print(f'PASS: concurrent streams from {[f for f,c in selected]} Hz; bytes={counts}', flush=True)
    return True


def auto_default_muxes():
    """Frequencies from Tvheadend's ``--Generic--: auto-Default`` DVB-T table."""
    muxes = []
    for frequency in range(177_500_000, 226_500_000 + 1, 7_000_000):
        muxes.append({'enabled': True, 'delsys': 'DVBT', 'frequency': frequency,
                      'bandwidth': '7MHz', 'scan_state': 1})
    for frequency in range(474_000_000, 858_000_000 + 1, 8_000_000):
        muxes.append({'enabled': True, 'delsys': 'DVBT', 'frequency': frequency,
                      'bandwidth': '8MHz', 'scan_state': 1})
    return muxes


def ensure_scan_muxes(admin, network, region):
    """Make sure the network has muxes to scan.

    This backend image loads dtv-scan-tables, but ``api/dvb/scanfile/list`` returns
    HTTP 400 and setting ``scanfile`` does not create muxes. For the generic
    auto-Default table, create the same frequency grid via ``mux_create``.
    """
    try:
        progress = wait_for(lambda: scan_progress(admin, network).muxes or None,
                            timeout=5, what='scanfile muxes')
        if progress:
            return 'scanfile'
    except AssertionError:
        pass
    if region.endswith('auto-Default') or region.endswith('auto/dvb-t_auto-Default'):
        created = 0
        for conf in auto_default_muxes():
            admin.create_mux(network, conf)
            created += 1
        admin.scan_network(network)
        print(f'NOTE: scanfile did not populate muxes; created {created} auto-Default '
              f'frequencies via mux_create', flush=True)
        wait_for(lambda: scan_progress(admin, network).muxes or None,
                 timeout=30, what='manually created muxes')
        return 'mux_create'
    raise AssertionError(
        f'scanfile {region!r} created no muxes; only auto-Default can be synthesized here')


def exercise(supervisor, options):
    server = ServerConfig('HDHomeRun acceptance', f'http://127.0.0.1:{supervisor.http_port}',
                          supervisor.username, supervisor.password, 'htsp',
                          supervisor.htsp_port, True)
    transport = supervisor.hdhomerun_transport
    assert transport is not None, 'the supervisor did not choose an HDHomeRun transport'
    configured = read_hdhomerun_transport(supervisor.http_port, supervisor.username, supervisor.password)
    assert configured == (transport.local_ip, transport.base_port), configured
    print(f'PASS: server advertises local_ip={transport.local_ip} '
          f'local_port={transport.base_port} (tuners {transport.ports})', flush=True)

    devices = discover_host_devices(timeout=3)
    assert devices, 'Windows HDHomeRun discovery found no device'
    device = next((item for item in devices if item.ip == options.device), None) if options.device else devices[0]
    assert device is not None, f'{options.device} did not answer discovery'
    print(f'PASS: Windows discovery found HDHomeRun {device.ip} with {device.tuner_count} tuners '
          f'(reached through {device.local_ip})', flush=True)
    assert device.local_ip == transport.local_ip, (
        f'device reachable through {device.local_ip}, transport publishes on {transport.local_ip}')

    admin = TvhAdmin(server)
    control = HdHomeRunControl(device.ip)
    try:
        for tuner in range(device.tuner_count or 1):
            owner = control.get(f'/tuner{tuner}/lockkey').get(4, '')
            if owner != 'none':
                raise AssertionError(f'HDHomeRun tuner {tuner} is already locked; stop other recordings or tests before running acceptance')
        admin.request('api/config/save', data={'node': json.dumps({'hdhomerun_ip': device.ip})})
        tuners = wait_for(lambda: read_tuners(admin), timeout=30, what='the server to find HDHomeRun tuners')
        kinds = [tuner.kind for tuner in tuners]
        assert len(tuners) >= 1, 'no frontends were created'
        print(f'PASS: Tvheadend recognized {len(tuners)} frontend(s): {", ".join(kinds)}', flush=True)

        region = options.region
        if not options.frequency and not region:
            regions = scan_regions(admin, options.kind, canonical=True)
            region = next((key for key, label in regions if label.endswith('auto-Default')), '')
            assert region, 'No generic auto-Default table found; supply a key returned by the server with --region'
        network = create_tuner_network(admin, options.kind, '' if options.frequency else region,
                                       f'Acceptance {options.kind}', tuners)
        if options.frequency:
            for frequency in options.frequency:
                admin.create_mux(network, {'frequency': frequency, 'delsys': options.kind, 'bandwidth': '8MHz'})
            admin.scan_network(network)
            source = 'explicit test frequencies'
        else:
            source = ensure_scan_muxes(admin, network, region)
        print(f'PASS: created network and started scan of {region or options.frequency} via {source}', flush=True)

        targets = set()
        locked = set()
        deadline = time.monotonic() + options.timeout
        progress = None
        while time.monotonic() < deadline:
            progress = scan_progress(admin, network)
            for tuner, target in transport_targets(control, tuners, transport).items():
                if target.startswith('udp://'):
                    targets.add((tuner, target))
            for tuner in range(len(tuners)):
                try:
                    status = control.get(f'/tuner{tuner}/status').get(4, '')
                except (OSError, RuntimeError):
                    continue
                if 'lock=' in status and 'lock=none' not in status:
                    locked.add(tuner)
            if progress.services and progress.working and progress.done:
                break
            time.sleep(1)
        assert progress is not None
        print(f'PASS: scan progress muxes={progress.muxes} scanned={progress.scanned} '
              f'working={progress.working} services={progress.services}', flush=True)
        assert progress.working > 0, 'no frequency locked; check the aerial and region'
        assert progress.services > 0, 'no services were discovered (scan no data)'
        assert locked, 'the HDHomeRun never reported an RF lock'
        print(f'PASS: HDHomeRun reported RF lock on tuner(s) {sorted(locked)}', flush=True)

        expected = {f'udp://{transport.local_ip}:{port}' for port in transport.ports}
        observed = {target for _tuner, target in targets}
        assert observed & expected, (
            f'HDHomeRun targets {sorted(observed)} did not include the published range {sorted(expected)}')
        print(f'PASS: HDHomeRun was told to stream to {sorted(observed & expected)}', flush=True)

        services = services_to_map(admin, network)
        assert services, 'services were found but none could be mapped'
        map_services(admin, services)
        wait_for(lambda: admin.list_channels(), timeout=60, what='channels to be mapped')
        channels = admin.list_channels()
        print(f'PASS: mapped {len(services)} service(s) into {len(channels)} channel(s)', flush=True)

        backend = HttpBackend(server)
        try:
            channel = next((row for row in backend.get_channels() if row.name), None)
            assert channel is not None, 'the server returned no playable channel'
            with requests.Session() as session:
                session.trust_env = False
                with session.get(backend.stream_url(channel, 'pass'), stream=True, timeout=30) as response:
                    response.raise_for_status()
                    data = response.raw.read(188 * 200)
            assert len(data) == 188 * 200, f'short MPEG-TS read: {len(data)}'
            assert all(data[i] == 0x47 for i in range(0, len(data), 188)), 'not MPEG-TS packets'
            print(f'PASS: played channel "{channel.name}" ({len(data)} bytes of MPEG-TS)', flush=True)
            concurrent = concurrent_streams(admin, backend, network, control, transport, len(tuners))
        finally:
            backend.close()

        return {'tuners': len(tuners), 'services': progress.services,
                'channels': len(channels), 'targets': sorted(observed & expected), 'concurrent': concurrent}
    finally:
        admin.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'windows/backend/dist')
    parser.add_argument('--device', help='HDHomeRun IPv4 address (default: first discovered)')
    parser.add_argument('--kind', default='DVB-T', choices=['DVB-T', 'DVB-C', 'DVB-S'])
    parser.add_argument('--region', default=None,
                        help='Exact scanfile key returned by the server (default: look up generic auto-Default)')
    parser.add_argument('--timeout', type=int, default=600,
                        help='Seconds to wait for the scan (auto-Default needs several minutes)')
    parser.add_argument('--frequency', type=int, action='append', default=[],
                        help='Known working DVB-T frequency in Hz; repeat for a two-tuner test')
    options = parser.parse_args()
    if options.frequency and options.kind != 'DVB-T':
        parser.error('--frequency is currently supported for DVB-T/T2 tests only')
    if any(frequency <= 0 for frequency in options.frequency):
        parser.error('--frequency must be positive')
    folder = ROOT / 'windows/build' / ('hdhomerun-test-' + uuid.uuid4().hex)
    app = QCoreApplication([])
    supervisor = WslcBuiltinSupervisor(folder / 'config', options.bundle)
    if options.device:
        device = str(ipaddress.IPv4Address(options.device))
        supervisor.config_dir.mkdir(parents=True)
        (supervisor.config_dir / 'config').write_text(json.dumps({'hdhomerun_ip': device}), encoding='utf-8')
    supervisor.recordings_dir = str(folder / 'recordings')
    supervisor.padding = (0, 0)
    state = {'error': '', 'result': None, 'diagnostics': '', 'owner': None}

    def ready(*_ports):
        state['owner'] = json.loads((supervisor.config_dir / 'wslc-owner.json').read_text())
        def worker():
            try:
                state['result'] = exercise(supervisor, options)
            except Exception as exc:
                print(sanitize(traceback.format_exc()), file=sys.stderr)
                state['error'] = sanitize(str(exc)) or type(exc).__name__
                try:
                    owner = json.loads((supervisor.config_dir / 'wslc-owner.json').read_text())
                    state['diagnostics'] = sanitize(supervisor.runtime.logs_owned(owner['name'], owner['owner']))
                except Exception:
                    pass
            finally:
                supervisor.stop()
        threading.Thread(target=worker, daemon=True).start()

    def completed(error):
        state['error'] = state['error'] or error
        app.quit()

    def timeout():
        state['error'] = 'acceptance test timed out'
        app.quit()

    supervisor.ready.connect(ready)
    supervisor._completed.connect(completed)
    QTimer.singleShot(options.timeout * 1000 + 120000, timeout)
    supervisor.start()
    try:
        app.exec()
    finally:
        supervisor.shut_down()
        app.processEvents()
    if state['result'] and not state['error']:
        try:
            owner = state['owner']
            assert supervisor.runtime.inspect_owned(owner['name'], owner['owner'], missing_ok=True,
                                                     cancellable=False) is None
            transport = supervisor.hdhomerun_transport
            wait_for(lambda: _udp_ports_free(transport.base_port, transport.tuner_count, transport.local_ip),
                     timeout=5, what='the HDHomeRun UDP publications to be released')
            print('PASS: owned container removed and UDP publications released', flush=True)
        except Exception as exc:
            state['error'] = str(exc) or type(exc).__name__
    if state['error']:
        (folder / 'backend.log').write_text(state['diagnostics'] or supervisor.log_text(), encoding='utf-8')
        print(state['error'], file=sys.stderr)
    print('Test artifacts:', folder)
    return 0 if state['result'] and not state['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

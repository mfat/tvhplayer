"""Host HDHomeRun discovery and Windows-to-container stream transport. No Qt imports.

Wire format reference: Silicondust libhdhomerun/hdhomerun_pkt.h. This module
only discovers devices and chooses the Windows-side UDP endpoint; it never
tunes a frontend.

The WSLc container gets its own NAT address, so Tvheadend's automatic
``udp://<container>:<port>`` target is unreachable from an HDHomeRun on the
LAN. Tvheadend's ``local_ip``/``local_port`` settings let the app advertise a
LAN-reachable address and a deterministic per-frontend port range instead:
tuner ``n`` listens on ``local_port + n``. WSLc publishes that same UDP range
from one Windows LAN address into the container. Direct UDP publication was
verified against WSLc 3.0.3; host networking is not supported there.
"""
from __future__ import annotations

import ipaddress
import json
import random
import re
import select
import socket
import struct
import time
import zlib
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional

from .tuners import read_tuners

DISCOVERY_PORT = 65001
# Discovery reply tags (libhdhomerun hdhomerun_pkt.h).
TAG_DEVICE_TYPE = 1
TAG_DEVICE_ID = 2
TAG_TUNER_COUNT = 0x10

# Without a configured device, reserve the supported eight-tuner range so a
# device plugged into this interface later does not exceed the published range.
DEFAULT_TUNER_COUNT = 8
MAX_TUNER_COUNT = 8
# Private, unprivileged range. Kept away from Tvheadend's web/HTSP ports and
# from the ephemeral range's busiest area.
UDP_PORT_LOW = 30000
UDP_PORT_HIGH = 60000


@dataclass(frozen=True)
class HostTuner:
    """One HDHomeRun found from Windows, and the interface that reached it."""

    ip: str
    local_ip: str = ''
    tuner_count: int = 0
    device_id: int = 0


@dataclass(frozen=True)
class HdHomeRunTransport:
    """The Windows-side UDP endpoint range published into the container."""

    local_ip: str
    base_port: int
    tuner_count: int
    device_ip: str = ''

    @property
    def ports(self) -> tuple[int, ...]:
        return tuple(range(self.base_port, self.base_port + self.tuner_count))

    def publish_specs(self) -> tuple[str, ...]:
        """``--publish`` values: host address and port equal the guest port.

        WSLc forwards the datagram to the same UDP port inside the container,
        where Tvheadend binds ``local_port + tuner_number``.
        """
        return tuple(f'{self.local_ip}:{port}:{port}/udp' for port in self.ports)

    def config(self) -> dict:
        return {'local_ip': self.local_ip, 'local_port': self.base_port}

    def with_base_port(self, base_port: int) -> 'HdHomeRunTransport':
        return replace(self, base_port=int(base_port))

    def describe(self) -> str:
        first, last = self.ports[0], self.ports[-1]
        ports = str(first) if first == last else f'{first}-{last}'
        source = f'HDHomeRun {self.device_ip}' if self.device_ip else 'no HDHomeRun found'
        return (f'{source}; publishing MPEG-TS UDP {self.local_ip}:{ports} '
                f'for {self.tuner_count} tuner(s)')


def discovery_request() -> bytes:
    payload = b'\x01\x04' + struct.pack('>I', 1) + b'\x02\x04' + b'\xff' * 4
    packet = struct.pack('>HH', 2, len(payload)) + payload
    return packet + struct.pack('<I', zlib.crc32(packet))


def _reply_tags(packet: bytes) -> Optional[dict]:
    if len(packet) < 8:
        return None
    kind, length = struct.unpack('>HH', packet[:4])
    if kind != 3 or length + 8 != len(packet):
        return None
    if struct.unpack('<I', packet[-4:])[0] != zlib.crc32(packet[:-4]):
        return None
    payload = packet[4:-4]
    tags = {}
    pos = 0
    while pos < len(payload):
        if len(payload) - pos < 2:
            return None
        tag, size = payload[pos:pos + 2]
        pos += 2
        if size & 0x80:
            if pos >= len(payload):
                return None
            size = (size & 0x7f) | (payload[pos] << 7)
            pos += 1
        if pos + size > len(payload):
            return None
        tags[tag] = payload[pos:pos + size]
        pos += size
    if tags.get(TAG_DEVICE_TYPE) != struct.pack('>I', 1) or len(tags.get(TAG_DEVICE_ID, b'')) != 4:
        return None
    return tags


def is_tuner_reply(packet: bytes) -> bool:
    return _reply_tags(packet) is not None


def parse_tuner_reply(packet: bytes, source_ip: str, local_ip: str = '') -> Optional[HostTuner]:
    """A ``HostTuner`` for a valid discovery reply, or None."""
    tags = _reply_tags(packet)
    if tags is None:
        return None
    try:
        address = str(ipaddress.IPv4Address(source_ip))
    except ValueError:
        return None
    count = 0
    raw_count = tags.get(TAG_TUNER_COUNT, b'')
    if raw_count:
        # Firmware has used one byte and four bytes for this tag.
        count = int.from_bytes(raw_count, 'big')
    # Reject nonsense counts (some replies leave the tag unset or garbage).
    if count < 1 or count > MAX_TUNER_COUNT:
        count = 0
    return HostTuner(
        ip=address,
        local_ip=local_ip,
        tuner_count=count,
        device_id=int.from_bytes(tags[TAG_DEVICE_ID], 'big'),
    )


def host_interfaces():
    """Bind discovery on each usable IPv4 interface, including multi-NIC hosts."""
    import psutil
    interfaces = []
    for rows in psutil.net_if_addrs().values():
        for row in rows:
            if row.family != socket.AF_INET or not row.netmask:
                continue
            try:
                interface = ipaddress.IPv4Interface(f'{row.address}/{row.netmask}')
            except ValueError:
                continue
            if interface.ip.is_loopback or interface.ip.is_link_local or interface.network.prefixlen >= 31:
                continue
            interfaces.append((str(interface.ip), str(interface.network.broadcast_address)))
    return sorted(set(interfaces))


def _usable_ipv4(address: str) -> bool:
    try:
        parsed = ipaddress.IPv4Address(address)
    except ValueError:
        return False
    return not (parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified
                or parsed.is_multicast or parsed.is_reserved)


def discover_host_devices(timeout=2.0, cancel=None, interfaces=None) -> List[HostTuner]:
    """HDHomeRuns answering a bounded Windows-side UDP discovery.

    The returned ``local_ip`` is the interface the device replied through, so
    the caller can advertise an address the device can reach.
    """
    sockets = []
    found = {}
    local_ips = {}
    try:
        for local, broadcast in (interfaces if interfaces is not None else host_interfaces()):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((local, 0))
                sock.sendto(discovery_request(), (broadcast, DISCOVERY_PORT))
                sockets.append(sock)
                local_ips[sock] = local
            except OSError:
                sock.close()
        deadline = time.monotonic() + timeout
        while sockets and time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                break
            ready, _, _ = select.select(sockets, [], [], min(.2, max(0, deadline - time.monotonic())))
            for sock in ready:
                try:
                    packet, source = sock.recvfrom(2048)
                except OSError:
                    continue
                if source[1] != DISCOVERY_PORT:
                    continue
                device = parse_tuner_reply(packet, source[0], local_ips.get(sock, ''))
                if device is not None and device.ip not in found:
                    found[device.ip] = device
    finally:
        for sock in sockets:
            sock.close()
    return [found[ip] for ip in sorted(found)]


def discover_host_tuners(timeout=2.0, cancel=None) -> List[str]:
    """IPv4 addresses of devices answering a bounded Windows-side UDP discovery."""
    return [device.ip for device in discover_host_devices(timeout=timeout, cancel=cancel)]


def probe_host_device(address, timeout=.25, cancel=None):
    """Unicast discovery of the configured device, without a broadcast wait."""
    if not _usable_ipv4(address):
        raise ValueError('Configure one valid HDHomeRun IPv4 address.')
    local_ip = local_address_for(address)
    if not local_ip:
        return None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((local_ip, 0))
        sock.connect((address, DISCOVERY_PORT))
        sock.send(discovery_request())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                return None
            ready, _, _ = select.select([sock], [], [], min(.05, max(0, deadline-time.monotonic())))
            if ready:
                try:
                    packet = sock.recv(2048)
                except OSError:
                    break
                device = parse_tuner_reply(packet, address, local_ip)
                if device is not None:
                    return device
    # An offline device must not force a different device or an arbitrary NIC.
    return HostTuner(address, local_ip, MAX_TUNER_COUNT)


def local_address_for(device_ip: str, port: int = DISCOVERY_PORT) -> str:
    """The local IPv4 address Windows uses to reach ``device_ip``, or ''."""
    try:
        ipaddress.IPv4Address(device_ip)
    except ValueError:
        return ''
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((device_ip, int(port)))
            address = sock.getsockname()[0]
    except OSError:
        return ''
    return address if _usable_ipv4(address) else ''


def default_lan_address() -> str:
    """The IPv4 address on Windows' default route, or ''.

    Used when no HDHomeRun answered discovery. A UDP ``connect`` does not send
    a packet; it only asks Windows which source address the route would use.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 9))
            address = sock.getsockname()[0]
        if _usable_ipv4(address):
            return address
    except OSError:
        pass
    for address, _broadcast in host_interfaces():
        if _usable_ipv4(address):
            return address
    return ''


def _udp_ports_free(base_port: int, count: int, local_ip: str) -> bool:
    sockets = []
    try:
        for offset in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind((local_ip or '0.0.0.0', base_port + offset))
            except OSError:
                sock.close()
                return False
            sockets.append(sock)
    finally:
        for sock in sockets:
            sock.close()
    return True


def pick_udp_base(tuner_count: int, rng=None, avoid: Iterable[int] = (), local_ip: str = '',
                  probe=None) -> int:
    """Choose a free UDP base port for ``tuner_count`` consecutive tuner ports."""
    count = max(1, min(int(tuner_count), MAX_TUNER_COUNT))
    rng = rng or random
    blocked = set(int(port) for port in avoid)
    check = probe or (lambda base, ports, address: _udp_ports_free(base, ports, address))
    for _ in range(200):
        base = rng.randint(UDP_PORT_LOW, UDP_PORT_HIGH - count + 1)
        if any(base + offset in blocked for offset in range(count)):
            continue
        if check(base, count, local_ip):
            return base
    raise RuntimeError('could not choose HDHomeRun UDP stream ports')


def plan_transport(devices: Optional[Iterable[HostTuner]] = None, *,
                   timeout: float = 2.0, cancel=None,
                   default_tuner_count: int = DEFAULT_TUNER_COUNT,
                   rng=None, avoid: Iterable[int] = (), port_picker=pick_udp_base, device_ip='',
                   ) -> Optional[HdHomeRunTransport]:
    """Choose the Windows address and UDP range to advertise to HDHomeRun.

    Only a selected or unambiguous device is used; otherwise the default LAN
    address is used so a tuner added after startup still has a route. Returns
    None when the host has no usable LAN address (for example, offline).
    """
    found = list(devices) if devices is not None else discover_host_devices(timeout=timeout, cancel=cancel)
    found = [device for device in found if device.local_ip and _usable_ipv4(device.local_ip)]
    if device_ip:
        found = [device for device in found if device.ip == device_ip]
        if not found:
            return None
    elif len(found) > 1:
        raise ValueError('Multiple HDHomeRuns found; select one device before configuring streams.')
    if found:
        device = found[0]
        local_ip = device.local_ip
        count = device.tuner_count or int(default_tuner_count)
    else:
        device = None
        local_ip = default_lan_address()
        count = int(default_tuner_count)
    if not _usable_ipv4(local_ip):
        return None
    count = max(1, min(int(count), MAX_TUNER_COUNT))
    base = port_picker(count, rng=rng, avoid=avoid, local_ip=local_ip)
    return HdHomeRunTransport(local_ip=local_ip, base_port=int(base),
                              tuner_count=count, device_ip=device.ip if device else '')


def configured_local_ip(admin) -> Optional[str]:
    """Tvheadend's current ``local_ip``, or None when it cannot be read.

    ``None`` means "unknown" (old server, fake admin); ``''`` means the server
    is configured to pick its own container address, which cannot work behind
    WSLc NAT.
    """
    try:
        data = admin.request('api/config/load')
        entries = data.get('entries') if isinstance(data, dict) else None
        params = {param.get('id'): param.get('value')
                  for param in (entries[0].get('params') or [])} if entries else {}
    except Exception:
        return None
    value = params.get('local_ip')
    return value if isinstance(value, str) else None


def validate_stream_route(admin, address):
    """Validate existing frontends as well as newly discovered ones."""
    local_ip = configured_local_ip(admin)
    if local_ip is None:
        raise ValueError('Cannot verify the built-in server HDHomeRun stream address. '
                         'Restart the built-in server and check its setup log.')
    if not local_ip:
        raise ValueError('The built-in server did not publish an HDHomeRun stream address. '
                         'Restart the built-in server with the HDHomeRun connected.')
    routed = local_address_for(address)
    if not routed or routed != local_ip:
        raise ValueError(
            f'The HDHomeRun ({address}) is reached through {routed or "no usable LAN interface"}, '
            f'but the built-in server publishes streams on {local_ip}. '
            'Restart the built-in server after connecting the HDHomeRun to that network.')


def _validate_existing_tuners(admin, tuners):
    addresses = set()
    for tuner in tuners:
        hardware = getattr(tuner, 'hardware', '')
        name = getattr(tuner, 'name', '')
        if 'hdhomerun' not in (hardware + name).lower():
            continue
        for candidate in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', hardware + ' ' + name):
            if _usable_ipv4(candidate):
                addresses.add(candidate)
    for address in sorted(addresses):
        validate_stream_route(admin, address)


def read_windows_builtin_tuners(admin, discover=discover_host_tuners, wait=time.sleep):
    """Use host discovery when container broadcasts find nothing.

    Tvheadend supports one directed HDHomeRun address. Only select automatically
    when the host finds exactly one device; don't choose arbitrarily among several.
    """
    tuners = read_tuners(admin)
    if tuners:
        _validate_existing_tuners(admin, tuners)
        return tuners
    devices = discover()
    if len(devices) != 1:
        return tuners
    address = str(ipaddress.IPv4Address(devices[0]))
    # Persist the selected device even if its route requires a container restart.
    # The next launch must plan for this device, not the default interface.
    admin.request('api/config/save', data={'node': json.dumps({'hdhomerun_ip': address})})
    # A configured local IP is the Windows address the built-in server publishes
    # UDP streams from. If the device is reached through another interface, the
    # published range is on the wrong network and scanning would fail silently.
    validate_stream_route(admin, address)
    # The server's HDHomeRun discovery loop runs every 15 seconds.
    for _ in range(20):
        wait(1)
        tuners = read_tuners(admin)
        if tuners:
            _validate_existing_tuners(admin, tuners)
            return tuners
    return tuners

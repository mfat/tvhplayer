"""Host HDHomeRun discovery for a backend behind container NAT. No Qt imports.

Wire format reference: Silicondust libhdhomerun/hdhomerun_pkt.h.
Only discovery datagrams are sent; this does not tune or lock a frontend.
"""
from __future__ import annotations

import ipaddress
import json
import select
import socket
import struct
import time
import zlib

from .tuners import read_tuners

DISCOVERY_PORT = 65001


def discovery_request() -> bytes:
    payload = b'\x01\x04' + struct.pack('>I', 1) + b'\x02\x04' + b'\xff' * 4
    packet = struct.pack('>HH', 2, len(payload)) + payload
    return packet + struct.pack('<I', zlib.crc32(packet))


def is_tuner_reply(packet: bytes) -> bool:
    if len(packet) < 8:
        return False
    kind, length = struct.unpack('>HH', packet[:4])
    if kind != 3 or length + 8 != len(packet):
        return False
    if struct.unpack('<I', packet[-4:])[0] != zlib.crc32(packet[:-4]):
        return False
    payload = packet[4:-4]
    tags = {}
    pos = 0
    while pos < len(payload):
        if len(payload) - pos < 2:
            return False
        tag, size = payload[pos:pos + 2]
        pos += 2
        if size & 0x80:
            if pos >= len(payload):
                return False
            size = (size & 0x7f) | (payload[pos] << 7)
            pos += 1
        if pos + size > len(payload):
            return False
        tags[tag] = payload[pos:pos + size]
        pos += size
    return tags.get(1) == struct.pack('>I', 1) and len(tags.get(2, b'')) == 4


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


def discover_host_tuners(timeout=2.0):
    """IPv4 addresses of devices answering a bounded Windows-side UDP discovery."""
    sockets = []
    found = set()
    try:
        for local, broadcast in host_interfaces():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((local, 0))
                sock.sendto(discovery_request(), (broadcast, DISCOVERY_PORT))
                sockets.append(sock)
            except OSError:
                sock.close()
        deadline = time.monotonic() + timeout
        while sockets and time.monotonic() < deadline:
            ready, _, _ = select.select(sockets, [], [], max(0, deadline - time.monotonic()))
            for sock in ready:
                try:
                    packet, source = sock.recvfrom(2048)
                except OSError:
                    continue
                if source[1] == DISCOVERY_PORT and is_tuner_reply(packet):
                    found.add(str(ipaddress.IPv4Address(source[0])))
    finally:
        for sock in sockets:
            sock.close()
    return sorted(found)


def read_windows_builtin_tuners(admin, discover=discover_host_tuners, wait=time.sleep):
    """Use host discovery when container broadcasts find nothing.

    Tvheadend supports one directed HDHomeRun address. Only select automatically
    when the host finds exactly one device; don't choose arbitrarily among several.
    """
    tuners = read_tuners(admin)
    if tuners:
        return tuners
    devices = discover()
    if len(devices) != 1:
        return tuners
    address = str(ipaddress.IPv4Address(devices[0]))
    admin.request('api/config/save', data={'node': json.dumps({'hdhomerun_ip': address})})
    # The server's HDHomeRun discovery loop runs every 15 seconds.
    for _ in range(20):
        wait(1)
        tuners = read_tuners(admin)
        if tuners:
            return tuners
    return tuners

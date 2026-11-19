"""DNS servers for a WSLc built-in server.

``wslc run --dns`` replaces the resolver list. Passing only the address the
user added would drop the servers the container otherwise inherits. This module
reads the IPv4 resolvers WSL copies from Windows adapters when it mirrors host
DNS (``HostDnsInfo::GetDnsSettings(IncludeVpn)``), then appends the extra
address.

That is the list observed inside WSLc when the container inherits the Windows
adapter resolvers. A NAT-gateway or DNS-tunneling resolver is a different
source and is left to the separate WSL resolver investigation. Discovery runs
on the backend thread; nothing here may be called from the Qt GUI thread.
"""
from __future__ import annotations

import ipaddress
import sys

# glibc consults MAXNS (3) nameservers. WSL stops at the same limit.
INHERITED_DNS_LIMIT = 3

IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131
IF_TYPE_PPP = 23
IF_TYPE_PROP_VIRTUAL = 53
IF_OPER_UP = 1
AF_INET = 2
AF_INET6 = 23
ERROR_BUFFER_OVERFLOW = 111
# GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_INCLUDE_GATEWAYS
GAA_FLAGS = 0x0002 | 0x0004 | 0x0080
NETWORK_CONNECTIVITY_HIDDEN = 5

DISCOVERY_FAILED = (
    'Could not read the DNS servers Windows would give the built-in server. '
    'The additional DNS server was not applied, because using it alone would replace those servers. '
    'Turn off Use additional DNS server, or check that a network adapter has DNS servers, '
    'then start the built-in server again.'
)


class DnsAddressError(ValueError):
    """The DNS address the user typed cannot be passed to WSLc."""


class DnsDiscoveryError(RuntimeError):
    """Windows DNS could not be read, so an extra server must not replace it."""


def canonical_dns_address(text):
    """Return a plain IPv4 or IPv6 address, or raise ``DnsAddressError``."""
    raw = (text or '').strip()
    if raw.startswith('[') and raw.endswith(']'):
        raw = raw[1:-1].strip()
    if not raw:
        raise DnsAddressError('Enter a DNS server address.')
    if '%' in raw or '/' in raw:
        raise DnsAddressError('Enter an IPv4 or IPv6 address, such as 1.1.1.1.')
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        raise DnsAddressError('Enter an IPv4 or IPv6 address, such as 1.1.1.1.') from None
    if address.is_unspecified or address.is_multicast:
        raise DnsAddressError('Enter the address of a DNS server.')
    if isinstance(address, ipaddress.IPv6Address):
        return address.compressed
    return str(address)


def _dedupe(addresses):
    seen = set()
    result = []
    for item in addresses:
        address = ipaddress.ip_address(canonical_dns_address(item))
        if address in seen:
            continue
        seen.add(address)
        result.append(address.compressed if isinstance(address, ipaddress.IPv6Address) else str(address))
    return result


def merge_dns_servers(inherited, additional):
    """Inherited servers first, then ``additional`` if it is not already there.

    An empty inherited list is a discovery failure. The extra address is not
    returned on its own, because that would replace Windows DNS.
    """
    extra = canonical_dns_address(additional)
    servers = _dedupe(inherited)
    if not servers:
        raise DnsDiscoveryError(DISCOVERY_FAILED)
    if any(ipaddress.ip_address(item) == ipaddress.ip_address(extra) for item in servers):
        return servers
    # Keep every inherited server. resolv.conf uses the first three; the
    # caller logs when the extra address falls past that.
    return servers + [extra]


def select_inherited_dns(adapters, best_index, *, include_ipv6=False, limit=INHERITED_DNS_LIMIT):
    """Order adapters the way WSL does, then take up to ``limit`` resolvers.

    ``adapters`` entries are dicts with ``index``, ``up``, ``loopback``,
    ``tunnel``, ``vpn``, ``hidden``, ``has_unicast``, ``dns_v4``, and ``dns_v6``.
    """
    usable = [
        adapter for adapter in adapters
        if adapter.get('up') and not adapter.get('loopback') and not adapter.get('tunnel')
        and not adapter.get('hidden') and adapter.get('has_unicast')
        and (adapter.get('dns_v4') or (include_ipv6 and adapter.get('dns_v6')))
    ]
    usable.sort(key=lambda adapter: (
        0 if adapter.get('vpn') else 1,
        0 if adapter.get('index') == best_index else 1,
        0 if adapter.get('dns_v4') else 1,
        adapter.get('index') or 0,
    ))
    servers = []
    for adapter in usable:
        room = limit - len(servers)
        if room <= 0:
            break
        take = 1 if adapter.get('vpn') and room > 1 else room
        chosen = []
        for family in ('dns_v4', 'dns_v6'):
            if family == 'dns_v6' and not include_ipv6:
                continue
            for item in adapter.get(family) or ():
                if len(chosen) >= take:
                    break
                try:
                    address = canonical_dns_address(item)
                except DnsAddressError:
                    continue
                if address not in chosen:
                    chosen.append(address)
        servers.extend(chosen)
    return _dedupe(servers)[:limit]


def discover_windows_dns():
    """IPv4 DNS servers the container inherits from Windows, in resolver order."""
    if sys.platform != 'win32':
        raise DnsDiscoveryError(DISCOVERY_FAILED)
    try:
        adapters, best = _read_windows_adapters()
    except OSError as exc:
        raise DnsDiscoveryError(f'{DISCOVERY_FAILED} ({exc})') from exc
    servers = select_inherited_dns(adapters, best)
    if not servers:
        raise DnsDiscoveryError(DISCOVERY_FAILED)
    return servers


def _read_windows_adapters():
    import ctypes
    from ctypes import wintypes

    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError('DNS discovery needs 64-bit Python')

    class sockaddr_in(ctypes.Structure):
        _fields_ = [
            ('sin_family', wintypes.USHORT),
            ('sin_port', wintypes.USHORT),
            ('sin_addr', ctypes.c_ubyte * 4),
            ('sin_zero', ctypes.c_ubyte * 8),
        ]

    class sockaddr_in6(ctypes.Structure):
        _fields_ = [
            ('sin6_family', wintypes.USHORT),
            ('sin6_port', wintypes.USHORT),
            ('sin6_flowinfo', wintypes.ULONG),
            ('sin6_addr', ctypes.c_ubyte * 16),
            ('sin6_scope_id', wintypes.ULONG),
        ]

    class socket_address(ctypes.Structure):
        _fields_ = [('lpSockaddr', ctypes.c_void_p), ('iSockaddrLength', ctypes.c_int)]

    class dns_server(ctypes.Structure):
        _fields_ = [
            ('Length', wintypes.ULONG),
            ('Reserved', wintypes.DWORD),
            ('Next', ctypes.c_void_p),
            ('Address', socket_address),
        ]

    class adapter(ctypes.Structure):
        _fields_ = [
            ('Length', wintypes.ULONG),
            ('IfIndex', wintypes.DWORD),
            ('Next', ctypes.c_void_p),
            ('AdapterName', ctypes.c_void_p),
            ('FirstUnicastAddress', ctypes.c_void_p),
            ('FirstAnycastAddress', ctypes.c_void_p),
            ('FirstMulticastAddress', ctypes.c_void_p),
            ('FirstDnsServerAddress', ctypes.c_void_p),
            ('DnsSuffix', ctypes.c_void_p),
            ('Description', ctypes.c_void_p),
            ('FriendlyName', ctypes.c_void_p),
            ('PhysicalAddress', ctypes.c_ubyte * 8),
            ('PhysicalAddressLength', wintypes.DWORD),
            ('Flags', wintypes.DWORD),
            ('Mtu', wintypes.DWORD),
            ('IfType', wintypes.DWORD),
            ('OperStatus', ctypes.c_int),
        ]

    class connectivity_hint(ctypes.Structure):
        _fields_ = [
            ('ConnectivityLevel', ctypes.c_int),
            ('ConnectivityCost', ctypes.c_int),
            ('ApproachingDataLimit', wintypes.BOOLEAN),
            ('OverDataLimit', wintypes.BOOLEAN),
            ('Roaming', wintypes.BOOLEAN),
        ]

    iphlpapi = ctypes.WinDLL('iphlpapi', use_last_error=True)
    get_adapters = ctypes.WINFUNCTYPE(
        wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG),
    )(('GetAdaptersAddresses', iphlpapi))
    get_best = ctypes.WINFUNCTYPE(
        wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
    )(('GetBestInterfaceEx', iphlpapi))
    hidden_query = getattr(iphlpapi, 'GetNetworkConnectivityHintForInterface', None)
    if hidden_query is not None:
        hidden_query.argtypes = [wintypes.DWORD, ctypes.POINTER(connectivity_hint)]
        hidden_query.restype = wintypes.DWORD

    def hidden(index):
        # Missing on older Windows: do not hide every adapter. A failed call
        # means WSL itself ignores that adapter.
        if hidden_query is None:
            return False
        hint = connectivity_hint()
        if hidden_query(wintypes.DWORD(index), ctypes.byref(hint)) != 0:
            return True
        return hint.ConnectivityLevel == NETWORK_CONNECTIVITY_HIDDEN

    def families(first):
        v4, v6 = [], []
        ptr = first
        seen = set()
        for _ in range(32):
            if not ptr or ptr in seen:
                break
            seen.add(ptr)
            row = ctypes.cast(ptr, ctypes.POINTER(dns_server)).contents
            sockaddr = row.Address.lpSockaddr
            if sockaddr:
                family = ctypes.cast(sockaddr, ctypes.POINTER(wintypes.USHORT)).contents.value
                if family == AF_INET:
                    raw = ctypes.cast(sockaddr, ctypes.POINTER(sockaddr_in)).contents.sin_addr
                    v4.append(str(ipaddress.IPv4Address(bytes(raw))))
                elif family == AF_INET6:
                    raw = ctypes.cast(sockaddr, ctypes.POINTER(sockaddr_in6)).contents.sin6_addr
                    v6.append(ipaddress.IPv6Address(bytes(raw)).compressed)
            ptr = row.Next
        return v4, v6

    size = 16 * 1024
    buf = None
    for _ in range(4):
        buf = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG(size)
        status = get_adapters(0, GAA_FLAGS, None, buf, ctypes.byref(needed))
        if status == 0:
            break
        if status != ERROR_BUFFER_OVERFLOW:
            raise OSError(f'GetAdaptersAddresses failed ({status})')
        size = max(int(needed.value), size * 2)
    else:
        raise OSError('GetAdaptersAddresses buffer kept growing')

    adapters = []
    ptr = ctypes.addressof(buf)
    seen = set()
    for _ in range(256):
        if not ptr or ptr in seen:
            break
        seen.add(ptr)
        row = ctypes.cast(ptr, ctypes.POINTER(adapter)).contents
        v4, v6 = families(row.FirstDnsServerAddress)
        adapters.append({
            'index': int(row.IfIndex),
            'up': int(row.OperStatus) == IF_OPER_UP,
            'loopback': int(row.IfType) == IF_TYPE_SOFTWARE_LOOPBACK,
            'tunnel': int(row.IfType) == IF_TYPE_TUNNEL,
            'vpn': int(row.IfType) in (IF_TYPE_PPP, IF_TYPE_PROP_VIRTUAL),
            'hidden': hidden(int(row.IfIndex)),
            'has_unicast': bool(row.FirstUnicastAddress),
            'dns_v4': v4,
            'dns_v6': v6,
        })
        ptr = row.Next

    best = wintypes.DWORD(0)
    dest = sockaddr_in(sin_family=AF_INET)
    if get_best(ctypes.byref(dest), ctypes.byref(best)) != 0:
        dest6 = sockaddr_in6(sin6_family=AF_INET6)
        if get_best(ctypes.byref(dest6), ctypes.byref(best)) != 0:
            best = wintypes.DWORD(0)
    # The address buffer has to stay alive until every pointer above is copied.
    del buf
    return adapters, int(best.value)

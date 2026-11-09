import json
import socket
import struct
import threading
import types
import zlib

import pytest

from tvhplayer.core import hdhomerun


def reply(payload=None):
    payload = payload if payload is not None else bytes.fromhex('01040000000102041240c1f5')
    frame = struct.pack('>HH', 3, len(payload)) + payload
    return frame + struct.pack('<I', zlib.crc32(frame))


def test_invalid_discovery_packets_are_ignored():
    valid = reply()
    assert hdhomerun.is_tuner_reply(valid)
    assert not hdhomerun.is_tuner_reply(b'')
    assert not hdhomerun.is_tuner_reply(valid[:-1])
    assert not hdhomerun.is_tuner_reply(valid[:-1] + bytes([valid[-1] ^ 1]))
    assert not hdhomerun.is_tuner_reply(reply(bytes.fromhex('01040000000502041240c1f5')))
    assert not hdhomerun.is_tuner_reply(reply(b'\x01\x80'))
    assert not hdhomerun.is_tuner_reply(reply(b'\x01\x04\x00'))
    assert not hdhomerun.is_tuner_reply(hdhomerun.discovery_request())


def test_unknown_tags_with_two_byte_lengths_do_not_hide_a_tuner():
    payload = bytes.fromhex('01040000000102041240c1f5') + b'\x7f\x80\x01' + b'x' * 128
    assert hdhomerun.is_tuner_reply(reply(payload))


def test_udp_discovery_receives_and_validates_a_device(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as device:
        device.bind(('127.0.0.1', 0))
        device.settimeout(3)
        monkeypatch.setattr(hdhomerun, 'DISCOVERY_PORT', device.getsockname()[1])
        monkeypatch.setattr(hdhomerun, 'host_interfaces', lambda: [('127.0.0.1', '127.0.0.1')])
        def respond():
            packet, source = device.recvfrom(2048)
            if packet == hdhomerun.discovery_request():
                device.sendto(reply(), source)
        thread = threading.Thread(target=respond)
        thread.start()
        try:
            assert hdhomerun.discover_host_tuners(timeout=.3) == ['127.0.0.1']
        finally:
            thread.join(4)


def test_discovery_reports_the_interface_and_tuner_count(monkeypatch):
    payload = bytes.fromhex('01040000000102041240c1f5') + bytes.fromhex('100102')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as device:
        device.bind(('127.0.0.1', 0))
        device.settimeout(3)
        monkeypatch.setattr(hdhomerun, 'DISCOVERY_PORT', device.getsockname()[1])
        monkeypatch.setattr(hdhomerun, 'host_interfaces', lambda: [('127.0.0.1', '127.0.0.1')])
        def respond():
            packet, source = device.recvfrom(2048)
            if packet == hdhomerun.discovery_request():
                device.sendto(reply(payload), source)
        thread = threading.Thread(target=respond)
        thread.start()
        try:
            devices = hdhomerun.discover_host_devices(timeout=.3)
        finally:
            thread.join(4)
    assert devices == [hdhomerun.HostTuner('127.0.0.1', '127.0.0.1', 2, 0x1240C1F5)]


def test_parse_tuner_reply_rejects_invalid_source_or_packet():
    packet = reply(bytes.fromhex('01040000000102041240c1f5'))
    assert hdhomerun.parse_tuner_reply(packet, '192.168.8.148', '192.168.8.211').device_id == 0x1240C1F5
    assert hdhomerun.parse_tuner_reply(packet, 'not-an-ip') is None
    assert hdhomerun.parse_tuner_reply(b'bad', '192.168.8.148') is None


@pytest.mark.parametrize('tag,count', [('100102', 2), ('100400000002', 2)])
def test_tuner_count_accepts_the_firmware_tag_widths(tag, count):
    packet = reply(bytes.fromhex('01040000000102041240c1f5') + bytes.fromhex(tag))
    device = hdhomerun.parse_tuner_reply(packet, '192.168.8.148')
    assert device.tuner_count == count


def transport_device(count=2):
    return hdhomerun.HostTuner('192.168.8.148', '192.168.8.211', count, 0x1240C1F5)


def fixed_picker(base=30000):
    return lambda count, **kwargs: base


def test_transport_uses_the_interface_that_reached_the_device():
    transport = hdhomerun.plan_transport([transport_device()], port_picker=fixed_picker())
    assert transport.local_ip == '192.168.8.211'
    assert transport.base_port == 30000
    assert transport.tuner_count == 2
    assert transport.ports == (30000, 30001)
    assert transport.publish_specs() == ('192.168.8.211:30000:30000/udp',
                                         '192.168.8.211:30001:30001/udp')
    assert transport.config() == {'local_ip': '192.168.8.211', 'local_port': 30000}
    assert '192.168.8.148' in transport.describe()


def test_transport_requires_a_choice_among_multiple_devices():
    devices = [transport_device(), hdhomerun.HostTuner('192.168.1.9', '192.168.1.5', 4)]
    with pytest.raises(ValueError, match='select one'):
        hdhomerun.plan_transport(devices, port_picker=fixed_picker())
    selected = hdhomerun.plan_transport(devices, device_ip='192.168.1.9', port_picker=fixed_picker())
    assert (selected.device_ip, selected.local_ip, selected.tuner_count) == ('192.168.1.9', '192.168.1.5', 4)
    assert hdhomerun.plan_transport(devices, device_ip='192.168.1.99', port_picker=fixed_picker()) is None


def test_unicast_probe_returns_as_soon_as_configured_device_answers(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as device:
        device.bind(('127.0.0.1', 0))
        device.settimeout(2)
        monkeypatch.setattr(hdhomerun, 'DISCOVERY_PORT', device.getsockname()[1])
        monkeypatch.setattr(hdhomerun, '_usable_ipv4', lambda address: True)
        monkeypatch.setattr(hdhomerun, 'local_address_for', lambda address: '127.0.0.1')
        def respond():
            packet, source = device.recvfrom(2048)
            assert packet == hdhomerun.discovery_request()
            device.sendto(reply(bytes.fromhex('01040000000102041240c1f5100102')), source)
        thread = threading.Thread(target=respond)
        thread.start()
        try:
            found = hdhomerun.probe_host_device('127.0.0.1', timeout=1)
        finally:
            thread.join(3)
    assert found.ip == '127.0.0.1' and found.tuner_count == 2


@pytest.mark.parametrize('local_ip,route,raises', [('', '192.168.8.211', True),
    ('192.168.8.211', '192.168.1.5', True), ('192.168.8.211', '', True),
    ('192.168.8.211', '192.168.8.211', False)])
def test_existing_hdhomerun_frontends_still_validate_route(monkeypatch, local_ip, route, raises):
    tuner = types.SimpleNamespace(name='HDHomeRun #0 (192.168.8.148)', hardware='HDHomeRun(123)')
    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: [tuner])
    monkeypatch.setattr(hdhomerun, 'local_address_for', lambda address: route)
    monkeypatch.setattr(hdhomerun, 'configured_local_ip', lambda admin: local_ip)
    discover = lambda: pytest.fail('Existing tuners must not require broadcast discovery')
    if raises:
        with pytest.raises(ValueError, match='Restart'):
            hdhomerun.read_windows_builtin_tuners(None, discover=discover)
    else:
        assert hdhomerun.read_windows_builtin_tuners(None, discover=discover) == [tuner]


def test_transport_without_a_device_uses_the_default_lan_and_port_count(monkeypatch):
    monkeypatch.setattr(hdhomerun, 'default_lan_address', lambda: '192.168.8.211')
    transport = hdhomerun.plan_transport([], port_picker=fixed_picker())
    assert transport.local_ip == '192.168.8.211'
    assert transport.tuner_count == hdhomerun.DEFAULT_TUNER_COUNT
    assert transport.device_ip == ''


def test_transport_is_none_without_a_lan_address(monkeypatch):
    monkeypatch.setattr(hdhomerun, 'default_lan_address', lambda: '')
    assert hdhomerun.plan_transport([], port_picker=fixed_picker()) is None


@pytest.mark.parametrize('count,expected', [(0, hdhomerun.DEFAULT_TUNER_COUNT), (99, hdhomerun.MAX_TUNER_COUNT)])
def test_transport_clamps_the_tuner_count(monkeypatch, count, expected):
    monkeypatch.setattr(hdhomerun, 'default_lan_address', lambda: '192.168.8.211')
    transport = hdhomerun.plan_transport([transport_device(count)], port_picker=fixed_picker())
    assert transport.tuner_count == expected


def test_transport_ignores_a_device_without_a_usable_interface(monkeypatch):
    monkeypatch.setattr(hdhomerun, 'default_lan_address', lambda: '192.168.8.211')
    device = hdhomerun.HostTuner('192.168.8.148', '127.0.0.1', 2)
    transport = hdhomerun.plan_transport([device], port_picker=fixed_picker())
    assert transport.local_ip == '192.168.8.211'


def test_pick_udp_base_skips_avoided_and_unavailable_ports():
    class Rng:
        def __init__(self, values):
            self.values = iter(values)

        def randint(self, _low, _high):
            return next(self.values)

    seen = []
    def probe(base, _count, _local_ip):
        seen.append(base)
        return base == 30002

    base = hdhomerun.pick_udp_base(2, rng=Rng([30000, 30001, 30002]),
                                   avoid=(30000,), probe=probe)
    assert base == 30002
    assert seen == [30001, 30002]


def test_pick_udp_base_gives_up_instead_of_reusing_a_port():
    class Rng:
        def randint(self, low, high):
            return low

    with pytest.raises(RuntimeError, match='UDP stream ports'):
        hdhomerun.pick_udp_base(2, rng=Rng(), probe=lambda *args: False)


def test_configured_local_ip_distinguishes_unknown_from_empty():
    class Admin:
        def __init__(self, value):
            self.value = value

        def request(self, path):
            if self.value is None:
                return {}
            return {'entries': [{'params': [{'id': 'local_ip', 'value': self.value}]}]}

    assert hdhomerun.configured_local_ip(Admin('192.168.8.211')) == '192.168.8.211'
    assert hdhomerun.configured_local_ip(Admin('')) == ''
    assert hdhomerun.configured_local_ip(Admin(None)) is None
    assert hdhomerun.configured_local_ip(None) is None


def test_directed_discovery_explains_a_cross_interface_device(monkeypatch):
    class Admin:
        def __init__(self, local_ip):
            self.local_ip = local_ip
            self.calls = []

        def request(self, path, data=None):
            self.calls.append((path, data))
            if path == 'api/config/load':
                return {'entries': [{'params': [{'id': 'local_ip', 'value': self.local_ip}]}]}
            return {}

    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: [])
    monkeypatch.setattr(hdhomerun, 'local_address_for', lambda address: '192.168.1.5')
    with pytest.raises(ValueError, match='publishes streams on'):
        hdhomerun.read_windows_builtin_tuners(Admin('192.168.8.211'),
                                              discover=lambda: ['192.168.8.148'])
    with pytest.raises(ValueError, match='did not publish'):
        hdhomerun.read_windows_builtin_tuners(Admin(''), discover=lambda: ['192.168.8.148'])


def test_directed_discovery_accepts_a_matching_interface(monkeypatch):
    class Admin:
        def request(self, path, data=None):
            if path == 'api/config/load':
                return {'entries': [{'params': [{'id': 'local_ip', 'value': '192.168.8.211'}]}]}
            return {}

    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: [])
    monkeypatch.setattr(hdhomerun, 'local_address_for', lambda address: '192.168.8.211')
    assert hdhomerun.read_windows_builtin_tuners(Admin(), discover=lambda: ['192.168.8.148'],
                                                 wait=lambda _: None) == []


def test_directed_discovery_rejects_an_unverifiable_stream_configuration(monkeypatch):
    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: [])
    calls = []
    admin = types.SimpleNamespace(request=lambda path, data: calls.append((path, data)))
    with pytest.raises(ValueError, match='Cannot verify'):
        hdhomerun.read_windows_builtin_tuners(admin, discover=lambda: ['192.168.8.148'],
                                             wait=lambda _: None)
    assert calls[0][0] == 'api/config/save'


def test_directed_discovery_waits_for_backend_tuners(monkeypatch):
    reads = iter([[], [], ['tuner0', 'tuner1']])
    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: next(reads))
    monkeypatch.setattr(hdhomerun, 'configured_local_ip', lambda admin: '192.168.8.211')
    monkeypatch.setattr(hdhomerun, 'local_address_for', lambda address: '192.168.8.211')
    calls = []
    admin = types.SimpleNamespace(request=lambda path, data: calls.append((path, data)))
    found = hdhomerun.read_windows_builtin_tuners(admin, discover=lambda: ['192.168.8.148'], wait=lambda _: None)
    assert found == ['tuner0', 'tuner1']
    assert calls[0][0] == 'api/config/save'
    assert json.loads(calls[0][1]['node']) == {'hdhomerun_ip': '192.168.8.148'}


@pytest.mark.parametrize('devices', [[], ['192.168.8.148', '192.168.8.149']])
def test_discovery_does_not_choose_an_ambiguous_device(monkeypatch, devices):
    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: [])
    assert hdhomerun.read_windows_builtin_tuners(None, discover=lambda: devices) == []


def test_existing_tuners_do_not_trigger_host_discovery(monkeypatch):
    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: ['existing'])
    assert hdhomerun.read_windows_builtin_tuners(None, discover=lambda: pytest.fail('Unneeded discovery')) == ['existing']


def test_wizard_uses_host_fallback_only_for_windows_builtin(monkeypatch):
    pytest.importorskip('PyQt6')
    from tvhplayer.setup_wizard import SourcePage, read_tuners, read_windows_builtin_tuners
    local = object()
    page = types.SimpleNamespace(_wizard=types.SimpleNamespace(server={'builtin': True}), _read_local_tuners=local)
    monkeypatch.setattr('sys.platform', 'win32')
    assert SourcePage._tuner_reader(page) is read_windows_builtin_tuners
    page._wizard.server = {'name': 'googlerouter'}
    assert SourcePage._tuner_reader(page) is read_tuners
    # On Linux the built-in server's reader also checks for a firewall on this computer.
    page._wizard.server = {'builtin': True}
    monkeypatch.setattr('sys.platform', 'linux')
    assert SourcePage._tuner_reader(page) is local
    page._wizard.server = {'name': 'googlerouter'}
    assert SourcePage._tuner_reader(page) is read_tuners


def test_directed_search_finds_a_device_a_firewall_hides_from_broadcasts(monkeypatch):
    """Each address of the network is asked on its own; this one answers."""
    import ipaddress
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as device:
        device.bind(('127.0.0.1', 0))
        device.settimeout(3)
        monkeypatch.setattr(hdhomerun, 'DISCOVERY_PORT', device.getsockname()[1])

        def respond():
            packet, source = device.recvfrom(2048)
            if packet == hdhomerun.discovery_request():
                device.sendto(reply(bytes.fromhex('01040000000102041240c1f5100102')), source)
        thread = threading.Thread(target=respond)
        thread.start()
        try:
            networks = [('127.0.0.2', ipaddress.IPv4Network('127.0.0.0/30')),
                        ('127.0.0.3', ipaddress.IPv4Network('127.0.0.0/16'))]
            devices = hdhomerun.sweep_host_devices(timeout=.5, networks=networks, max_hosts=8)
        finally:
            thread.join(4)
    # The /16 is too big to ask address by address, so only the /30 was asked.
    assert devices == [hdhomerun.HostTuner('127.0.0.1', '127.0.0.2', 2, 0x1240C1F5)]


def test_firewall_blocked_devices_answer_directly_but_not_to_a_broadcast():
    seen = hdhomerun.HostTuner('192.168.8.150')
    hidden = hdhomerun.HostTuner('192.168.8.148')
    assert hdhomerun.firewall_blocked_devices(broadcast=lambda: [seen], sweep=lambda: [hidden, seen]) == [
        '192.168.8.148']
    assert hdhomerun.firewall_blocked_devices(broadcast=lambda: [hidden], sweep=lambda: [hidden]) == []


def test_firewall_allow_command_only_for_ufw():
    ufw = lambda name: '/usr/sbin/ufw' if name == 'ufw' else None
    assert hdhomerun.firewall_allow_command('192.168.8.148', which=ufw) == 'sudo ufw allow from 192.168.8.148 proto udp'
    assert hdhomerun.firewall_allow_command('192.168.8.148', which=lambda _name: None) == ''
    assert hdhomerun.firewall_allow_command('not an address', which=ufw) == ''


def test_hdhomerun_address_from_the_tuner_name():
    tuner = types.SimpleNamespace(name='HDHomeRun DVB-T Tuner #0 (192.168.8.148)', hardware='')
    assert hdhomerun.hdhomerun_address(tuner) == '192.168.8.148'
    assert hdhomerun.hdhomerun_address(types.SimpleNamespace(name='DVB-T #0 (10.0.0.1)', hardware='')) == ''

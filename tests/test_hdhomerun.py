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


def test_directed_discovery_waits_for_backend_tuners(monkeypatch):
    reads = iter([[], [], ['tuner0', 'tuner1']])
    monkeypatch.setattr(hdhomerun, 'read_tuners', lambda admin: next(reads))
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
    page = types.SimpleNamespace(_wizard=types.SimpleNamespace(server={'builtin': True}))
    monkeypatch.setattr('sys.platform', 'win32')
    assert SourcePage._tuner_reader(page) is read_windows_builtin_tuners
    page._wizard.server = {'name': 'googlerouter'}
    assert SourcePage._tuner_reader(page) is read_tuners
    page._wizard.server = {'builtin': True}
    monkeypatch.setattr('sys.platform', 'linux')
    assert SourcePage._tuner_reader(page) is read_tuners

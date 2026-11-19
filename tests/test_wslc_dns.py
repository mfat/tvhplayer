"""Extra DNS for the Windows WSLc built-in server. No live resolver or container."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from tvhplayer.core.config import ConfigStore
from tvhplayer.core.windows_dns import (
    DISCOVERY_FAILED,
    DnsAddressError,
    DnsDiscoveryError,
    canonical_dns_address,
    discover_windows_dns,
    merge_dns_servers,
    select_inherited_dns,
)
from tvhplayer.core.windows_wslc import WslcError, WslcRuntimeAdapter

IMAGE = 'sha256:' + 'b' * 64
OWNER = 'a' * 32
NAME = 'tvhplayer-' + OWNER


def adapter(**kwargs):
    row = {
        'index': 1, 'up': True, 'loopback': False, 'tunnel': False, 'vpn': False,
        'hidden': False, 'has_unicast': True, 'dns_v4': ('192.168.8.1',), 'dns_v6': (),
    }
    row.update(kwargs)
    return row


def test_canonical_address_accepts_ip_literals_only():
    assert canonical_dns_address(' 1.1.1.1 ') == '1.1.1.1'
    assert canonical_dns_address('[2001:db8:0:0:0:0:0:1]') == '2001:db8::1'
    for text in ('', 'one.one.one.one', '1.1.1.1/32', '0.0.0.0', '::', '224.0.0.1', 'fe80::1%12'):
        with pytest.raises(DnsAddressError):
            canonical_dns_address(text)


def test_inherited_order_prefers_vpn_then_best_interface_and_skips_the_rest():
    rows = [
        adapter(index=2, dns_v4=('10.0.0.1',)),
        adapter(index=4, dns_v4=('192.168.8.1', '192.168.8.2'), dns_v6=('2001:db8::53',)),
        adapter(index=9, vpn=True, dns_v4=('10.8.0.1', '10.8.0.2')),
        adapter(index=1, up=False, dns_v4=('10.1.1.1',)),
        adapter(index=3, loopback=True, dns_v4=('127.0.0.1',)),
        adapter(index=5, tunnel=True, dns_v4=('10.2.2.2',)),
        adapter(index=6, hidden=True, dns_v4=('10.3.3.3',)),
        adapter(index=7, has_unicast=False, dns_v4=('10.4.4.4',)),
        adapter(index=8, dns_v4=(), dns_v6=('2001:db8::8',)),
    ]
    assert select_inherited_dns(rows, best_index=4) == ['10.8.0.1', '192.168.8.1', '192.168.8.2']


def test_inherited_list_dedupes_and_stops_at_three():
    rows = [
        adapter(index=4, dns_v4=('192.168.8.1', '192.168.8.1', '1.1.1.1', '8.8.8.8')),
        adapter(index=2, dns_v4=('9.9.9.9',)),
    ]
    assert select_inherited_dns(rows, best_index=4) == ['192.168.8.1', '1.1.1.1', '8.8.8.8']


def test_merge_prefers_custom_dns_while_retaining_windows_dns():
    assert merge_dns_servers(['192.168.8.1', '192.168.8.1'], '172.23.160.1') == [
        '172.23.160.1', '192.168.8.1']
    assert merge_dns_servers(['192.168.8.1', '1.1.1.1'], '1.1.1.1') == ['1.1.1.1', '192.168.8.1']
    assert merge_dns_servers(['192.168.8.1', '1.1.1.1', '8.8.8.8'], '9.9.9.9') == [
        '9.9.9.9', '192.168.8.1', '1.1.1.1', '8.8.8.8']
    with pytest.raises(DnsDiscoveryError, match='was not applied'):
        merge_dns_servers([], '1.1.1.1')


def test_custom_dns_is_always_within_glibc_first_three():
    servers = merge_dns_servers(['192.168.8.1', '192.168.8.2', '10.0.0.53'], '172.23.160.1')
    assert servers == ['172.23.160.1', '192.168.8.1', '192.168.8.2', '10.0.0.53']
    assert servers[0] == '172.23.160.1'


def test_discovery_is_refused_off_windows(monkeypatch):
    monkeypatch.setattr('tvhplayer.core.windows_dns.sys.platform', 'linux')
    with pytest.raises(DnsDiscoveryError, match='was not applied'):
        discover_windows_dns()


def test_saved_dns_setting_keeps_a_valid_address_and_drops_a_bad_one(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({
        'wslc_extra_dns': True,
        'wslc_extra_dns_address': '2001:db8:0:0:0:0:0:1',
    }), encoding='utf-8')
    data = ConfigStore(path).data
    assert data['wslc_extra_dns'] is True
    assert data['wslc_extra_dns_address'] == '2001:db8::1'
    path.write_text(json.dumps({
        'wslc_extra_dns': True, 'wslc_extra_dns_address': 'dns.example',
    }), encoding='utf-8')
    data = ConfigStore(path).data
    assert data['wslc_extra_dns'] is False
    assert data['wslc_extra_dns_address'] == ''
    path.write_text(json.dumps({
        'wslc_extra_dns': False, 'wslc_extra_dns_address': '8.8.8.8',
    }), encoding='utf-8')
    data = ConfigStore(path).data
    assert data['wslc_extra_dns'] is False
    assert data['wslc_extra_dns_address'] == '8.8.8.8'


class Cli:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, '', '')


def _runtime():
    runtime = WslcRuntimeAdapter('wslc.exe', Cli())
    runtime.config_storage = SimpleNamespace(volume='tvhplayer-config-' + OWNER)
    return runtime


def test_launch_without_extra_dns_adds_no_dns_flags_and_keeps_published_ports():
    runtime = _runtime()
    udp = [('192.168.8.211', 30000), ('192.168.8.211', 30001)]
    runtime.launch(IMAGE, NAME, OWNER, r'C:\Config', r'D:\TV recordings', (24111, 24112), udp)
    args = runtime.runner.calls[0]
    assert '--dns' not in args
    assert args.count('--publish') == 4
    assert '127.0.0.1:24111:9981/tcp' in args
    assert '127.0.0.1:24112:9982/tcp' in args
    assert '192.168.8.211:30000:30000/udp' in args
    assert '192.168.8.211:30001:30001/udp' in args


def test_launch_uses_preferred_dns_first_without_changing_tcp_udp_publication():
    runtime = _runtime()
    udp = [('192.168.8.211', 30000)]
    runtime.launch(
        IMAGE, NAME, OWNER, r'C:\Config', r'D:\TV recordings', (24111, 24112), udp,
        dns_servers=('172.23.160.1', '192.168.8.1'))
    args = runtime.runner.calls[0]
    assert args[args.index('--dns') + 1] == '172.23.160.1'
    flags = [args[index + 1] for index, arg in enumerate(args) if arg == '--dns']
    assert flags == ['172.23.160.1', '192.168.8.1']
    assert '127.0.0.1:24111:9981/tcp' in args
    assert '127.0.0.1:24112:9982/tcp' in args
    assert '192.168.8.211:30000:30000/udp' in args
    assert '--noacl' in args[-1].split()


def test_launch_rejects_an_invalid_dns_server_before_starting():
    runtime = _runtime()
    with pytest.raises(WslcError):
        runtime.launch(IMAGE, NAME, OWNER, r'C:\Config', r'D:\TV', (24111, 24112),
                       dns_servers=('192.168.8.1', 'not-dns'))
    assert runtime.runner.calls == []


def test_supervisor_skips_discovery_when_extra_dns_is_off(monkeypatch):
    pytest.importorskip('PyQt6')
    from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
    calls = []
    monkeypatch.setattr(
        'tvhplayer.core.windows_dns.discover_windows_dns',
        lambda: calls.append(True) or ['192.168.8.1'])
    supervisor = SimpleNamespace()
    assert WslcBuiltinSupervisor._extra_dns_servers(supervisor, '') == ()
    assert calls == []


def test_supervisor_appends_discovered_dns_and_reports_a_failed_lookup(monkeypatch):
    pytest.importorskip('PyQt6')
    from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
    calls = []

    def discover():
        calls.append(True)
        return ['192.168.8.1']

    monkeypatch.setattr('tvhplayer.core.windows_dns.discover_windows_dns', discover)
    supervisor = SimpleNamespace(_progress=lambda message: None, _emit_log=lambda text: None)
    assert WslcBuiltinSupervisor._extra_dns_servers(supervisor, '172.23.160.1') == (
        '172.23.160.1', '192.168.8.1')
    assert WslcBuiltinSupervisor._extra_dns_servers(supervisor, '172.23.160.1') == (
        '172.23.160.1', '192.168.8.1')
    assert len(calls) == 2
    monkeypatch.setattr('tvhplayer.core.windows_dns.discover_windows_dns', lambda: [])
    with pytest.raises(WslcError, match='was not applied') as error:
        WslcBuiltinSupervisor._extra_dns_servers(supervisor, '1.1.1.1')
    assert '1.1.1.1' not in str(error.value)
    assert DISCOVERY_FAILED.split('.')[0] in str(error.value)


def test_saving_the_setting_does_not_discover_dns_on_the_ui_thread(monkeypatch, tmp_path):
    from tests.test_pyqt6_ui import _make_player
    from tvhplayer.settings_dialog import SettingsDialog

    def discover():
        raise AssertionError('DNS discovery ran while saving the setting')

    monkeypatch.setattr('tvhplayer.core.windows_dns.discover_windows_dns', discover)
    app, _ui, window, _player = _make_player(monkeypatch, tmp_path)
    dialog = None
    try:
        window.builtin = SimpleNamespace(
            uses_wslc=True, extra_dns='', is_running=lambda: False, shut_down=lambda: None)
        dialog = SettingsDialog(window, window)
        titles = [dialog.nav.item(row).text() for row in range(dialog.nav.count())]
        assert titles[-1] == 'Built-in Server'
        assert 'Built-in Server' not in [title for title, _subtitle in dialog.PAGES]
        dialog.dns_edit.setText('not-dns')
        dialog.dns_check.click()
        assert window.config['wslc_extra_dns'] is False
        dialog.dns_edit.setText('172.23.160.1')
        dialog.dns_edit.editingFinished.emit()
        assert window.config['wslc_extra_dns'] is True
        assert window.config['wslc_extra_dns_address'] == '172.23.160.1'
        assert window.builtin.extra_dns == '172.23.160.1'
        window.builtin.is_running = lambda: True
        dialog.dns_check.click()
        assert window.config['wslc_extra_dns'] is False
        assert window.config['wslc_extra_dns_address'] == '172.23.160.1'
        assert window.builtin.extra_dns == ''
        assert 'Restart the built-in server' in window.status_label.text()
        window.builtin.is_running = lambda: False
    finally:
        window._confirm_quit = lambda: True
        if dialog is not None:
            dialog.close()
        window.close()
        app.processEvents()


def test_dns_page_stays_hidden_without_the_wslc_backend(monkeypatch, tmp_path):
    from tests.test_pyqt6_ui import _make_player
    from tvhplayer.settings_dialog import SettingsDialog

    app, _ui, window, _player = _make_player(monkeypatch, tmp_path)
    try:
        assert not getattr(window.builtin, 'uses_wslc', False)
        dialog = SettingsDialog(window, window)
        titles = [dialog.nav.item(row).text() for row in range(dialog.nav.count())]
        assert 'Built-in Server' not in titles
        assert titles[-1] == 'Updates'
    finally:
        window._confirm_quit = lambda: True
        window.close()
        app.processEvents()

import json

from tvhplayer.core.tuner_setup import (
    create_tuner_network,
    map_services,
    fallback_name,
    mapper_progress,
    name_unnamed_channels,
    network_name,
    scan_progress,
    scan_regions,
    services_to_map,
    us_rf_channel,
)
from tvhplayer.core.tuners import Tuner


class Admin:
    def __init__(self):
        self.requests = []
        self.saved = []
        self.scanned = []
        self.tree = {}
        self.muxes = []
        self.services = []
        self.streams = {}

    def request(self, path, data=None, params=None):
        self.requests.append((path, data, params))
        if path == 'api/service/streams':
            return {'streams': [{'type': kind} for kind in self.streams.get(params['uuid'], [])]}
        if path == 'api/dvb/scanfile/list':
            return {'entries': [
                {'key': 'dvbt/uk/dvb-t_uk-CrystalPalace', 'val': 'United Kingdom: uk-CrystalPalace'},
                {'key': 'dvbt/auto/dvb-t_auto-Default', 'val': '--Generic--: auto-Default'},
            ]}
        if path == 'api/mpegts/network/create':
            return {'uuid': 'net'}
        if path == 'api/service/mapper/status':
            return {'total': 4, 'ok': 2, 'fail': 1, 'ignore': 0}
        return {}

    def hardware_tree(self, uuid='root'):
        return self.tree.get(uuid, [])

    def save(self, nodes):
        self.saved.extend(nodes)

    def scan_network(self, uuid):
        self.scanned.append(uuid)

    def list_muxes(self, network_uuid):
        return self.muxes

    def list_services(self, mux_uuids):
        return self.services


def test_windows_pinned_scan_table_names_and_returned_keys_are_preserved():
    class PinnedAdmin:
        def request(self, path, params):
            assert path == 'api/dvb/scanfile/list'
            assert params == {'type': 'dvb-t'}
            return {'entries': [{'key': 'dvb-t/auto/dvb-t_auto-Defaul', 'val': '--Generic--: auto-Default'}]}
    assert scan_regions(PinnedAdmin(), 'DVB-T', canonical=True) == [
        ('dvb-t/auto/dvb-t_auto-Defaul', '--Generic--: auto-Default')]


def test_windows_scan_table_loading_is_retried_without_changing_other_servers(monkeypatch):
    import pytest
    from tvhplayer.core.errors import TvhError
    monkeypatch.setattr('tvhplayer.core.tuner_setup.time.sleep', lambda delay: None)
    class LoadingAdmin:
        calls = 0
        def request(self, path, params):
            self.calls += 1
            if self.calls == 1:
                raise TvhError('HTTP 400 for api/dvb/scanfile/list: loading')
            return {'entries': []}
    admin = LoadingAdmin()
    assert scan_regions(admin, 'DVB-T', canonical=True) == []
    assert admin.calls == 2
    with pytest.raises(TvhError):
        scan_regions(LoadingAdmin(), 'DVB-T')


def test_regions_are_sorted_and_named():
    admin = Admin()
    regions = scan_regions(admin, 'DVB-T')
    assert [label for _key, label in regions] == ['--Generic--: auto-Default', 'United Kingdom: uk-CrystalPalace']
    assert admin.requests[0][2] == {'type': 'dvbt'}
    assert network_name('DVB-T', 'United Kingdom: uk-CrystalPalace') == 'DVB-T uk-CrystalPalace'


def test_network_is_created_given_to_tuners_and_scanned():
    admin = Admin()
    tuner = Tuner(uuid='fe0', name='DVB-T #0', kind='DVB-T', enabled=False, networks=['old'])
    assert create_tuner_network(admin, 'DVB-T', 'dvbt/uk/x', 'DVB-T x', [tuner]) == 'net'
    path, data, _params = admin.requests[0]
    assert path == 'api/mpegts/network/create'
    assert data['class'] == 'dvb_network_dvbt'
    assert json.loads(data['conf']) == {'networkname': 'DVB-T x', 'scanfile': 'dvbt/uk/x'}
    assert admin.saved == [{'uuid': 'fe0', 'enabled': True, 'networks': ['old', 'net']}]
    assert admin.scanned == ['net']


def test_satellite_networks_go_to_the_dish_settings():
    admin = Admin()
    admin.tree = {
        'fe0': [{'uuid': 'satconf', 'leaf': 0, 'params': []}],
        'satconf': [{'uuid': 'ele', 'leaf': 1, 'params': [{'id': 'networks', 'value': []}]}],
    }
    tuner = Tuner(uuid='fe0', name='DVB-S #0', kind='DVB-S', enabled=True)
    create_tuner_network(admin, 'DVB-S', 'dvbs/geo/x', 'DVB-S x', [tuner])
    assert admin.saved == [{'uuid': 'fe0', 'enabled': True}, {'uuid': 'ele', 'enabled': True, 'networks': ['net']}]


def test_scan_progress_and_services():
    admin = Admin()
    admin.muxes = [
        {'uuid': 'm1', 'scan_state': 0, 'scan_result': 1, 'num_svc': 5},
        {'uuid': 'm2', 'scan_state': 0, 'scan_result': 2, 'num_svc': 0},
        {'uuid': 'm3', 'scan_state': 3, 'scan_result': 0, 'num_svc': 1},
    ]
    progress = scan_progress(admin, 'net')
    assert (progress.muxes, progress.scanned, progress.working, progress.services) == (3, 2, 1, 6)
    assert not progress.done
    admin.services = [
        {'uuid': 's1', 'svcname': 'BBC ONE'},
        {'uuid': 's2', 'svcname': 'Sky', 'encrypted': True},
        {'uuid': 's3', 'svcname': ''},
        {'uuid': 's4', 'svcname': 'Mapped', 'channel': ['c']},
        {'uuid': 's5', 'svcname': None, 'sid': 3},
        {'uuid': 's6', 'sid': 4},
    ]
    # A nameless service is a channel when it has picture or sound, and data otherwise.
    admin.streams = {'s3': ['PCR', 'PMT'], 's5': ['PCR', 'PMT', 'H264', 'AC3'], 's6': ['AC-4']}
    assert services_to_map(admin, 'net') == ['s1', 's5', 's6']
    assert services_to_map(admin, 'net', include_encrypted=True) == ['s1', 's2', 's5', 's6']
    map_services(admin, ['s1'])
    path, data, _params = admin.requests[-1]
    assert path == 'api/service/mapper/save'
    assert json.loads(data['node'])['services'] == ['s1']
    assert mapper_progress(admin) == (3, 4)


def test_us_rf_channel_from_scan_table_frequencies():
    assert us_rf_channel(57000000) == 2
    assert us_rf_channel(85000000) == 6
    assert us_rf_channel(177000000) == 7
    assert us_rf_channel(213000000) == 13
    assert us_rf_channel(473000000) == 14
    assert us_rf_channel(527000000) == 23
    assert us_rf_channel(695028615) == 51
    assert us_rf_channel(100000000) is None
    assert us_rf_channel(None) is None


def test_fallback_names():
    assert fallback_name({'delsys': 'ATSC-T', 'frequency': 545000000, 'name': '545MHz'}, 3) == 'RF 26 – 3'
    assert fallback_name({'delsys': 'DVB-T', 'frequency': 191500000, 'name': '191.5MHz'}, 7) == '191.5MHz – 7'
    assert fallback_name({'delsys': 'ATSC-C', 'frequency': 57000000, 'name': '57MHz'}, 1) == '57MHz – 1'
    assert fallback_name({}, 5) == 'Channel 5'


def test_name_unnamed_channels_renames_only_channels_of_nameless_services():
    admin = Admin()
    admin.muxes = [{'uuid': 'm1', 'delsys': 'ATSC-T', 'frequency': 545000000, 'name': '545MHz'}]
    admin.services = [
        {'uuid': 's1', 'multiplex_uuid': 'm1', 'sid': 1, 'svcname': 'WBTV', 'channel': ['c1']},
        {'uuid': 's2', 'multiplex_uuid': 'm1', 'sid': 3, 'svcname': '', 'channel': ['c2']},
        {'uuid': 's3', 'multiplex_uuid': 'm1', 'sid': 4, 'channel': ['c3']},
    ]
    admin.services.append({'uuid': 's4', 'multiplex_uuid': 'm1', 'sid': 5, 'channel': []})
    named = set()
    # s3 was not mapped in this run, so its channel keeps whatever name it has.
    # s4's channel is not made yet, so it is waited for.
    assert name_unnamed_channels(admin, 'net', ['s1', 's2', 's4'], named) == 1
    assert admin.saved == [{'uuid': 'c2', 'name': 'RF 26 – 3'}]
    admin.services[3]['channel'] = ['c4']
    assert name_unnamed_channels(admin, 'net', ['s1', 's2', 's4'], named) == 0
    assert admin.saved == [{'uuid': 'c2', 'name': 'RF 26 – 3'}, {'uuid': 'c4', 'name': 'RF 26 – 5'}]


def test_wizard_scans_a_tuner_and_adds_channels(monkeypatch):
    import os

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication, QWizard

    from tvhplayer import setup_wizard

    app = QApplication.instance() or QApplication([])
    admin = Admin()
    admin.tree = {
        'root': [{'uuid': 'ad0', 'text': 'Adapter 0', 'class': 'linuxdvb_adapter', 'leaf': 0}],
        'ad0': [{'uuid': 'fe0', 'text': 'DVB-T #0', 'class': 'linuxdvb_frontend_dvbt', 'leaf': 1,
                 'params': [{'id': 'enabled', 'value': True}]}],
    }
    admin.muxes = [{'uuid': 'm1', 'scan_state': 0, 'scan_result': 1, 'num_svc': 3, 'name': '506MHz'}]
    admin.services = [{'uuid': 's1', 'svcname': 'One'}, {'uuid': 's2', 'svcname': 'Two'},
                      {'uuid': 's3', 'multiplex_uuid': 'm1', 'sid': 9}]
    admin.streams = {'s3': ['MPEG2VIDEO', 'MPEG2AUDIO']}
    admin.request_status = None
    original = admin.request

    def request(path, data=None, params=None):
        if path == 'api/service/mapper/status':
            # The server reports the mapping done before it makes the channels.
            return {'total': 3, 'ok': 3}
        return original(path, data, params)

    admin.request = request
    monkeypatch.setattr(setup_wizard.SetupWizard, 'call', lambda self, fn, slot: slot(fn(admin), ''))
    done, iptv = [], []
    wizard = setup_wizard.SetupWizard({'name': 'Built-in'}, iptv.append, done.append)
    wizard.show()
    page = wizard.source_page
    assert page.tuner_radio.isChecked()
    assert 'DVB-T #0' in page.status.text()
    assert any(label.text() == 'DVB-T #0' for label in page.findChildren(type(page.status)))
    wizard.next()
    tuners = wizard.tuner_page
    assert tuners.kind() == 'DVB-T'
    assert len(tuners.chosen_tuners()) == 1
    assert not tuners.isComplete()
    tuners.region_filter.setText('crystal')
    assert tuners.region_list.count() == 1
    tuners.region_list.setCurrentRow(0)
    assert tuners.isComplete()
    wizard.next()
    scan = wizard.scan_page
    scan._poll()
    scan._poll()
    assert not scan.isComplete()
    # The channel of the nameless service arrives, and gets a readable name.
    admin.services[2]['channel'] = ['c3']
    scan._poll()
    assert scan.isComplete()
    assert 'Added 3 channels' in scan.status.text()
    assert admin.saved[0] == {'uuid': 'fe0', 'enabled': True, 'networks': ['net']}
    assert admin.saved[-1] == {'uuid': 'c3', 'name': '506MHz – 9'}
    wizard.done(QWizard.DialogCode.Accepted)
    assert done == [{'name': 'Built-in'}] and iptv == []
    app.processEvents()


def test_wizard_picks_which_server_receives_the_channels(monkeypatch):
    import os

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    from tvhplayer import setup_wizard

    app = QApplication.instance() or QApplication([])
    servers = [
        {'name': 'Built-in', 'builtin': True},
        {'name': 'Living room', 'url': 'http://tv.local:9981'},
    ]
    seen = []

    def fake_call(self, fn, slot):
        seen.append(self.server['name'])
        slot([], '')

    monkeypatch.setattr(setup_wizard.SetupWizard, 'call', fake_call)
    wizard = setup_wizard.SetupWizard(servers[0], lambda _server: None, lambda _server: None, servers=servers)
    wizard.show()
    page = wizard.source_page
    assert page.server_combo.count() == 2
    assert page.server_combo.currentText() == 'Built-in'
    assert any(label.text().replace('&', '') == 'Channels will be added to' for label in page.findChildren(type(page.status)))
    page.server_combo.setCurrentIndex(1)
    assert wizard.server['name'] == 'Living room'
    assert seen[-1] == 'Living room'
    app.processEvents()


def test_wizard_hands_iptv_to_the_playlist_import(monkeypatch):
    import os

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication, QWizard

    from tvhplayer import setup_wizard

    app = QApplication.instance() or QApplication([])
    admin = Admin()
    monkeypatch.setattr(setup_wizard.SetupWizard, 'call', lambda self, fn, slot: slot(fn(admin), ''))
    done, iptv = [], []
    wizard = setup_wizard.SetupWizard({'name': 'Built-in'}, iptv.append, done.append)
    wizard.show()
    page = wizard.source_page
    # No tuner: only the playlist can be chosen, and it is.
    assert not page.tuner_radio.isEnabled()
    assert page.iptv_radio.isChecked()
    assert page.status.text().startswith('No tuner found.')
    assert page.nextId() == -1
    wizard.done(QWizard.DialogCode.Accepted)
    assert iptv == [{'name': 'Built-in'}] and done == []
    app.processEvents()

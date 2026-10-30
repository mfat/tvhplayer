import json

from tvhplayer.core.tuner_setup import (
    create_tuner_network,
    map_services,
    mapper_progress,
    network_name,
    scan_progress,
    scan_regions,
    services_to_map,
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

    def request(self, path, data=None, params=None):
        self.requests.append((path, data, params))
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
    ]
    assert services_to_map(admin, 'net') == ['s1']
    assert services_to_map(admin, 'net', include_encrypted=True) == ['s1', 's2']
    map_services(admin, ['s1'])
    path, data, _params = admin.requests[-1]
    assert path == 'api/service/mapper/save'
    assert json.loads(data['node'])['services'] == ['s1']
    assert mapper_progress(admin) == (3, 4)


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
    admin.muxes = [{'uuid': 'm1', 'scan_state': 0, 'scan_result': 1, 'num_svc': 2}]
    admin.services = [{'uuid': 's1', 'svcname': 'One'}, {'uuid': 's2', 'svcname': 'Two'}]
    admin.request_status = None
    original = admin.request

    def request(path, data=None, params=None):
        if path == 'api/service/mapper/status':
            return {'total': 2, 'ok': 2}
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
    assert scan.isComplete()
    assert 'Added 2 channels' in scan.status.text()
    assert admin.saved[0] == {'uuid': 'fe0', 'enabled': True, 'networks': ['net']}
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

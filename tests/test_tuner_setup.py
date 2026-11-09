import json

from tvhplayer.core.tuner_setup import (
    FREQ_CHANNELS,
    FREQ_EMPTY,
    FREQ_NO_DATA,
    FREQ_NO_SIGNAL,
    FREQ_SCANNING,
    FREQ_WAITING,
    ChannelPlan,
    Frequency,
    ScanProgress,
    create_tuner_network,
    fallback_name,
    follow_new_channels,
    frequency_label,
    map_services,
    mapper_progress,
    network_name,
    plan_channels,
    scan_progress,
    scan_regions,
    scan_summary,
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
        self.inputs = []

    def request(self, path, data=None, params=None):
        self.requests.append((path, data, params))
        if path == 'api/status/inputs':
            return {'entries': self.inputs}
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
    # s1 has a name but no picture or sound: kept, and counted as possibly silent.
    plan = plan_channels(admin, 'net')
    assert plan.services == ['s1', 's5', 's6'] and plan.silent == 1
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


def test_follow_new_channels_counts_them_and_names_those_of_nameless_services():
    admin = Admin()
    admin.muxes = [{'uuid': 'm1', 'delsys': 'ATSC-T', 'frequency': 545000000, 'name': '545MHz'}]
    admin.services = [
        {'uuid': 's1', 'multiplex_uuid': 'm1', 'sid': 1, 'svcname': 'WBTV', 'channel': ['c1']},
        {'uuid': 's2', 'multiplex_uuid': 'm1', 'sid': 3, 'svcname': '', 'channel': ['c2']},
        {'uuid': 's3', 'multiplex_uuid': 'm1', 'sid': 4, 'channel': ['c3']},
        {'uuid': 's4', 'multiplex_uuid': 'm1', 'sid': 5, 'channel': []},
    ]
    named = set()
    # s3 was not mapped in this run, so its channel keeps whatever name it has.
    # s4's channel is not made yet.
    assert follow_new_channels(admin, 'net', ['s1', 's2', 's4'], named) == (2, 1)
    assert admin.saved == [{'uuid': 'c2', 'name': 'RF 26 – 3'}]
    admin.services[3]['channel'] = ['c4']
    assert follow_new_channels(admin, 'net', ['s1', 's2', 's4'], named) == (3, 0)
    assert admin.saved == [{'uuid': 'c2', 'name': 'RF 26 – 3'}, {'uuid': 'c4', 'name': 'RF 26 – 5'}]


def _input(stream, snr=0, bps=0):
    return {'input': 'HDHomeRun Tuner #0', 'stream': stream, 'subs': 1,
            'signal': 30000, 'signal_scale': 1, 'snr': snr, 'snr_scale': 1, 'bps': bps}


def test_scan_progress_tells_why_each_frequency_failed():
    """What the tuners report while a frequency is scanned decides its result.

    The readings are the ones a real HDHomeRun gave: about 40% strength and
    0 quality with no station, 84% quality once it locks on.
    """
    admin = Admin()
    base = {'network': 'ATSC-T us', 'delsys': 'ATSC-T', 'num_svc': 0, 'scan_result': 0}
    admin.muxes = [
        dict(base, uuid='a', name='473MHz', frequency=473000000, scan_state=3),
        dict(base, uuid='b', name='479MHz', frequency=479000000, scan_state=3),
        dict(base, uuid='c', name='485MHz', frequency=485000000, scan_state=3),
        dict(base, uuid='d', name='491MHz', frequency=491000000, scan_state=1),
    ]
    admin.inputs = [
        _input('473MHz in ATSC-T us', snr=55000, bps=0),       # locked on, no data yet
        _input('479MHz in ATSC-T us', snr=0, bps=0),           # nothing there
        _input('485MHz in ATSC-T us', snr=55000, bps=157920),  # data arriving
    ]
    seen = {}
    progress = scan_progress(admin, 'net', seen)
    states = {item.uuid: item.state for item in progress.frequencies}
    assert states == {'a': FREQ_SCANNING, 'b': FREQ_SCANNING, 'c': FREQ_SCANNING, 'd': FREQ_WAITING}
    assert progress.frequencies[0].label == 'RF 14 (473MHz)'
    assert progress.frequencies[0].reception.words.startswith('Signal good')
    from tvhplayer.setup_wizard import _frequency_text
    assert _frequency_text(progress.frequencies[0]) == 'RF 14 (473MHz): scanning. Signal good (quality 84%)'
    assert _frequency_text(progress.frequencies[1]) == 'RF 15 (479MHz): scanning, looking for a signal'
    # All three fail; the tuners are free again and report nothing.
    for mux in admin.muxes[:3]:
        mux.update(scan_state=0, scan_result=2)
    admin.inputs = []
    progress = scan_progress(admin, 'net', seen)
    states = {item.uuid: item.state for item in progress.frequencies}
    assert states == {'a': FREQ_NO_DATA, 'b': FREQ_NO_SIGNAL, 'c': FREQ_EMPTY, 'd': FREQ_WAITING}
    assert (progress.scanned, progress.muxes) == (3, 4)
    admin.muxes[3].update(scan_state=0, scan_result=1, num_svc=6)
    progress = scan_progress(admin, 'net', seen)
    assert progress.frequencies[3].state == FREQ_CHANNELS and progress.done


def test_frequency_labels():
    assert frequency_label({'delsys': 'ATSC-T', 'frequency': 545000000, 'name': '545MHz'}) == 'RF 26 (545MHz)'
    assert frequency_label({'delsys': 'DVB-T', 'frequency': 554000000, 'name': '554MHz'}) == '554MHz'


def _progress(*states):
    return ScanProgress(muxes=len(states), scanned=len(states), frequencies=[
        Frequency(uuid=str(index), label=str(index), state=state) for index, state in enumerate(states)])


def test_scan_summary_says_what_went_wrong():
    assert scan_summary(_progress(FREQ_CHANNELS, FREQ_NO_SIGNAL), ChannelPlan(['s1', 's2']), 2) == (
        'Added 2 channels. The TV guide fills in over the next minutes as the channels broadcast it.')
    text = scan_summary(_progress(FREQ_CHANNELS, FREQ_NO_DATA, FREQ_NO_DATA), ChannelPlan(['s1'], silent=1), 1)
    assert text.startswith('Added 1 channel. On 2 frequencies the tuner found a signal, but no data reached the server.')
    assert '1 channel has no picture or sound information' in text
    advice = 'If ufw is on, this lets the HDHomeRun through: sudo ufw allow from 192.168.8.148 proto udp'
    text = scan_summary(_progress(FREQ_NO_DATA), ChannelPlan(), 0, advice)
    assert text.endswith('can cause this. ' + advice)
    assert scan_summary(_progress(FREQ_NO_SIGNAL, FREQ_NO_SIGNAL), ChannelPlan(), 0) == (
        'No channels were found. No frequency had a signal. Check that the aerial, cable, or dish is '
        'connected to the tuner, and that you chose the right region or satellite.')
    assert scan_summary(_progress(FREQ_NO_DATA), ChannelPlan(), 0).startswith(
        'No channels were found. On 1 frequency the tuner found a signal, but no data reached the server.')
    assert scan_summary(_progress(FREQ_EMPTY), ChannelPlan(), 0).startswith(
        'No channels were found. Check that the aerial')
    assert scan_summary(_progress(FREQ_CHANNELS), ChannelPlan(['s1', 's2']), 0).startswith(
        'The server did not add any of the 2 channels found.')


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
    admin.muxes = [
        {'uuid': 'm1', 'scan_state': 0, 'scan_result': 1, 'num_svc': 3, 'name': '506MHz', 'frequency': 506000000},
        {'uuid': 'm2', 'scan_state': 0, 'scan_result': 2, 'num_svc': 0, 'name': '514MHz', 'frequency': 514000000},
    ]
    admin.services = [{'uuid': 's1', 'svcname': 'One'}, {'uuid': 's2', 'svcname': 'Two'},
                      {'uuid': 's3', 'multiplex_uuid': 'm1', 'sid': 9}]
    admin.streams = {'s1': ['H264', 'AAC'], 's2': ['H264', 'AAC'], 's3': ['MPEG2VIDEO', 'MPEG2AUDIO']}
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
    assert [scan.frequency_list.item(row).text() for row in range(scan.frequency_list.count())] == [
        '506MHz: 3 channels', '514MHz: no station']
    assert scan.counts.text() == (
        'Checked 2 of 2 frequencies: 1 with channels, 1 with no station. Found 3 channels so far.')
    # The server makes the channels a moment after it is asked to.
    scan._poll()
    assert not scan.isComplete()
    for service, channel in zip(admin.services, ('c1', 'c2', 'c3')):
        service['channel'] = [channel]
    scan._poll()
    assert scan.isComplete()
    assert scan.status.text().startswith('Added 3 channels.')
    assert scan.added == 3
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


def test_wizard_says_when_a_firewall_hides_an_hdhomerun(monkeypatch):
    import os

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    from tvhplayer import setup_wizard

    app = QApplication.instance() or QApplication([])
    font = app.font()
    bigger = app.font()
    bigger.setPointSizeF(12)
    app.setFont(bigger)
    admin = Admin()
    monkeypatch.setattr(setup_wizard.sys, 'platform', 'linux')
    monkeypatch.setattr(setup_wizard, 'firewall_blocked_devices', lambda: ['192.168.8.148'])
    monkeypatch.setattr(setup_wizard, 'firewall_allow_command',
                        lambda address: f'sudo ufw allow from {address} proto udp')
    monkeypatch.setattr(setup_wizard.SetupWizard, 'call', lambda self, fn, slot: slot(fn(admin), ''))
    wizard = setup_wizard.SetupWizard({'name': 'Built-in', 'builtin': True}, lambda _s: None, lambda _s: None)
    wizard.show()
    page = wizard.source_page
    assert page.status.text() == 'No tuner the server can use was found.'
    assert page.firewall.isVisibleTo(page)
    assert page.firewall_note.text() == (
        'Found an HDHomeRun at 192.168.8.148, but a firewall on this computer blocks it from the built-in '
        'server. To allow it, run this in a terminal, then choose Look again:')
    assert page.firewall_command.text() == 'sudo ufw allow from 192.168.8.148 proto udp'
    # The window grows for the note: Qt would squeeze it to a line or two.
    for _ in range(3):
        app.processEvents()
    note = page.firewall_note
    assert note.height() >= note.heightForWidth(note.width())
    page.copy_command_btn.click()
    assert QApplication.clipboard().text() == 'sudo ufw allow from 192.168.8.148 proto udp'
    # Once allowed, the server finds it and the note goes.
    monkeypatch.setattr(setup_wizard, 'firewall_blocked_devices', lambda: [])
    page.look_again()
    assert not page.firewall.isVisibleTo(page)
    assert not page.copy_command_btn.isVisibleTo(page)
    wizard.close()
    app.setFont(font)
    app.processEvents()

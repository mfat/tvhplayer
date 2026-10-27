import json

from tvhplayer.core.config import ConfigStore, default_config


def test_config_roundtrip_normalizes_servers(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    store.servers = [{'name': 'box', 'url': 'http://127.0.0.1:9981'}]
    store.data['last_server'] = 0
    store.save()

    loaded = ConfigStore(path)
    assert loaded.servers[0]['protocol'] == 'http'
    assert loaded.servers[0]['htsp_port'] == 9982
    assert loaded.data['window_geometry']['width'] == 1200


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_text('{not json', encoding='utf-8')
    store = ConfigStore(path)
    assert store.data['servers'] == []
    assert store.data['volume'] == default_config()['volume']


def test_missing_file_uses_defaults(tmp_path):
    store = ConfigStore(tmp_path / 'missing.conf')
    assert store.data == default_config()
    store.save()
    assert json.loads((tmp_path / 'missing.conf').read_text())['volume'] == 50


def test_theme_defaults_to_tvhplayer_and_keeps_a_qt_style_name(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    for saved, loaded in ((None, 'TVHplayer'), ('', 'TVHplayer'), (3, 'TVHplayer'), ('Breeze', 'Breeze')):
        path.write_text(json.dumps({'ui_theme': saved}), encoding='utf-8')
        assert ConfigStore(path).data['ui_theme'] == loaded


def test_saved_volume_keeps_silence_and_stays_in_range(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    for saved, loaded in ((0, 0), (73, 73), (250, 100), ('loud', 50)):
        path.write_text(json.dumps({'volume': saved}), encoding='utf-8')
        assert ConfigStore(path).data['volume'] == loaded


def test_playlists_are_saved_and_cleaned(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({'playlists': [
        {'name': 'ir', 'location': 'http://a/ir.m3u', 'server': 'builtin', 'muxes': {'id:a': 'm1'}},
        'junk',
    ]}), encoding='utf-8')
    store = ConfigStore(path)
    assert store.data['playlists'] == [{
        'name': 'ir',
        'location': 'http://a/ir.m3u',
        'server': 'builtin',
        'network_uuid': '',
        'muxes': {'id:a': 'm1'},
        'allow_commands': False,
        'tags': [],
        'max_streams': 0,
        'chosen_groups': None,
        'left_out': [],
    }]


def test_every_setting_has_a_default_and_bad_values_are_replaced(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({
        'local_recording_format': 'avi',
        'local_recording_dir': None,
        'convert_options': 3,
        'last_channel': 'BBC',
        'hide_dead_channels': 0,
    }), encoding='utf-8')
    data = ConfigStore(path).data
    assert set(data) == set(default_config())
    assert data['local_recording_format'] == 'ts'
    assert data['local_recording_dir'] == ''
    assert data['convert_options'] == ''
    assert data['last_channel'] == {}
    assert data['hide_dead_channels'] is False
    assert default_config()['hide_dead_channels'] is True

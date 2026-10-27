import json
import os

import pytest

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
    assert (tmp_path / 'tvhplayer.conf.broken').read_text(encoding='utf-8') == '{not json'
    store.save()
    assert (tmp_path / 'tvhplayer.conf.broken').read_text(encoding='utf-8') == '{not json'


def test_config_that_is_not_text_falls_back_to_defaults(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_bytes(b'\xff\xfe{')
    assert ConfigStore(path).data['servers'] == []
    assert (tmp_path / 'tvhplayer.conf.broken').exists()


def test_save_replaces_the_file_whole_and_owner_only(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    store.data['volume'] = 30
    store.save()
    assert json.loads(path.read_text())['volume'] == 30
    assert [item.name for item in tmp_path.iterdir()] == ['tvhplayer.conf']
    if os.name == 'posix':
        assert path.stat().st_mode & 0o777 == 0o600


def test_failed_save_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    store.data['volume'] = 30
    store.save()

    def full_disk(*args, **kwargs):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(json, 'dump', full_disk)
    store.data['volume'] = 70
    with pytest.raises(OSError):
        store.save()
    assert json.loads(path.read_text())['volume'] == 30
    assert [item.name for item in tmp_path.iterdir()] == ['tvhplayer.conf']


def test_save_through_a_link_keeps_the_link(tmp_path):
    if os.name != 'posix':
        pytest.skip('symlinks')
    real = tmp_path / 'dotfiles' / 'tvhplayer.conf'
    real.parent.mkdir()
    real.write_text('{}', encoding='utf-8')
    link = tmp_path / 'tvhplayer.conf'
    link.symlink_to(real)
    store = ConfigStore(link)
    store.data['volume'] = 30
    store.save()
    assert link.is_symlink()
    assert json.loads(real.read_text())['volume'] == 30


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


def test_own_title_bar_is_off_unless_chosen(tmp_path):
    path = tmp_path / 'config.json'
    assert default_config()['own_title_bar'] is False
    path.write_text(json.dumps({'own_title_bar': True}), encoding='utf-8')
    assert ConfigStore(path).data['own_title_bar'] is True


def test_light_or_dark_choice_is_kept_and_unknown_values_follow_the_system(tmp_path):
    path = tmp_path / 'config.json'
    for saved, loaded in (('dark', 'dark'), ('light', 'light'), ('purple', 'system'), (None, 'system')):
        path.write_text(json.dumps({'color_scheme': saved}), encoding='utf-8')
        assert ConfigStore(path).data['color_scheme'] == loaded

import json
import os
from pathlib import Path

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


def test_app_profile_override_isolates_app_data_without_changing_windows_profile(tmp_path, monkeypatch):
    from tvhplayer.core.config import default_config_dir, default_cache_dir
    from tvhplayer.core.logs import log_dir
    monkeypatch.setenv('TVHPLAYER_PROFILE_DIR', str(tmp_path))
    original = {key: os.environ.get(key) for key in ('APPDATA', 'LOCALAPPDATA', 'USERPROFILE')}
    assert default_config_dir() == tmp_path / 'Roaming/TVHplayer'
    assert default_cache_dir() == tmp_path / 'Local/TVHplayer/Cache'
    assert log_dir() == tmp_path / 'Local/TVHplayer/Logs'
    assert {key: os.environ.get(key) for key in original} == original


def test_old_config_keeps_port_80_for_portless_http_once(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({'servers': [
        {'name': 'proxy', 'url': 'http://tvh.example/tvh'},
        {'name': 'tls', 'url': 'https://tvh.example'},
        {'name': 'box', 'url': 'http://127.0.0.1:9981'},
    ]}), encoding='utf-8')
    store = ConfigStore(path)
    assert [s['url'] for s in store.servers] == [
        'http://tvh.example:80/tvh', 'https://tvh.example', 'http://127.0.0.1:9981',
    ]
    store.save()
    store.servers = [{'name': 'new', 'url': 'http://other.example'}]
    store.save()
    assert ConfigStore(path).servers[0]['url'] == 'http://other.example'


def test_unparsable_old_address_does_not_discard_the_config(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({'volume': 7, 'servers': [{'name': 'x', 'url': 'http://[host]'}]}),
                    encoding='utf-8')
    store = ConfigStore(path)
    assert store.data['volume'] == 7
    assert store.servers[0]['url'] == 'http://[host]'
    assert not (tmp_path / 'tvhplayer.conf.broken').exists()


def test_new_config_does_not_pin_http_ports(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    store.servers = [{'name': 'new', 'url': 'http://other.example'}]
    store.save()
    assert ConfigStore(path).servers[0]['url'] == 'http://other.example'


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

    monkeypatch.setattr(os, 'fsync', full_disk)
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


def test_cast_automatic_and_manual_choices_roundtrip_separately(tmp_path):
    path = tmp_path / 'settings.json'
    store = ConfigStore(path)
    store.data['cast_profiles'] = {'local': 'auto', 'other': 'manual-profile'}
    store.data['cast_auto_profiles'] = {'receiver|local': 'webm-profile'}
    store.save()
    loaded = ConfigStore(path)
    assert loaded.data['cast_profiles'] == {'local': 'auto', 'other': 'manual-profile'}
    assert loaded.data['cast_auto_profiles'] == {'receiver|local': 'webm-profile'}


def test_theme_defaults_to_organic_and_keeps_a_chosen_one(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    assert ConfigStore(tmp_path / 'new.conf').data['ui_theme'] == 'Organic'
    for saved, loaded in ((None, 'Organic'), ('', 'Organic'), (3, 'Organic'), ('Breeze', 'Breeze'),
                          ('TVHplayer', 'TVHplayer')):
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
    assert len(store.data['playlists'][0].pop('state_id')) == 32
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
        'source_type': 'm3u',
        'request_headers': {},
        'health': {},
        'health_totals': {},
        'last_checked': 0.0,
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
    # A config saved before this setting existed gets marking on.
    assert data['mark_dead_channels'] is True
    assert default_config()['hide_dead_channels'] is False
    assert default_config()['mark_dead_channels'] is True


def test_timeshift_size_falls_back_when_unusable(tmp_path):
    path = tmp_path / 'config.json'
    assert default_config()['timeshift_on_disk'] is False
    for raw, expected in ((10, 10), (0, 4), (501, 4), ('8', 4), (True, 4)):
        path.write_text(json.dumps({'timeshift_gb': raw, 'timeshift_on_disk': 1}), encoding='utf-8')
        data = ConfigStore(path).data
        assert data['timeshift_gb'] == expected
        assert data['timeshift_on_disk'] is True


def test_live_resize_stays_unset_until_chosen(tmp_path):
    path = tmp_path / 'config.json'
    assert default_config()['live_resize'] is None
    path.write_text('{}', encoding='utf-8')
    assert ConfigStore(path).data['live_resize'] is None
    path.write_text(json.dumps({'live_resize': True}), encoding='utf-8')
    assert ConfigStore(path).data['live_resize'] is True
    path.write_text(json.dumps({'live_resize': False}), encoding='utf-8')
    assert ConfigStore(path).data['live_resize'] is False
    path.write_text(json.dumps({'live_resize': None}), encoding='utf-8')
    assert ConfigStore(path).data['live_resize'] is None
    path.write_text(json.dumps({'resize_on_release': True}), encoding='utf-8')
    assert 'resize_on_release' not in ConfigStore(path).data


def test_title_bar_is_left_to_the_desktop_until_chosen(tmp_path):
    path = tmp_path / 'config.json'
    assert default_config()['title_bar'] is None
    path.write_text(json.dumps({'title_bar': False}), encoding='utf-8')
    assert ConfigStore(path).data['title_bar'] is False
    path.write_text(json.dumps({'title_bar': True}), encoding='utf-8')
    assert ConfigStore(path).data['title_bar'] is True


def test_earlier_title_bar_switch_carries_over_only_when_on(tmp_path):
    # Every config up to 4.6 held own_title_bar, false unless it was switched
    # on: a false one is the old default, not a choice.
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'own_title_bar': True}), encoding='utf-8')
    data = ConfigStore(path).data
    assert data['title_bar'] is True and 'own_title_bar' not in data
    path.write_text(json.dumps({'own_title_bar': False}), encoding='utf-8')
    data = ConfigStore(path).data
    assert data['title_bar'] is None and 'own_title_bar' not in data
    # Once saved, the choice stays as it is.
    store = ConfigStore(path)
    store.data['title_bar'] = False
    store.save()
    assert ConfigStore(path).data['title_bar'] is False


def test_legacy_player_engine_choice_is_dropped(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'player_engine': 'vlc', 'volume': 40}), encoding='utf-8')
    data = ConfigStore(path).data
    assert 'player_engine' not in data
    assert data['volume'] == 40


def test_light_or_dark_choice_is_kept_and_unknown_values_follow_the_system(tmp_path):
    path = tmp_path / 'config.json'
    for saved, loaded in (('dark', 'dark'), ('light', 'light'), ('purple', 'system'), (None, 'system')):
        path.write_text(json.dumps({'color_scheme': saved}), encoding='utf-8')
        assert ConfigStore(path).data['color_scheme'] == loaded


def _big_playlist(count=50000, **extra):
    return dict({
        'name': 'big', 'location': 'http://a/big.m3u', 'server': 'builtin',
        'muxes': {f'id:{index}': f'{index:032x}' for index in range(count)},
        'health': {'id:1': {'name': 'One', 'status': 'failed', 'scan_result': 2, 'checked': 1.0}},
    }, **extra)


def _record_writes(monkeypatch):
    from tvhplayer.core import config
    written = []
    real = config._write_file

    def record(target, text):
        written.append((Path(target).name, len(text)))
        real(target, text)

    monkeypatch.setattr(config, '_write_file', record)
    return written


def test_a_playlists_channel_map_is_kept_beside_the_settings(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    store.data['playlists'] = [_big_playlist(10)]
    store.save()
    on_disk = json.loads(path.read_text())
    playlist = on_disk['playlists'][0]
    assert 'muxes' not in playlist and 'health' not in playlist
    state = json.loads((tmp_path / 'playlists' / f"{playlist['state_id']}.json").read_text())
    assert state['muxes']['id:3'] == f'{3:032x}'
    assert state['health']['id:1']['status'] == 'failed'

    again = ConfigStore(path).data['playlists'][0]
    assert again['muxes'] == state['muxes'] and again['health'] == state['health']
    assert again['state_id'] == playlist['state_id']


def test_saving_other_settings_does_not_write_a_big_playlist_again(tmp_path, monkeypatch):
    # Every channel change saves the settings. With a big playlist each save
    # wrote its whole channel map, megabytes, on the UI thread.
    path = tmp_path / 'tvhplayer.conf'
    path.write_text(json.dumps({'playlists': [_big_playlist()]}), encoding='utf-8')
    store = ConfigStore(path)
    store.save()
    written = _record_writes(monkeypatch)
    store.data['last_channel'] = {'server': 'builtin', 'key': 'x', 'name': 'X'}
    store.save()
    assert written == [('tvhplayer.conf', written[0][1])]
    assert written[0][1] < 10000

    # Read back from disk, it is not written again either.
    store = ConfigStore(path)
    written.clear()
    store.data['volume'] = 10
    store.save()
    assert [name for name, _size in written] == ['tvhplayer.conf']


def test_a_changed_channel_map_is_written_and_a_removed_playlist_forgotten(tmp_path, monkeypatch):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    store.data['playlists'] = [_big_playlist(10)]
    store.save()
    state_id = store.data['playlists'][0]['state_id']
    unknown = tmp_path / 'playlists' / ('f' * 32 + '.json')
    unknown.write_text('{}')
    written = _record_writes(monkeypatch)
    store.data['playlists'] = [dict(store.data['playlists'][0], muxes={'id:new': 'n' * 32})]
    store.save()
    assert [name for name, _size in written] == [f'{state_id}.json', 'tvhplayer.conf']
    assert ConfigStore(path).data['playlists'][0]['muxes'] == {'id:new': 'n' * 32}

    store.data['playlists'] = []
    store.save()
    assert not (tmp_path / 'playlists' / f'{state_id}.json').exists()
    # A file this app did not write, or no longer knows, is left alone.
    assert unknown.exists()


def test_background_saves_are_read_back_in_order(tmp_path):
    path = tmp_path / 'tvhplayer.conf'
    store = ConfigStore(path)
    for volume in range(20):
        store.data['volume'] = volume
        store.data['playlists'] = [_big_playlist(volume + 1, state_id='a' * 32)]
        store.save(background=True)
    data = ConfigStore(path).data
    assert data['volume'] == 19
    assert len(data['playlists'][0]['muxes']) == 20

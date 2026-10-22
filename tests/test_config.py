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

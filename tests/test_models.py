from tvhplayer.core.models import Channel, DvrEntry, ServerConfig


def test_server_config_defaults_to_http():
    cfg = ServerConfig.from_dict({'name': 'box', 'url': 'http://127.0.0.1:9981'})
    assert cfg.protocol == 'http'
    assert cfg.htsp_port == 9982
    assert cfg.to_dict()['protocol'] == 'http'


def test_channel_from_htsp_and_http():
    http_ch = Channel.from_raw({'uuid': 'abc', 'name': 'BBC One', 'number': 1})
    assert http_ch.uuid == 'abc'
    assert http_ch.htsp_id is None

    htsp_ch = Channel.from_raw(
        {'channelId': 42, 'channelIdStr': 'deadbeef', 'channelName': 'BBC Two', 'channelNumber': 2}
    )
    assert htsp_ch.htsp_id == 42
    assert htsp_ch.uuid == 'deadbeef'
    assert htsp_ch.name == 'BBC Two'


def test_dvr_category_maps_running_and_failed():
    running = DvrEntry(uuid='1', title='t', channel_name='c', start=0, duration=1, status='Running')
    assert running.category() == 'recording'
    htsp_rec = DvrEntry(uuid='1', title='t', channel_name='c', start=0, duration=1, status='Running', sched_status='recording')
    assert htsp_rec.category() == 'recording'
    failed = DvrEntry(uuid='1', title='t', channel_name='c', start=0, duration=1, status='Failed', errors=1)
    assert failed.category() == 'failed'

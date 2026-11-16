from tvhplayer.core.models import Channel, DvrEntry, ServerConfig, recordings_to_stop


def test_new_server_defaults_to_htsp_and_old_saved_server_keeps_http():
    assert ServerConfig(name='box', url='http://127.0.0.1:9981').protocol == 'htsp'
    cfg = ServerConfig.from_dict({'name': 'box', 'url': 'http://127.0.0.1:9981'})
    assert cfg.protocol == 'http'
    assert cfg.htsp_port == 9982
    assert cfg.to_dict()['protocol'] == 'http'


def test_channel_from_htsp_and_http():
    http_ch = Channel.from_raw({
        'uuid': 'abc',
        'name': 'BBC One',
        'number': 1,
        'icon': 'imagecache/9',
        'tags': ['fav'],
        'enabled': 0,
    })
    assert http_ch.uuid == 'abc'
    assert http_ch.htsp_id is None
    assert http_ch.icon == 'imagecache/9'
    assert http_ch.tag_ids == ['fav']
    assert http_ch.enabled is False
    assert http_ch.to_raw()['icon'] == 'imagecache/9'

    htsp_ch = Channel.from_raw({
        'channelId': 42,
        'channelIdStr': 'deadbeef',
        'channelName': 'BBC Two',
        'channelNumber': 2,
        'channelNumberMinor': 1,
        'channelIcon': 'imagecache/2',
        'tags': [7],
    })
    assert htsp_ch.htsp_id == 42
    assert htsp_ch.uuid == 'deadbeef'
    assert htsp_ch.name == 'BBC Two'
    assert htsp_ch.number_minor == 1
    assert htsp_ch.icon == 'imagecache/2'
    assert htsp_ch.tag_ids == ['7']
    assert htsp_ch.enabled is True


def test_dvr_category_maps_running_and_failed():
    running = DvrEntry(uuid='1', title='t', channel_name='c', start=0, duration=1, status='Running')
    assert running.category() == 'recording'
    htsp_rec = DvrEntry(uuid='1', title='t', channel_name='c', start=0, duration=1, status='Running', sched_status='recording')
    assert htsp_rec.category() == 'recording'
    waiting = DvrEntry(
        uuid='1', title='t', channel_name='c', start=0, duration=1,
        status='Waiting for stream', sched_status='recording',
    )
    assert waiting.category() == 'recording'
    failed = DvrEntry(uuid='1', title='t', channel_name='c', start=0, duration=1, status='Failed', errors=1)
    assert failed.category() == 'failed'
    scheduled = DvrEntry(
        uuid='1', title='t', channel_name='c', start=0, duration=1,
        status='Scheduled for recording', sched_status='scheduled',
    )
    assert scheduled.category() == 'upcoming'


def _running(uuid, name, channel_key):
    return DvrEntry(
        uuid=uuid,
        title='Instant Recording',
        channel_name=name,
        start=0,
        duration=60,
        status='Running',
        sched_status='recording',
        raw={'channel': channel_key, 'channelname': name},
    )


def test_matches_channel_by_htsp_id_or_http_uuid():
    htsp = _running('1', 'IRINN', 42)
    assert htsp.matches_channel(Channel(uuid='42', name='IRINN', htsp_id=42))
    assert not htsp.matches_channel(Channel(uuid='7', name='IRINN', htsp_id=7))

    http = _running('2', 'BBC', 'abc')
    assert http.matches_channel(Channel(uuid='abc', name='BBC'))
    assert not http.matches_channel(Channel(uuid='def', name='BBC'))


def test_recordings_to_stop_keeps_other_jobs_when_several_are_running():
    first = _running('1', 'IRINN', 'a')
    second = _running('2', 'BBC', 'b')
    assert recordings_to_stop([first]) == [first]
    assert recordings_to_stop([first, second], Channel(uuid='b', name='BBC')) == [second]
    assert recordings_to_stop([first, second], None) == []
    assert recordings_to_stop([first, second], Channel(uuid='c', name='Other')) == []


def test_http_channel_number_with_a_subchannel():
    # api/channel/grid sends a number with a minor part as the text "2.1",
    # and a plain number as an integer.
    ch = Channel.from_raw({'uuid': 'u', 'name': 'KTVU', 'number': '2.1'})
    assert (ch.number, ch.number_minor) == (2, 1)
    ch = Channel.from_raw({'uuid': 'u', 'name': 'KTVU', 'number': '2.10'})
    assert (ch.number, ch.number_minor) == (2, 10)
    ch = Channel.from_raw({'uuid': 'u', 'name': 'BBC', 'number': 7})
    assert (ch.number, ch.number_minor) == (7, None)


def test_channels_sort_by_major_then_minor_then_name():
    from tvhplayer.core.backend import channel_sort_key

    channels = [
        Channel(uuid='a', name='Zeta', number=2, number_minor=2),
        Channel(uuid='b', name='Alpha', number=2, number_minor=1),
        Channel(uuid='c', name='Main', number=2),
        Channel(uuid='d', name='Beta', number=2, number_minor=10),
        Channel(uuid='e', name='None'),
        Channel(uuid='f', name='Ten', number=10),
    ]
    assert [c.name for c in sorted(channels, key=channel_sort_key)] == [
        'Main', 'Alpha', 'Zeta', 'Beta', 'Ten', 'None']

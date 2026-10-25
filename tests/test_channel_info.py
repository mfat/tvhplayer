import json

from tvhplayer.core.channel_info import (
    CHANNEL_LIST_DEFAULTS,
    KIND_HD,
    KIND_RADIO,
    KIND_SD,
    KIND_UHD,
    channel_icon_reference,
    channel_kinds,
    channel_list_options,
    channels_in_tag,
    match_now_next,
    progress,
    recording_channel_keys,
)
from tvhplayer.core.models import Channel, ChannelTag, DvrEntry, EpgEvent

from test_guide_api import _htsp, _http


def _event(event_id, channel_uuid, start, stop, title, next_id=None):
    return EpgEvent(
        start=start,
        stop=stop,
        title=title,
        channel_uuid=channel_uuid,
        event_id=event_id,
        next_event_id=next_id,
    )


def test_options_fill_missing_keys_and_ignore_bad_values():
    assert channel_list_options(None) == CHANNEL_LIST_DEFAULTS
    options = channel_list_options({
        'columns': {'next': True, 'number': 0, 'bogus': True},
        'logos': False,
        'tag': 7,
        'order': ['status', 'name', 'status', 'nonsense'],
    })
    assert options['order'] == ['status', 'name', 'number', 'now', 'next', 'type']
    assert options['columns']['next'] is True
    assert options['columns']['number'] is False
    assert 'bogus' not in options['columns']
    assert options['logos'] is False
    assert options['tag'] == ''
    # The defaults are copied, not shared.
    options['columns']['now'] = False
    options['order'].clear()
    assert CHANNEL_LIST_DEFAULTS['columns']['now'] is True
    assert CHANNEL_LIST_DEFAULTS['order']


def test_icon_prefers_the_imagecache_url_and_skips_server_files():
    channel = Channel.from_raw({
        'uuid': 'a', 'name': 'A', 'icon': 'file:///srv/a.png', 'icon_public_url': 'imagecache/4',
    })
    assert channel_icon_reference(channel) == 'imagecache/4'
    assert channel_icon_reference(Channel.from_raw({'uuid': 'b', 'name': 'B', 'icon': 'file:///b.png'})) == ''
    htsp = Channel.from_raw({'channelId': 3, 'channelName': 'C', 'channelIcon': 'imagecache/9'})
    assert channel_icon_reference(htsp) == 'imagecache/9'


def test_now_next_from_the_grid_and_from_htsp_event_ids():
    news = Channel(uuid='news', name='News')
    sport = Channel.from_raw({'channelId': 2, 'channelIdStr': 'sport', 'channelName': 'Sport',
                              'eventId': 20, 'nextEventId': 21})
    quiet = Channel(uuid='quiet', name='Quiet')
    events = [
        _event(10, 'news', 100, 200, 'Headlines', next_id=11),
        _event(11, 'news', 200, 300, 'Weather'),
        _event(20, 'sport', 90, 210, 'Match'),
        _event(21, 'sport', 210, 400, 'Highlights'),
    ]
    result = match_now_next([news, sport, quiet], events)
    assert result['news'].now.title == 'Headlines'
    assert result['news'].next.title == 'Weather'
    assert result['sport'].now.title == 'Match'
    assert result['sport'].next.title == 'Highlights'
    assert 'quiet' not in result


def test_progress_is_clamped_and_none_without_times():
    event = _event(1, 'a', 100, 200, 'A')
    assert progress(event, 150) == 0.5
    assert progress(event, 50) == 0.0
    assert progress(event, 500) == 1.0
    assert progress(_event(2, 'a', 0, 0, 'B'), 10) is None
    assert progress(None, 10) is None


def test_kinds_come_from_htsp_services_service_rows_then_tags():
    htsp = Channel.from_raw({'channelId': 1, 'channelName': 'One', 'services': [
        {'name': 'a', 'type': 'SDTV'},
        {'name': 'b', 'type': 'HDTV', 'caid': 0x0500, 'providername': 'Sat'},
    ]})
    http = Channel(uuid='two', name='Two')
    radio = Channel(uuid='three', name='Three')
    tagged = Channel(uuid='four', name='Four', tag_ids=['uhd-tag'])
    plain = Channel(uuid='five', name='Five')
    services = [
        {'channel': ['two'], 'dvb_servicetype': 0x1f, 'encrypted': True, 'provider': 'Cable'},
        {'channel': ['three'], 'dvb_servicetype': 2, 'encrypted': False},
    ]
    tags = [ChannelTag(uuid='uhd-tag', name='UHDTV')]
    kinds = channel_kinds([htsp, http, radio, tagged, plain], services, tags)
    assert (kinds['1'].kind, kinds['1'].encrypted, kinds['1'].provider) == (KIND_HD, True, 'Sat')
    assert (kinds['two'].kind, kinds['two'].encrypted) == (KIND_UHD, True)
    assert kinds['two'].label() == 'UHD, Encrypted'
    assert kinds['three'].kind == KIND_RADIO
    assert kinds['four'].kind == KIND_UHD
    assert 'five' not in kinds
    assert channel_kinds([Channel(uuid='x', name='X')], [{'channel': ['x'], 'dvb_servicetype': 1}])['x'].kind == KIND_SD


def test_recording_keys_only_count_running_entries():
    news = Channel(uuid='news', name='News')
    sport = Channel(uuid='sport', name='Sport')
    entries = [
        DvrEntry(uuid='r', title='T', channel_name='News', start=0, duration=60,
                 sched_status='recording', raw={'channel': 'news'}),
        DvrEntry(uuid='s', title='T', channel_name='Sport', start=0, duration=60,
                 sched_status='scheduled', raw={'channel': 'sport'}),
    ]
    assert recording_channel_keys([news, sport], entries) == {'news'}
    assert recording_channel_keys([news, sport], []) == set()


def test_tag_filter_matches_http_uuids_and_htsp_members():
    a = Channel(uuid='a', name='A', tag_ids=['news'])
    b = Channel(uuid='b', name='B', htsp_id=5)
    c = Channel(uuid='c', name='C')
    assert channels_in_tag([a, b, c], None) == [a, b, c]
    assert channels_in_tag([a, b, c], ChannelTag(uuid='news')) == [a]
    assert channels_in_tag([a, b, c], ChannelTag(uuid='9', htsp_id=9, member_ids=['5'])) == [b]


def test_http_loads_events_and_services_with_documented_parameters():
    backend = _http()
    backend._session.queue.append({'entries': [{'eventId': 11, 'title': 'Weather', 'start': 1, 'stop': 2}]})
    events = backend.load_events([11, 12])
    method, url, kwargs = backend._session.calls[-1]
    assert (method, url) == ('POST', 'http://127.0.0.1:9981/api/epg/events/load')
    assert json.loads(kwargs['data']['eventId']) == [11, 12]
    assert [event.title for event in events] == ['Weather']
    assert backend.load_events([]) == []

    backend._session.queue.append({'entries': [{'channel': ['a'], 'dvb_servicetype': 1}]})
    assert backend.list_channel_services() == [{'channel': ['a'], 'dvb_servicetype': 1}]
    params = backend._session.calls[-1][2]['params']
    assert backend._session.calls[-1][1].endswith('/api/mpegts/service/grid')
    assert params['hidemode'] == 'none'
    assert set(params['list'].split(',')) >= {'channel', 'dvb_servicetype', 'encrypted'}


def test_http_now_next_reads_now_then_loads_next_events():
    backend = _http()
    backend._session.queue.append({'entries': [
        {'eventId': 10, 'channelUuid': 'news', 'start': 100, 'stop': 200, 'title': 'Headlines', 'nextEventId': 11},
    ]})
    backend._session.queue.append({'entries': [
        {'eventId': 11, 'channelUuid': 'news', 'start': 200, 'stop': 300, 'title': 'Weather'},
    ]})
    result = backend.get_now_next([Channel(uuid='news', name='News')])
    assert backend._session.calls[0][2]['params']['mode'] == 'now'
    assert json.loads(backend._session.calls[1][2]['data']['eventId']) == [11]
    assert (result['news'].now.title, result['news'].next.title) == ('Headlines', 'Weather')


def test_htsp_now_next_loads_the_ids_sent_with_each_channel():
    backend, conn = _htsp()
    conn.replies['api'] = {'response': {'entries': [
        {'eventId': 20, 'start': 1, 'stop': 2, 'title': 'Match'},
        {'eventId': 21, 'start': 2, 'stop': 3, 'title': 'Highlights'},
    ]}}
    channel = Channel.from_raw({'channelId': 2, 'channelName': 'Sport', 'eventId': 20, 'nextEventId': 21})
    result = backend.get_now_next([channel])
    assert conn.calls[-1] == ('api', {'path': 'epg/events/load', 'args': {'eventId': [20, 21]}})
    assert (result['2'].now.title, result['2'].next.title) == ('Match', 'Highlights')
    assert backend.list_channel_services() == []

import json

import pytest

from tvhplayer.core.errors import TvhError
from tvhplayer.core.guide import epg_htsp_transport
from tvhplayer.core.htsp_backend import HtspBackend
from tvhplayer.core.http_backend import HttpBackend
from tvhplayer.core.models import Channel, ChannelTag, EpgQuery, ServerConfig


class _Response:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.text = json.dumps(self._payload)
        self.content = self.text.encode('utf-8')


class _Session:
    def __init__(self):
        self.calls = []
        self.queue = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        payload = self.queue.pop(0) if self.queue else {}
        return _Response(payload)

    def close(self):
        return None


def _http():
    backend = HttpBackend(ServerConfig(name='box', url='http://127.0.0.1:9981', username='u', password='p'))
    backend._session.close()
    backend._session = _Session()
    return backend


class _Conn:
    def __init__(self):
        self.calls = []
        self.replies = {}
        self._sock = object()
        self.webroot = ''

    def rpc(self, method, args=None, on_async=None, timeout=None):
        self.calls.append((method, args))
        return self.replies.get(method, {'success': 1})


def _htsp():
    backend = HtspBackend(ServerConfig(
        name='box',
        url='http://127.0.0.1:9981',
        username='u',
        password='p',
        protocol='htsp',
    ))
    conn = _Conn()
    backend._conn = conn
    backend._ready = True
    return backend, conn


def _params(backend):
    return backend._session.calls[-1][2].get('params') or {}


def test_http_guide_grid_uses_documented_parameter_names():
    backend = _http()
    backend._session.queue.append({'entries': [{
        'eventId': 5,
        'start': 100,
        'stop': 200,
        'title': {'eng': 'News'},
        'subtitle': 'Evening',
        'summary': 'Headlines',
        'description': 'The full bulletin',
        'channelUuid': 'chan',
        'channelName': 'BBC',
        'channelNumber': '3',
        'genre': [48],
        'image': 'imagecache/38',
        'imagePoster': 'imagecache/39',
        'imageBackdrop': 'imagecache/40',
        'imageStill': 'imagecache/41',
        'serieslinkUri': 'crid://series',
        'episodeUri': 'crid://episode',
        'nextEventId': 6,
        'dvrUuid': 'dvr',
        'dvrState': 'scheduled',
        'widescreen': 1,
        'subtitled': 1,
        'hd': 1,
        'ageRating': 9,
        'ratingLabel': 'PG',
        'ratingLabelIcon': 'imagecache/37',
    }]})
    event = backend.query_epg(EpgQuery(
        title='News',
        fulltext=True,
        channel=Channel(uuid='chan', name='BBC'),
        channel_tag=ChannelTag(uuid='fav', name='Favourites'),
        content_type=16,
        duration_min=60,
        duration_max=7200,
        mode='now',
        limit=10,
        offset=20,
        lang='eng',
    ))[0]
    assert event.title == 'News'
    assert event.subtitle == 'Evening'
    assert event.summary == 'Headlines'
    assert event.description == 'The full bulletin'
    assert event.channel_number == 3
    assert event.genre == [48]
    assert event.image_still == 'imagecache/41'
    assert event.serieslink_uri == 'crid://series'
    assert event.next_event_id == 6
    assert event.dvr_state == 'scheduled'
    assert event.hd is True
    assert event.age_rating == 9
    assert event.rating_label == 'PG'
    params = _params(backend)
    assert params['title'] == 'News'
    assert params['fulltext'] == 1
    assert params['channel'] == 'chan'
    assert params['channelTag'] == 'fav'
    assert params['contentType'] == 16
    assert params['durationMin'] == 60
    assert params['durationMax'] == 7200
    assert params['mode'] == 'now'
    assert params['limit'] == 10
    assert params['start'] == 20
    assert params['lang'] == 'eng'
    assert backend._session.calls[-1][1].endswith('/api/epg/events/grid')

    backend._session.queue.append({'entries': []})
    assert backend.get_epg(Channel(uuid='chan', name='BBC'), limit=24) == []
    assert _params(backend)['limit'] == 24
    assert 'title' not in _params(backend)

    with pytest.raises(TvhError):
        backend.query_epg(EpgQuery(mode='later'))


def test_http_event_lists_profiles_images_and_status():
    backend = _http()
    backend._session.queue.append({'entries': []})
    with pytest.raises(TvhError):
        backend.get_event(5)
    assert backend._session.calls[-1][1].endswith('/api/epg/events/load')

    backend._session.queue.append({'entries': [{'eventId': 8, 'title': 'Next', 'start': 1, 'stop': 2}]})
    assert backend.list_related_events(5)[0].event_id == 8
    assert 'epg/events/related' in backend._session.calls[-1][1]

    backend._session.queue.append({'entries': []})
    assert backend.list_alternative_events(5) == []
    assert 'epg/events/alternative' in backend._session.calls[-1][1]

    backend._session.queue.append({'entries': [{'key': 16, 'val': 'Movie / Drama'}, {'key': 0, 'val': ''}]})
    genres = backend.list_content_types()
    assert genres[0].key == 16
    assert genres[0].name == 'Movie / Drama'
    assert genres[1].name == ''

    backend._session.queue.append({'entries': [{'key': 'uuid1', 'val': 'pass'}]})
    profile = backend.list_profiles()[0]
    assert profile.uuid == 'uuid1'
    assert profile.name == 'pass'
    assert backend._session.calls[-1][1].endswith('/api/profile/list')

    backend._session.queue.append({'entries': [
        {'uuid': 'b', 'name': 'Drama', 'index': 2, 'icon': 'imagecache/2'},
        {'uuid': 'a', 'name': 'All', 'index': 0},
    ]})
    tags = backend.list_channel_tags()
    assert [tag.name for tag in tags] == ['All', 'Drama']
    assert tags[1].icon == 'imagecache/2'

    url = backend.stream_url(Channel(uuid='chan', name='BBC'), profile='pass')
    assert url == 'http://u:p@127.0.0.1:9981/stream/channel/chan?profile=pass'
    assert backend.image_url('imagecache/38') == 'http://u:p@127.0.0.1:9981/imagecache/38'
    assert backend.image_url('https://cdn.example/a.png') == 'https://cdn.example/a.png'
    assert backend.image_url('') == ''

    backend._session.queue.append({'entries': [{
        'input': 'Tuner',
        'signal': -75649,
        'signal_scale': 2,
        'snr': 14149,
        'snr_scale': 2,
        'stream': '10773H',
        'weight': 100,
    }]})
    tuner = backend.get_inputs()[0]
    assert tuner.name == 'Tuner'
    assert tuner.signal == -75649
    assert tuner.get('input') == 'Tuner'
    assert tuner.get('signal_scale', 0) == 2
    assert tuner.get('missing', 'N/A') == 'N/A'

    backend._session.queue.append({'entries': [{
        'id': 4,
        'peer': '10.0.0.8',
        'user': 'u',
        'started': 50,
        'type': 'HTSP',
    }]})
    conn = backend.get_connections()[0]
    assert conn.peer == '10.0.0.8'
    assert conn.get('user') == 'u'
    assert conn.kind == 'HTSP'

    backend._session.queue.append({'entries': [{
        'id': 7,
        'channel': {'name': 'BBC'},
        'username': 'u',
        'start': 10,
        'state': 'Running',
    }]})
    sub = backend.get_subscriptions()[0]
    assert sub.channel == 'BBC'
    assert sub.get('channel') == {'name': 'BBC'}
    assert sub.get('state', 'Unknown') == 'Running'

    backend._session.queue.append({
        'current_time': 10,
        'next_activity': 20,
        'activities': {'dvr': 30, 'ota_grabber': 0},
        'subscription_count': 1,
        'connection_count': 2,
    })
    activity = backend.get_activity()
    assert activity.next_activity == 20
    assert activity.activities == {'dvr': 30, 'ota_grabber': 0}
    assert activity.subscription_count == 1
    assert activity.get('connection_count') == 2
    assert backend._session.calls[-1][1].endswith('/api/status/activity')


def test_htsp_transport_choice():
    channel = Channel(uuid='c', name='BBC', htsp_id=4)
    assert epg_htsp_transport(EpgQuery(channel=channel, limit=24)) == 'getEvents'
    assert epg_htsp_transport(EpgQuery(title='News', channel=channel)) == 'epgQuery'
    assert epg_htsp_transport(EpgQuery(title='News', fulltext=True, channel=channel)) == 'http'
    assert epg_htsp_transport(EpgQuery(title='News', mode='now')) == 'http'
    assert epg_htsp_transport(EpgQuery(channel=channel, offset=10)) == 'http'
    assert epg_htsp_transport(EpgQuery(
        channel_tag=ChannelTag(uuid='fav', name='Fav', htsp_id=3),
    )) == 'http'
    assert epg_htsp_transport(EpgQuery(
        title='News',
        channel=Channel(uuid='c', name='BBC'),
    )) == 'http'


def test_htsp_tags_guide_profiles_and_images():
    backend, conn = _htsp()
    backend._on_async({
        'method': 'tagAdd',
        'tagId': 3,
        'tagIdStr': 'fav',
        'tagName': 'Fav',
        'tagIndex': 2,
        'tagIcon': 'imagecache/1',
        'members': [4],
    })
    backend._on_async({'method': 'tagUpdate', 'tagId': 3, 'tagName': 'Favourites'})
    tag = backend.list_channel_tags()[0]
    assert tag.name == 'Favourites'
    assert tag.uuid == 'fav'
    assert tag.htsp_id == 3
    assert tag.icon == 'imagecache/1'
    assert tag.member_ids == ['4']
    backend._on_async({'method': 'tagDelete', 'tagId': 3})
    assert backend.list_channel_tags() == []

    backend._on_async({
        'method': 'channelAdd',
        'channelId': 4,
        'channelIdStr': 'c',
        'channelName': 'BBC',
        'channelNumber': 1,
        'channelNumberMinor': 2,
        'channelIcon': 'imagecache/9',
        'tags': [3],
    })
    backend._on_async({'method': 'channelUpdate', 'channelId': 4, 'channelIcon': 'imagecache/10'})
    channel = backend.get_channels()[0]
    assert channel.name == 'BBC'
    assert channel.icon == 'imagecache/10'
    assert channel.number_minor == 2
    assert channel.tag_ids == ['3']
    assert channel.number == 1

    conn.replies['getEvents'] = {'events': [
        {'eventId': 1, 'start': 1, 'stop': 2, 'title': 'Now', 'contentType': 16, 'summary': 'Live'},
        {'eventId': 2, 'start': 2, 'stop': 3, 'title': 'Next'},
    ]}
    events = backend.get_epg(channel, limit=1)
    assert len(events) == 1
    assert events[0].title == 'Now'
    assert events[0].genre == [16]
    assert events[0].description == 'Live'
    assert events[0].channel_uuid == 'c'
    assert conn.calls[-1][0] == 'getEvents'
    assert conn.calls[-1][1]['channelId'] == 4
    assert conn.calls[-1][1]['maxTime'] > events[0].start

    conn.replies['epgQuery'] = {'events': [{
        'eventId': 9,
        'title': 'News',
        'start': 5,
        'stop': 6,
    }]}
    found = backend.query_epg(EpgQuery(
        title='News',
        channel=channel,
        channel_tag=ChannelTag(uuid='fav', name='Favourites', htsp_id=3),
        content_type=16,
        duration_min=30,
        duration_max=90,
        lang='eng',
        limit=5,
    ))
    assert found[0].event_id == 9
    method, args = conn.calls[-1]
    assert method == 'epgQuery'
    assert args == {
        'query': 'News',
        'full': 1,
        'channelId': 4,
        'tagId': 3,
        'contentType': 16,
        'minduration': 30,
        'maxduration': 90,
        'language': 'eng',
    }

    conn.replies['api'] = {'response': {'entries': []}}
    assert backend.query_epg(EpgQuery(title='News', fulltext=True, channel=channel)) == []
    assert conn.calls[-1][0] == 'api'
    assert conn.calls[-1][1]['path'] == 'epg/events/grid'
    assert conn.calls[-1][1]['args']['fulltext'] == 1
    assert conn.calls[-1][1]['args']['title'] == 'News'
    assert conn.calls[-1][1]['args']['channel'] == 'c'

    conn.replies['getEvent'] = {'eventId': 9, 'title': 'News', 'start': 5, 'stop': 6}
    assert backend.get_event(9).title == 'News'
    assert conn.calls[-1] == ('getEvent', {'eventId': 9})

    conn.replies['getEvent'] = {'success': 1}
    with pytest.raises(TvhError):
        backend.get_event(9)

    conn.replies['api'] = {'response': {'entries': [{'eventId': 2, 'title': 'Later', 'start': 7, 'stop': 8}]}}
    assert backend.list_related_events(9)[0].title == 'Later'
    assert conn.calls[-1][1]['path'] == 'epg/events/related'
    assert backend.list_alternative_events(9)[0].title == 'Later'
    assert conn.calls[-1][1]['path'] == 'epg/events/alternative'
    assert conn.calls[-1][1]['args'] == {'eventId': 9}

    conn.replies['api'] = {'response': {'entries': [{'key': 16, 'val': 'Movie / Drama'}]}}
    assert backend.list_content_types()[0].name == 'Movie / Drama'
    assert conn.calls[-1][1]['path'] == 'epg/content_type/list'

    conn.replies['getProfiles'] = {'profiles': [{'uuid': 'p', 'name': 'pass', 'comment': 'ts'}]}
    assert backend.list_profiles()[0].comment == 'ts'
    assert conn.calls[-1][0] == 'getProfiles'

    assert backend.stream_url(channel, profile='pass') == (
        'http://u:p@127.0.0.1:9981/stream/channelid/4?profile=pass'
    )
    conn.webroot = '/tvh'
    assert backend.image_url('imagecache/38') == 'http://u:p@127.0.0.1:9981/tvh/imagecache/38'
    assert backend.image_url('https://cdn.example/a.png') == 'https://cdn.example/a.png'

    rooted = HtspBackend(ServerConfig(
        name='box',
        url='http://127.0.0.1:9981/tvh',
        username='u',
        password='p',
        protocol='htsp',
    ))
    rooted._conn = conn
    rooted._ready = True
    assert rooted.image_url('imagecache/38') == 'http://u:p@127.0.0.1:9981/tvh/imagecache/38'

    conn.replies['api'] = {'response': {
        'current_time': 10,
        'next_activity': 20,
        'activities': {'dvr': 30},
        'subscription_count': 1,
        'connection_count': 2,
    }}
    activity = backend.get_activity()
    assert activity.activities['dvr'] == 30
    assert activity.get('subscription_count') == 1
    assert conn.calls[-1][1]['path'] == 'status/activity'

import json
from datetime import datetime

import pytest

from tvhplayer.core.backend import TvhBackend
from tvhplayer.core.dvr import (
    clock_to_minutes,
    instant_recording_title,
    minutes_to_clock,
    weekdays_from_mask,
)
from tvhplayer.core.errors import TvhError
from tvhplayer.core.htsp_backend import HtspBackend
from tvhplayer.core.http_backend import HttpBackend
from tvhplayer.core.models import (
    AutorecEntry,
    AutorecSpec,
    Channel,
    DvrEntry,
    DvrEntryUpdate,
    ServerConfig,
    TimerecSpec,
)


def test_instant_recording_title_uses_channel_and_start_time():
    when = datetime(2026, 10, 23, 14, 53, 7)
    assert instant_recording_title('BBC One', when) == 'BBC One 2026-10-23 14:53:07'
    assert instant_recording_title('  ', when) == 'Unknown Channel 2026-10-23 14:53:07'


def test_time_and_weekday_conversions():
    assert minutes_to_clock(0) == '00:00'
    assert minutes_to_clock(19 * 60 + 30) == '19:30'
    assert clock_to_minutes('19:30') == 19 * 60 + 30
    assert clock_to_minutes('Any') is None
    assert weekdays_from_mask(0x07) == [1, 2, 3]
    with pytest.raises(TvhError):
        minutes_to_clock(1440)
    with pytest.raises(TvhError):
        weekdays_from_mask(0x80)


def test_http_json_accepts_raw_control_characters():
    backend = _http()

    class Loose:
        status_code = 200
        content = b'{"disp_title":"Line\nbreak"}'
        text = '{"disp_title":"Line\nbreak"}'

    backend._session.request = lambda *args, **kwargs: Loose()
    assert backend._request('GET', 'api/dvr/entry/grid')['disp_title'] == 'Line\nbreak'


def test_every_backend_method_is_documented_and_implemented():
    for name, value in vars(TvhBackend).items():
        if not getattr(value, '__isabstractmethod__', False):
            continue
        assert (value.__doc__ or '').strip()
        for cls in (HttpBackend, HtspBackend):
            assert not getattr(getattr(cls, name), '__isabstractmethod__', False)


class _Response:
    def __init__(self, payload=None, status=200, headers=None, content=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = {} if payload is None else payload
        if content is None:
            self.text = json.dumps(self._payload)
            self.content = self.text.encode('utf-8')
        else:
            self.content = content
            self.text = content.decode('utf-8', 'replace') if content else ''

    def json(self):
        return self._payload


class _Session:
    def __init__(self):
        self.calls = []
        self.queue = []
        self.body = b'abcd'
        self.head_status = 200

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        payload = self.queue.pop(0) if self.queue else {}
        return _Response(payload)

    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        return _Response(status=206, content=self.body)

    def head(self, url, **kwargs):
        self.calls.append(('HEAD', url, kwargs))
        return _Response(status=self.head_status, headers={'Content-Length': '10'}, content=b'')

    def close(self):
        return None


def _http():
    backend = HttpBackend(ServerConfig(name='box', url='http://127.0.0.1:9981', username='u', password='p'))
    backend._session.close()
    backend._session = _Session()
    return backend


def test_http_grid_reads_every_page(monkeypatch):
    import tvhplayer.core.dvr as dvr

    monkeypatch.setattr(dvr, 'GRID_LIMIT', 2)
    backend = _http()
    rows = [{'uuid': str(n), 'name': f'C{n}', 'number': n + 1} for n in range(5)]
    backend._session.queue = [
        {'total': 5, 'entries': rows[0:2]},
        {'total': 5, 'entries': rows[2:4]},
        {'total': 5, 'entries': rows[4:5]},
    ]
    assert [channel.name for channel in backend.get_channels()] == ['C0', 'C1', 'C2', 'C3', 'C4']
    pages = [(call[2]['params']['start'], call[2]['params']['limit']) for call in backend._session.calls]
    assert pages == [(0, 2), (2, 2), (4, 2)]


def test_grid_stops_without_total_or_with_own_limit(monkeypatch):
    import tvhplayer.core.dvr as dvr

    monkeypatch.setattr(dvr, 'GRID_LIMIT', 2)
    calls = []

    def fetch(params):
        calls.append(params)
        return {'entries': [{}, {}]}

    assert len(dvr.grid_rows(fetch)) == 2
    assert len(dvr.grid_rows(fetch, {'limit': 7})) == 2
    assert calls == [{'start': 0, 'limit': 2}, {'limit': 7}]


def _entry():
    return DvrEntry(
        uuid='abc',
        title='News',
        channel_name='BBC',
        start=10,
        duration=60,
        status='Running',
        sched_status='recording',
        htsp_id=7,
        raw={'url': 'dvrfile/abc'},
    )


def _posted(backend):
    method, url, kwargs = backend._session.calls[-1]
    return method, url, kwargs.get('data') or {}


def test_http_entry_actions_use_documented_paths():
    backend = _http()
    entry = _entry()
    backend.cancel_dvr_entry(entry)
    method, url, data = _posted(backend)
    assert method == 'POST'
    assert url.endswith('/api/dvr/entry/cancel')
    assert data == {'uuid': 'abc'}

    backend.remove_dvr_entry(entry)
    assert _posted(backend)[1].endswith('/api/dvr/entry/remove')
    backend.delete_dvr_entry(entry)
    assert _posted(backend)[1].endswith('/api/idnode/delete')
    backend.stop_dvr_entry(entry)
    assert _posted(backend)[1].endswith('/api/dvr/entry/stop')
    backend.set_dvr_rerecord(entry, 'toggle')
    assert _posted(backend)[1].endswith('/api/dvr/entry/rerecord/toggle')
    backend.set_dvr_prevrec(entry, 'set')
    assert _posted(backend)[1].endswith('/api/dvr/entry/prevrec/set')
    assert _posted(backend)[2] == {'uuid': 'abc'}
    backend.move_dvr_entry(entry, 'failed')
    assert _posted(backend)[1].endswith('/api/dvr/entry/move/failed')
    backend.notify_dvr_file_moved('/old.ts', '/new.ts')
    assert _posted(backend)[2] == {'src': '/old.ts', 'dst': '/new.ts'}

    with pytest.raises(TvhError):
        backend.set_dvr_rerecord(entry, 'drop')
    with pytest.raises(TvhError):
        backend.notify_dvr_file_moved('', '/new.ts')
    with pytest.raises(TvhError):
        backend.get_dvr_cutpoints(entry)


def test_http_update_and_create_payloads():
    backend = _http()
    entry = _entry()
    backend.update_dvr_entry(
        entry,
        DvrEntryUpdate(
            title='Updated',
            priority=2,
            enabled=False,
            channel=Channel(uuid='chan', name='BBC'),
        ),
    )
    node = json.loads(_posted(backend)[2]['node'])
    assert node['uuid'] == 'abc'
    assert node['title'] == {'eng': 'Updated'}
    assert node['pri'] == 2
    assert node['enabled'] is False
    assert node['channel'] == 'chan'

    with pytest.raises(TvhError):
        backend.update_dvr_entry(entry, DvrEntryUpdate())

    backend._session.queue.append({'uuid': 'made'})
    assert backend.create_dvr_entry_by_event(44, 'cfg') == 'made'
    assert _posted(backend)[2] == {'event_id': 44, 'config_uuid': 'cfg'}

    backend._session.queue.append({'uuid': 'series'})
    ident = backend.create_autorec_entry(AutorecSpec(
        title='News',
        days_of_week=0x1F,
        priority=2,
        broadcast_type=1,
        comment='nightly',
    ))
    assert ident == 'series'
    conf = json.loads(_posted(backend)[2]['conf'])
    assert conf['title'] == 'News'
    assert conf['weekdays'] == [1, 2, 3, 4, 5]
    assert conf['pri'] == 2
    assert conf['btype'] == 1
    assert 'directory' not in conf
    assert 'dupDetect' not in conf

    backend._session.queue.append('time-id')
    assert backend.create_timerec_entry(TimerecSpec(title='Nightly', start=19 * 60, stop=19 * 60 + 30)) == 'time-id'
    conf = json.loads(_posted(backend)[2]['conf'])
    assert conf['start'] == '19:00'
    assert conf['stop'] == '19:30'

    with pytest.raises(TvhError):
        backend.update_autorec_entry(AutorecEntry(uuid='uu', title='News'), AutorecSpec(directory='/tv'))
    with pytest.raises(TvhError):
        backend.create_timerec_entry(TimerecSpec(title='Bad', start=1500, stop=10))


def test_http_lists_and_recording_access():
    backend = _http()
    backend._session.queue.append({'entries': [{
        'uuid': 'done',
        'disp_title': 'Show',
        'channelname': 'BBC',
        'start': 10,
        'duration': 5,
        'status': 'Completed OK',
        'sched_status': 'completed',
    }]})
    finished = backend.list_dvr_entries()
    assert finished[0].title == 'Show'
    assert finished[0].category() == 'finished'
    assert backend._session.calls[-1][1].endswith('/api/dvr/entry/grid')

    backend._session.queue.append({'entries': [{
        'uuid': 'gone',
        'title': 'Old',
        'channelname': 'BBC',
        'start': 1,
        'stop': 2,
        'status': 'File missing',
    }]})
    removed = backend.list_removed_dvr_entries()
    assert removed[0].uuid == 'gone'
    assert removed[0].duration == 1
    assert backend._session.calls[-1][1].endswith('/api/dvr/entry/grid_removed')

    backend._session.queue.append({'entries': [{
        'uuid': 'auto',
        'title': 'News',
        'weekdays': [1, 2, 3],
        'pri': 2,
        'channel': 'ch',
        'enabled': True,
    }]})
    series = backend.list_autorec_entries()[0]
    assert series.days_of_week == 0x07
    assert series.priority == 2
    assert series.channel_uuid == 'ch'

    backend._session.queue.append({'entries': [{
        'uuid': 'time',
        'title': 'Night',
        'start': '19:00',
        'stop': 'Any',
        'weekdays': [1, 7],
    }]})
    timer = backend.list_timerec_entries()[0]
    assert timer.start_minute == 19 * 60
    assert timer.stop_minute is None
    assert timer.days_of_week == 0x41

    backend._session.queue.append({'entries': [{
        'uuid': 'prof',
        'name': '',
        'storage': '/tv',
        'profile': 'pass',
        'enabled': True,
    }]})
    config = backend.list_dvr_configs()[0]
    assert config.uuid == 'prof'
    assert config.storage == '/tv'
    assert config.enabled is True

    assert backend.recording_url(_entry()) == 'http://u:p@127.0.0.1:9981/dvrfile/abc'
    handle = backend.open_recording(_entry())
    assert handle.size == 10
    assert handle.read(4, 0) == b'abcd'
    head = backend._session.calls[-2]
    assert head[0] == 'HEAD'
    read = backend._session.calls[-1]
    assert read[2]['headers']['Range'] == 'bytes=0-3'
    handle.close()
    with pytest.raises(TvhError):
        handle.read(1)


class _Conn:
    def __init__(self):
        self.calls = []
        self.replies = {}
        self._sock = object()

    def rpc(self, method, args=None, on_async=None, timeout=None):
        self.calls.append((method, args))
        reply = self.replies.get(method, {'success': 1})
        if reply.get('error'):
            raise TvhError(reply['error'])
        return reply


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


def test_htsp_native_and_proxied_dvr_calls():
    backend, conn = _htsp()
    entry = _entry()
    backend.cancel_dvr_entry(entry)
    assert conn.calls[-1] == ('cancelDvrEntry', {'id': 7})
    backend.delete_dvr_entry(entry)
    assert conn.calls[-1] == ('deleteDvrEntry', {'id': 7})
    backend.stop_dvr_entry(entry)
    assert conn.calls[-1] == ('stopDvrEntry', {'id': 7})
    backend.remove_dvr_entry(entry)
    assert conn.calls[-1] == ('api', {'path': 'dvr/entry/remove', 'args': {'uuid': 'abc'}})
    backend.set_dvr_prevrec(entry, 'unset')
    assert conn.calls[-1][1]['path'] == 'dvr/entry/prevrec/unset'
    backend.move_dvr_entry(entry, 'finished')
    assert conn.calls[-1][1]['path'] == 'dvr/entry/move/finished'

    backend.update_dvr_entry(entry, DvrEntryUpdate(
        comment='kept',
        enabled=True,
        channel=Channel(uuid='chan', name='BBC', htsp_id=8),
        start_extra=2,
    ))
    method, args = conn.calls[-1]
    assert method == 'updateDvrEntry'
    assert args['id'] == 7
    assert args['comment'] == 'kept'
    assert args['enabled'] == 1
    assert args['channelId'] == 8
    assert args['startExtra'] == 2

    conn.replies['getTicket'] = {'path': '/dvrfile/7', 'ticket': 'tok en'}
    assert backend.recording_url(entry) == 'http://u:p@127.0.0.1:9981/dvrfile/7?ticket=tok%20en'

    conn.replies['fileOpen'] = {'id': 3, 'size': 9, 'mtime': 5}
    conn.replies['fileRead'] = {'data': b'xyz'}
    conn.replies['getDvrCutpoints'] = {'cutpoints': [{'start': 0, 'end': 1000, 'type': 3}]}
    handle = backend.open_recording(entry)
    assert handle.size == 9
    assert conn.calls[-1] == ('fileOpen', {'file': '/dvrfile/7'})
    assert handle.read(3) == b'xyz'
    assert conn.calls[-1][1]['offset'] == 0
    points = backend.get_dvr_cutpoints(entry)
    assert points[0].kind == 'commercial'
    assert points[0].end_ms == 1000
    handle.close()
    assert conn.calls[-1][0] == 'fileClose'
    handle.close()

    conn.replies['addDvrEntry'] = {'success': 1, 'id': 12}
    assert backend.create_dvr_entry_by_event(44, 'cfg') == '12'
    assert conn.calls[-1][1]['eventId'] == 44
    assert conn.calls[-1][1]['configName'] == 'cfg'

    conn.replies['addAutorecEntry'] = {'success': 1, 'id': '99'}
    assert backend.create_autorec_entry(AutorecSpec(
        title='News',
        days_of_week=0x07,
        directory='/tv',
        dup_detect=1,
        channel=Channel(uuid='c', name='BBC', htsp_id=4),
    )) == '99'
    created = conn.calls[-1][1]
    assert created['daysOfWeek'] == 7
    assert created['directory'] == '/tv'
    assert created['dupDetect'] == 1
    assert created['channelId'] == 4

    conn.replies['updateAutorecEntry'] = {}
    backend.update_autorec_entry(
        AutorecEntry(uuid='uu', title='News', htsp_id='55'),
        AutorecSpec(enabled=False),
    )
    assert conn.calls[-1][0] == 'updateAutorecEntry'
    assert conn.calls[-1][1]['id'] == '55'
    assert conn.calls[-1][1]['enabled'] == 0

    conn.replies['api'] = {'response': {'uuid': 'saved'}}
    backend.update_autorec_entry(AutorecEntry(uuid='uu', title='News'), AutorecSpec(comment='x'))
    assert conn.calls[-1][1]['path'] == 'idnode/save'
    assert conn.calls[-1][1]['args']['node'] == [{'uuid': 'uu', 'comment': 'x'}]

    conn.replies['addTimerecEntry'] = {'success': 1, 'id': 't1'}
    assert backend.create_timerec_entry(TimerecSpec(title='Nightly', start=19 * 60, stop=20 * 60)) == 't1'
    assert conn.calls[-1][1]['start'] == 19 * 60
    assert conn.calls[-1][1]['stop'] == 20 * 60

    conn.replies['api'] = {'response': {'entries': [{
        'uuid': 'prof',
        'name': 'default',
        'storage': '/tv',
    }]}}
    assert backend.list_dvr_configs()[0].storage == '/tv'
    assert conn.calls[-1][1]['path'] == 'dvr/config/grid'
    assert conn.calls[-1][1]['args']['limit'] == 10000

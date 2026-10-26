import json
import time
from datetime import datetime

from tvhplayer.core.guide import epg_htsp_transport, epg_http_params
from tvhplayer.core.guide_grid import (
    RECORDING,
    SCHEDULED,
    SPAN_SECONDS,
    GuideData,
    cell_at,
    cell_description,
    day_label,
    entries_by_event,
    local_midnight,
    recording_state,
    row_cells,
    slot_start,
    span_start,
    spans_between,
    timing_text,
)
from tvhplayer.core.models import Channel, DvrEntry, EpgEvent, EpgQuery


def _event(start, stop, title='Show', channel='a', event_id=None, **extra):
    return EpgEvent(start=start, stop=stop, title=title, channel_uuid=channel, event_id=event_id, **extra)


def test_slot_start_is_a_local_half_hour():
    now = int(time.time())
    start = slot_start(now)
    assert now - 1800 < start <= now
    assert datetime.fromtimestamp(start).minute in (0, 30)
    assert datetime.fromtimestamp(start).second == 0
    assert slot_start(start) == start


def test_spans_count_from_the_origin():
    origin = 1_000_000
    assert span_start(origin + 10, origin) == origin
    assert span_start(origin + SPAN_SECONDS, origin) == origin + SPAN_SECONDS
    assert spans_between(origin + 100, origin + SPAN_SECONDS + 1, origin) == [origin, origin + SPAN_SECONDS]
    # Nothing before the origin is ever asked for.
    assert spans_between(origin - 5000, origin + 10, origin) == [origin]


def test_span_query_sends_inclusive_bounds_as_grid_filters():
    params = epg_http_params(EpgQuery(ends_after=1000, starts_before=2000, limit=50))
    assert json.loads(params['filter']) == [
        {'field': 'stop', 'type': 'numeric', 'value': 1001, 'comparison': 'gt'},
        {'field': 'start', 'type': 'numeric', 'value': 1999, 'comparison': 'lt'},
    ]
    assert params['limit'] == 50
    assert 'filter' not in epg_http_params(EpgQuery(limit=5))
    channel = Channel(uuid='u', name='One', htsp_id=4)
    # HTSP's own calls cannot filter by time, so a span goes to the grid.
    assert epg_htsp_transport(EpgQuery(channel=channel, ends_after=1)) == 'http'
    assert epg_htsp_transport(EpgQuery(channel=channel)) == 'getEvents'


def test_guide_data_matches_by_uuid_then_name_and_keeps_a_programme_once():
    one = Channel(uuid='uuid-1', name='One')
    two = Channel(uuid='', name='Two', htsp_id=7)
    data = GuideData([one, two])
    first = _event(100, 200, 'News', channel='uuid-1', event_id=1)
    data.add(0, [
        first,
        _event(200, 300, 'Film', channel='other-uuid', event_id=2, channel_name='two'),
        _event(300, 300, 'Empty', channel='uuid-1', event_id=3),
        _event(100, 200, 'Lost', channel='nowhere', event_id=4),
    ])
    data.add(SPAN_SECONDS, [_event(100, 200, 'News again', channel='uuid-1', event_id=1)])
    assert [event.title for event in data.events('uuid-1')] == ['News again']
    assert [event.title for event in data.events('7')] == ['Film']
    assert data.loaded == {0, SPAN_SECONDS}
    data.clear()
    assert data.events('uuid-1') == [] and not data.loaded


def test_row_cells_clip_to_the_view_and_never_overlap():
    events = [
        _event(0, 100, 'Before'),
        _event(50, 400, 'Clipped'),
        _event(350, 700, 'Overlaps'),
        _event(700, 720, 'Sliver'),
        _event(720, 2000, 'Past the end'),
    ]
    cells = row_cells(events, 100, 1000)
    assert [(cell.event.title, cell.start, cell.stop) for cell in cells] == [
        ('Clipped', 100, 400),
        ('Overlaps', 400, 700),
        ('Past the end', 720, 1000),
    ]
    assert cell_at(cells, 450) == 1
    assert cell_at(cells, 710) == 2
    assert cell_at(cells, 50) == 0
    assert cell_at([], 50) == -1


def test_recording_state_prefers_the_list_of_recordings():
    scheduled = DvrEntry(uuid='d1', title='News', channel_name='One', start=0, duration=60,
                         sched_status='scheduled', raw={'broadcast': 11})
    running = DvrEntry(uuid='d2', title='Film', channel_name='One', start=0, duration=60,
                       status='Running', raw={'eventId': 12})
    done = DvrEntry(uuid='d3', title='Old', channel_name='One', start=0, duration=60,
                    status='Completed OK', raw={'broadcast': 13})
    entries = entries_by_event([scheduled, running, done])
    assert set(entries) == {11, 12}
    assert recording_state(_event(0, 1, event_id=11), entries) == SCHEDULED
    assert recording_state(_event(0, 1, event_id=12), entries) == RECORDING
    # The guide still says scheduled, but the timer is gone from the list.
    stale = _event(0, 1, event_id=14, dvr_uuid='gone', dvr_state='scheduled')
    assert recording_state(stale, entries) == ''
    assert recording_state(stale, {}) == ''
    # Before the list is read, the guide's own word is used.
    assert recording_state(stale, None) == SCHEDULED
    assert recording_state(_event(0, 1, event_id=15), None) == ''


def test_timing_and_spoken_descriptions():
    now = slot_start(int(time.time())) + 600
    airing = _event(now - 600, now + 1200, 'News', event_id=1)
    later = _event(now + 3 * 86400, now + 3 * 86400 + 5400, 'Film', event_id=2)
    assert timing_text(airing, now).startswith('On now, ')
    assert timing_text(airing, now).endswith('20 min left')
    assert timing_text(later, now).endswith('1 h 30 min')
    assert timing_text(_event(now - 100, now - 10), now).startswith('Ended, ')
    spoken = cell_description('BBC One', airing, now, SCHEDULED)
    assert spoken.startswith('News, BBC One, On now')
    assert spoken.endswith('recording scheduled')
    assert day_label(now, now) == 'Today'
    assert day_label(local_midnight(now) + 86400 + 3600, now) == 'Tomorrow'

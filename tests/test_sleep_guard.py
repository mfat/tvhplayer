from tvhplayer.core.models import DvrEntry
from tvhplayer.core.sleep_guard import (
    LOCAL_REASON,
    SCHEDULED_REASON,
    SERVER_REASON,
    awake_reason,
    server_on_this_computer,
)

NOW = 1_000_000


def entry(status, start=NOW + 3600, duration=1800):
    return DvrEntry(uuid='u', title='t', channel_name='c', start=start, duration=duration, status=status)


def test_servers_on_this_computer():
    assert server_on_this_computer({'builtin': True, 'url': ''})
    assert server_on_this_computer({'url': 'http://127.0.0.1:9981'})
    assert server_on_this_computer({'url': 'http://localhost:9981'})
    assert server_on_this_computer({'url': 'http://[::1]:9981'})
    assert not server_on_this_computer({'url': 'http://192.168.1.5:9981'})
    assert not server_on_this_computer({'url': 'http://[bad'})
    assert not server_on_this_computer(None)


def test_recording_always_keeps_awake():
    assert awake_reason([], NOW, local_recording=True, keep_for_scheduled=False) == LOCAL_REASON
    assert awake_reason([entry('Running', start=NOW - 60)], NOW, keep_for_scheduled=False) == SERVER_REASON


def test_scheduled_recording_keeps_awake_only_when_asked():
    upcoming = [entry('Scheduled')]
    assert awake_reason(upcoming, NOW, keep_for_scheduled=True) == SCHEDULED_REASON
    assert awake_reason(upcoming, NOW, keep_for_scheduled=False) == ''


def test_finished_and_past_entries_let_the_computer_sleep():
    entries = [entry('Completed OK'), entry('Scheduled', start=NOW - 7200, duration=600)]
    assert awake_reason(entries, NOW) == ''
    assert awake_reason(None, NOW) == ''

import random

from pathlib import Path

from tvhplayer.core import builtin_server
from tvhplayer.core.builtin_server import (
    LineBuffer,
    StderrWatch,
    bundled_binary_candidates,
    command_args,
    ensure_builtin_server,
    initial_ports,
    pick_port_pair,
    quit_confirmation,
    recording_titles,
    startup_result,
    builtin_requests_ready,
)
from tvhplayer.core.models import DvrEntry, ServerConfig


def test_source_checkout_looks_beside_the_repo():
    repo = Path(builtin_server.__file__).resolve().parents[2]
    sibling = repo.parent / 'tvheadend' / 'build.linux' / 'tvheadend'
    assert sibling in bundled_binary_candidates()
    assert repo / 'build' / 'tvheadend' in bundled_binary_candidates()


def test_command_stays_in_the_foreground_without_a_pid_file():
    args = command_args('/app/bin/tvheadend', '/tmp/tvhplayer/tvheadend', 24111, 24112)
    assert args[0] == '/app/bin/tvheadend'
    assert '-f' not in args
    assert '--fork' not in args
    assert '--pid' not in args
    assert '-C' not in args
    assert '--firstrun' not in args
    assert '--logfile' not in args
    assert '--nostderr' not in args
    assert '--bindaddr' in args
    assert args[args.index('--http_port') + 1] == '24111'
    assert args[args.index('--htsp_port') + 1] == '24112'


def test_stderr_bind_failure_is_not_a_ready_server():
    watch = StderrWatch()
    watch.feed(
        'tcp: bind: 127.0.0.1:24111: Address already in use\n'
        'http: Starting HTTP server 127.0.0.1:9981\n'
    )
    assert watch.bind_failed
    assert startup_result(True, watch, True) == 'bind_failed'


def test_ready_requires_both_listeners_and_serverinfo():
    watch = StderrWatch()
    watch.feed('http: Starting HTTP server 127.0.0.1:24111\n')
    assert startup_result(True, watch, True) == 'pending'
    watch.feed('htsp: Starting HTSP server 127.0.0.1:24112\n')
    assert startup_result(True, watch, False) == 'pending'
    assert startup_result(True, watch, True) == 'ready'
    assert startup_result(False, watch, True) == 'exited'


def test_partial_lines_are_buffered():
    lines = LineBuffer()
    lines.feed('http: Starting HTTP ser')
    assert not lines.watch.http_started
    lines.feed('ver 127.0.0.1:24111\n')
    assert lines.watch.http_started


def test_ports_avoid_the_standard_tvheadend_ports():
    rng = random.Random(1)
    http_port, htsp_port = pick_port_pair(rng)
    assert http_port not in (9981, 9982)
    assert htsp_port not in (9981, 9982)
    assert http_port != htsp_port
    assert initial_ports(9981, 9982, rng) != (9981, 9982)
    assert initial_ports(24111, 24112) == (24111, 24112)


def test_builtin_entry_is_permanent_and_separate_from_a_local_instance(monkeypatch):
    monkeypatch.setattr('tvhplayer.core.builtin_server.sys.platform', 'linux')
    servers = ensure_builtin_server([
        {'name': 'Living room', 'url': 'http://127.0.0.1:9981', 'builtin': False},
    ])
    assert servers[0]['url'] == 'http://127.0.0.1:9981'
    assert servers[0]['builtin'] is False
    assert servers[1]['builtin'] is True
    assert servers[1]['name'] == 'Built-in Server'
    again = ensure_builtin_server(servers)
    assert len(again) == 2


def test_windows_does_not_list_a_builtin_server(monkeypatch):
    monkeypatch.setattr('tvhplayer.core.builtin_server.sys.platform', 'win32')
    servers = ensure_builtin_server([
        {'name': 'Built-in Server', 'url': 'http://127.0.0.1:24111', 'builtin': True},
        {'name': 'NAS', 'url': 'http://nas:9981'},
    ])
    assert servers == [{'name': 'NAS', 'url': 'http://nas:9981'}]


def test_quit_warning_names_the_active_recording():
    running = DvrEntry(
        uuid='1', title='News Hour', channel_name='One', start=0, duration=60,
        status='Running', sched_status='recording',
    )
    scheduled = DvrEntry(
        uuid='2', title='Later', channel_name='Two', start=0, duration=60,
        status='Scheduled', sched_status='scheduled',
    )
    message = quit_confirmation(recording_titles([running, scheduled]), False)
    assert 'News Hour' in message
    assert 'Later' not in message
    assert quit_confirmation([], False) is None
    assert 'could not be read' in quit_confirmation([], True)


def test_builtin_requests_wait_until_the_child_has_a_url():
    pending = {'name': 'Built-in Server', 'url': '', 'builtin': True}
    assert builtin_requests_ready(pending, False) is False
    assert builtin_requests_ready(pending, True) is False
    ready = {'name': 'Built-in Server', 'url': 'http://127.0.0.1:24111', 'builtin': True}
    assert builtin_requests_ready(ready, True) is True
    local = {'name': 'local', 'url': 'http://127.0.0.1:9981', 'builtin': False}
    assert builtin_requests_ready(local, False) is True


def test_builtin_flag_roundtrips():
    cfg = ServerConfig.from_dict({'name': 'Built-in Server', 'url': '', 'builtin': True})
    assert cfg.to_dict()['builtin'] is True

import http.server
import json
import os
import random
import stat
import sys
import threading
import time

from datetime import datetime

from pathlib import Path

import pytest

from tvhplayer.core import builtin_server
from tvhplayer.core.builtin_server import (
    LineBuffer,
    StderrWatch,
    bundled_binary_candidates,
    apply_builtin_endpoint,
    command_args,
    ensure_builtin_server,
    ensure_superuser,
    find_builtin_server,
    initial_ports,
    pick_port_pair,
    quit_confirmation,
    recording_titles,
    upcoming_recordings,
    when_text,
    serverinfo_ok,
    startup_result,
    builtin_requests_ready,
    without_builtin_secrets,
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
    assert '--noacl' not in args
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
    assert servers[1]['protocol'] == 'htsp'
    again = ensure_builtin_server(servers)
    assert len(again) == 2


def test_windows_and_macos_do_not_list_a_builtin_server(monkeypatch):
    for platform in ('win32', 'darwin'):
        monkeypatch.setattr('tvhplayer.core.builtin_server.sys.platform', platform)
        servers = ensure_builtin_server([
            {'name': 'Built-in Server', 'url': 'http://127.0.0.1:24111', 'builtin': True},
            {'name': 'NAS', 'url': 'http://nas:9981'},
        ])
        assert servers == [{'name': 'NAS', 'url': 'http://nas:9981'}]


def test_deb_and_rpm_location_is_searched():
    assert Path('/usr/libexec/tvhplayer/tvheadend') in bundled_binary_candidates()


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


def _entry(uuid, title, start, sched_status='scheduled', status='Scheduled', raw=None):
    return DvrEntry(
        uuid=uuid, title=title, channel_name='One', start=start, duration=600,
        status=status, sched_status=sched_status, raw=raw or {},
    )


def test_upcoming_recordings_skip_past_disabled_and_running_rows():
    now = 1_000_000
    later = _entry('1', 'Later', now + 7200)
    soon = _entry('2', 'Soon', now + 60)
    past = _entry('3', 'Past', now - 3600)
    off = _entry('4', 'Off', now + 60, raw={'enabled': False})
    running = _entry('5', 'Now', now - 60, 'recording', 'Running')
    found = upcoming_recordings([later, past, off, running, soon], now)
    assert [entry.title for entry in found] == ['Soon', 'Later']


def test_when_text_names_the_day():
    now = datetime(2026, 10, 25, 12, 0).timestamp()
    assert when_text(datetime(2026, 10, 25, 21, 0).timestamp(), now) == 'today at 21:00'
    assert when_text(datetime(2026, 10, 26, 6, 30).timestamp(), now) == 'tomorrow at 06:30'
    assert when_text(datetime(2026, 10, 31, 20, 15).timestamp(), now) == 'Sat 31 Oct at 20:15'


def test_quit_warning_names_the_next_scheduled_recording():
    now = datetime(2026, 10, 25, 12, 0).timestamp()
    first = _entry('1', 'News', datetime(2026, 10, 25, 21, 0).timestamp())
    second = _entry('2', 'Film', datetime(2026, 10, 26, 21, 0).timestamp())
    message = quit_confirmation([], False, [first, second], now=now)
    assert 'Next: News today at 21:00 (and 1 more)' in message
    assert 'could not be read' not in quit_confirmation([], True, [first], now=now)


def test_quit_warning_covers_local_recording_on_any_server():
    message = quit_confirmation([], False, local_recording='One (rec.ts)')
    assert 'One (rec.ts)' in message


def test_playlist_update_alone_does_not_ask():
    assert quit_confirmation([], False, playlist_updates=['IPTV']) is None
    message = quit_confirmation([], False, local_recording='One (rec.ts)', playlist_updates=['IPTV'])
    assert 'IPTV' in message


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


def test_superuser_login_is_generated_once_and_owner_only(tmp_path):
    config_dir = tmp_path / 'tvheadend'
    username, password = ensure_superuser(config_dir)
    path = config_dir / 'superuser'
    assert json.loads(path.read_text()) == {'username': username, 'password': password}
    assert len(password) >= 16
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700
    assert ensure_superuser(config_dir) == (username, password)


def test_unusable_superuser_file_is_replaced(tmp_path):
    config_dir = tmp_path / 'tvheadend'
    config_dir.mkdir()
    (config_dir / 'superuser').write_text('{"username": "admin", "password": ""}')
    username, password = ensure_superuser(config_dir)
    assert password
    assert json.loads((config_dir / 'superuser').read_text())['password'] == password


def test_builtin_entry_carries_the_generated_login(monkeypatch):
    monkeypatch.setattr('tvhplayer.core.builtin_server.sys.platform', 'linux')
    servers = ensure_builtin_server([], 24111, 24112, 'tvhplayer', 'secret-secret-secret')
    entry = find_builtin_server(servers)
    assert (entry['username'], entry['password']) == ('tvhplayer', 'secret-secret-secret')
    moved = apply_builtin_endpoint(servers, 24113, 24114, 'tvhplayer', 'another-secret-value')
    assert find_builtin_server(moved)['url'] == 'http://127.0.0.1:24113'
    assert find_builtin_server(moved)['password'] == 'another-secret-value'
    nas = {'name': 'NAS', 'url': 'http://nas:9981', 'username': 'me', 'password': 'pw'}
    cleaned = without_builtin_secrets([nas] + moved)
    assert cleaned[0] == nas
    assert cleaned[1]['password'] == '' and cleaned[1]['username'] == ''
    assert find_builtin_server(moved)['password'] == 'another-secret-value'


def test_config_file_never_holds_the_builtin_password(tmp_path):
    from tvhplayer.core.config import ConfigStore

    store = ConfigStore(tmp_path / 'tvhplayer.conf')
    store.servers = [{
        'name': 'Built-in Server', 'url': 'http://127.0.0.1:24111',
        'username': 'tvhplayer', 'password': 'secret-secret-secret', 'builtin': True,
    }]
    store.save()
    assert 'secret-secret-secret' not in (tmp_path / 'tvhplayer.conf').read_text()
    assert store.servers[0]['password'] == 'secret-secret-secret'


class _ServerInfo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"sw_version": "4.3", "api_version": 19, "name": "Tvheadend"}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_serverinfo_check_ignores_a_proxy_from_the_environment(monkeypatch):
    server = http.server.HTTPServer(('127.0.0.1', 0), _ServerInfo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for name in ('http_proxy', 'HTTP_PROXY'):
            monkeypatch.setenv(name, 'http://127.0.0.1:9')
        for name in ('no_proxy', 'NO_PROXY'):
            monkeypatch.delenv(name, raising=False)
        assert serverinfo_ok(server.server_address[1], timeout=2)
    finally:
        server.shutdown()
        server.server_close()


def test_supervisor_gives_up_when_the_child_never_answers(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

    from tvhplayer.builtin_supervisor import BuiltinSupervisor

    app = QCoreApplication.instance() or QCoreApplication([])
    binary = tmp_path / 'tvheadend'
    binary.write_text('#!/bin/sh\nexec sleep 30\n')
    binary.chmod(0o755)
    supervisor = BuiltinSupervisor(binary, tmp_path / 'config', 24111, 24112)
    supervisor.startup_timeout = 0.3
    reasons = []
    loop = QEventLoop()
    supervisor.failed.connect(lambda reason: (reasons.append(reason), loop.quit()))
    QTimer.singleShot(5000, loop.quit)
    supervisor.start()
    loop.exec()
    try:
        assert reasons and 'did not answer' in reasons[0]
        assert supervisor.status == 'failed'
        assert not supervisor.is_running()
        assert supervisor.username == 'tvhplayer'
    finally:
        supervisor.stop()
    app.processEvents()


def _fake_proc(root, pid, argv, ppid):
    folder = root / str(pid)
    folder.mkdir(parents=True)
    (folder / 'cmdline').write_bytes(b'\0'.join(arg.encode() for arg in argv) + b'\0')
    (folder / 'stat').write_text(f'{pid} (odd name) x) S {ppid} 1 1 0\n')


def test_finds_servers_on_the_builtin_config_folder(tmp_path):
    from tvhplayer.core.builtin_server import owned_by_other_app, servers_using

    config = tmp_path / 'tvheadend'
    config.mkdir()
    proc = tmp_path / 'proc'
    _fake_proc(proc, 101, ['/app/bin/tvheadend', '-c', str(config), '-B'], 1)
    _fake_proc(proc, 102, ['/usr/bin/tvheadend', '-c', '/var/lib/tvheadend'], 1)
    _fake_proc(proc, 103, ['/usr/bin/python3', '/usr/share/tvhplayer/tvhplayer.py'], 1)
    _fake_proc(proc, 104, ['/usr/bin/tvheadend', '--config', str(config)], 103)
    assert sorted(servers_using(config, str(proc))) == [(101, 1), (104, 103)]
    assert not owned_by_other_app(1, str(proc))
    assert owned_by_other_app(103, str(proc))


def test_leftover_server_is_stopped_but_another_window_keeps_its_own(tmp_path, monkeypatch):
    import subprocess

    import tvhplayer.core.builtin_server as builtin

    config = tmp_path / 'tvheadend'
    config.mkdir()
    leftover = subprocess.Popen([
        'bash', '-c',
        f'exec -a tvheadend {sys.executable} -c "import time; time.sleep(60)" -c {config}',
    ])
    try:
        for _ in range(50):
            if builtin.servers_using(config):
                break
            time.sleep(0.05)
        monkeypatch.setattr(builtin, 'owned_by_other_app', lambda _parent, _proc='/proc': True)
        with pytest.raises(RuntimeError):
            builtin.stop_leftover_servers(config)
        assert leftover.poll() is None
        monkeypatch.setattr(builtin, 'owned_by_other_app', lambda _parent, _proc='/proc': False)
        assert builtin.stop_leftover_servers(config, timeout=5) == [leftover.pid]
        assert leftover.wait(timeout=5) is not None
    finally:
        if leftover.poll() is None:
            leftover.kill()


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux parent-death signal')
def test_launched_server_stops_when_the_app_dies(tmp_path):
    import subprocess

    from tvhplayer.core.builtin_server import launch_command

    pid_file = tmp_path / 'pid'
    # A stand-in app: starts "Tvheadend" (sleep) through the launcher, then dies.
    app = (
        'import os, subprocess, sys, time\n'
        'from tvhplayer.core.builtin_server import launch_command\n'
        'program, args = launch_command(["/bin/sleep", "60"])\n'
        'child = subprocess.Popen([program] + args)\n'
        f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
        'time.sleep(1)\n'
        'os._exit(0)\n'
    )
    subprocess.run([sys.executable, '-c', app], check=True, cwd=str(Path(__file__).resolve().parents[1]))
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            with open(f'/proc/{child}/stat') as handle:
                state = handle.read().rsplit(')', 1)[1].split()[0]
        except FileNotFoundError:
            break
        if state == 'Z':
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        pytest.fail('the launched process outlived its parent')
    program, args = launch_command(['/bin/tvheadend', '-c', 'x'], parent_pid=42, python='/usr/bin/python3')
    assert program == '/usr/bin/python3'
    assert args[-4:] == ['42', '/bin/tvheadend', '-c', 'x']


def test_builtin_server_gets_its_ready_to_use_defaults():
    from urllib.parse import parse_qs

    from tvhplayer.core.builtin_server import apply_builtin_defaults

    received = []

    class Api(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers['Content-Length'])
            received.append((self.path, parse_qs(self.rfile.read(length).decode())))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert apply_builtin_defaults(server.server_address[1]) == []
    finally:
        server.shutdown()
    paths = [path for path, _form in received]
    assert paths == ['/api/config/save', '/api/wizard/cancel']
    assert json.loads(received[0][1]['node'][0]) == {'digest': 2}
    assert apply_builtin_defaults(_free_port_for_test()) == ['plain login', 'setup wizard off']


def test_builtin_server_records_into_the_app_folder():
    from urllib.parse import parse_qs

    from tvhplayer.core.builtin_server import apply_builtin_defaults

    received = []
    grid = {'entries': [
        {'uuid': 'other', 'name': 'Archive', 'storage': '/srv/archive'},
        {'uuid': 'default', 'name': '', 'storage': '/app/share/tvhplayer'},
    ]}

    class Api(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers['Content-Length'])
            received.append((self.path, parse_qs(self.rfile.read(length).decode())))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(grid if self.path == '/api/dvr/config/grid' else {}).encode())

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert apply_builtin_defaults(
            server.server_address[1], recordings_dir='/home/me/Videos', padding=(2, 5),
        ) == []
        # Margins the profile already has are not saved again.
        grid['entries'][1].update({'pre-extra-time': 2, 'post-extra-time': 5, 'storage': '/home/me/Videos'})
        assert apply_builtin_defaults(server.server_address[1], recordings_dir='/home/me/Videos', padding=(2, 5)) == []
    finally:
        server.shutdown()
    saved = [form for path, form in received if path == '/api/idnode/save']
    assert [json.loads(form['node'][0]) for form in saved] == [
        {'uuid': 'default', 'storage': '/home/me/Videos'},
        {'uuid': 'default', 'pre-extra-time': 2, 'post-extra-time': 5},
    ]
    assert apply_builtin_defaults(_free_port_for_test(), recordings_dir='/x')[-1] == 'recordings folder'


def test_no_builtin_entry_without_a_packaged_tvheadend():
    servers = ensure_builtin_server([{'name': 'NAS', 'url': 'http://nas:9981'}], available=False)
    assert servers == [{'name': 'NAS', 'url': 'http://nas:9981'}]


def _free_port_for_test():
    import socket

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_server_cannot_start_again_once_the_app_quits(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QCoreApplication

    from tvhplayer.builtin_supervisor import BuiltinSupervisor

    app = QCoreApplication.instance() or QCoreApplication([])
    binary = tmp_path / 'tvheadend'
    binary.write_text('#!/bin/sh\nexec sleep 30\n')
    binary.chmod(0o755)
    supervisor = BuiltinSupervisor(binary, tmp_path / 'config', 24113, 24114)
    supervisor.shut_down()
    # A playlist refresh that finishes during quit reloads channels, which asks for the server.
    supervisor.start()
    assert supervisor.status == 'stopped'
    assert not supervisor._child_alive()
    assert app is not None

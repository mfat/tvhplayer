import http.server
import json
import os
import random
import stat
import threading

from pathlib import Path

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

import logging
import sys

import pytest

from tvhplayer.core import logs


def test_log_folder_follows_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    assert logs.log_dir() == tmp_path / 'state' / 'tvhplayer'
    monkeypatch.delenv('XDG_STATE_HOME')
    monkeypatch.setenv('HOME', str(tmp_path))
    assert logs.log_dir() == tmp_path / '.local' / 'state' / 'tvhplayer'


def test_sanitize_hides_secrets():
    text = (
        '"password": "hunter2", url http://tvhplayer:s3cret@127.0.0.1:9981/stream '
        'Authorization: Basic dXNlcjpwYXNz password=abc'
    )
    clean = logs.sanitize(text)
    for secret in ('hunter2', 's3cret', 'dXNlcjpwYXNz', 'abc'):
        assert secret not in clean
    assert 'http://tvhplayer:***@127.0.0.1:9981/stream' in clean


@pytest.fixture
def restore_logging():
    stdout, stderr = sys.stdout, sys.stderr
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    yield
    sys.stdout, sys.stderr = stdout, stderr
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
    for name in (logs.SERVER_LOGGER, logs.OUTPUT_LOGGER, 'pychromecast',
                 'pychromecast.controllers.heartbeat', 'tvhplayer.core.chromecast'):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.NOTSET)


def test_configure_writes_app_and_server_logs(tmp_path, restore_logging):
    folder = logs.configure_logging(tmp_path / 'logs', capture_output=False)
    logging.getLogger('tvhplayer.test').warning('something odd')
    logging.getLogger(logs.SERVER_LOGGER).info('Starting HTTP server')
    for handler in logging.getLogger().handlers + logging.getLogger(logs.SERVER_LOGGER).handlers:
        handler.flush()
    app_log = (folder / logs.APP_LOG).read_text(encoding='utf-8')
    server_log = (folder / logs.SERVER_LOG).read_text(encoding='utf-8')
    assert 'something odd' in app_log
    assert 'Starting HTTP server' in server_log
    assert 'Starting HTTP server' not in app_log


def test_everything_the_process_writes_is_logged_and_hidden(tmp_path):
    """print(), a C library writing to fd 2 (like VLC), and a child program."""
    import subprocess
    from pathlib import Path

    script = (
        'import logging, os, subprocess, sys\n'
        'from tvhplayer.core import logs\n'
        f'logs.configure_logging({str(tmp_path / "logs")!r})\n'
        'print("Debug: Stream URL: http://tvhplayer:s3cret@127.0.0.1:9981/stream/channel/x")\n'
        'os.write(2, b"[0000] access stream error: HTTP 401 error\\n")\n'
        'subprocess.run(["sh", "-c", "echo child says hello >&2"])\n'
        'logging.getLogger("tvhplayer.test").warning("a warning")\n'
    )
    done = subprocess.run(
        [sys.executable, '-c', script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    terminal = done.stdout + done.stderr
    assert 's3cret' not in terminal
    assert 'http://tvhplayer:***@127.0.0.1:9981' in done.stdout
    assert 'HTTP 401 error' in done.stderr
    assert 'child says hello' in done.stderr
    assert terminal.count('a warning') == 1
    app_log = (tmp_path / 'logs' / logs.APP_LOG).read_text(encoding='utf-8')
    assert 's3cret' not in app_log
    for text in ('Debug: Stream URL: http://tvhplayer:***@', 'HTTP 401 error', 'child says hello'):
        assert text in app_log
    assert app_log.count('a warning') == 1


def test_source_run_prints_chromecast_traffic_and_hides_heartbeats(tmp_path):
    import subprocess
    from pathlib import Path

    script = (
        'import logging\n'
        'from tvhplayer.core import logs\n'
        f'logs.configure_logging({str(tmp_path / "logs")!r})\n'
        'logging.getLogger("pychromecast.socket_client").debug('
        '"[TV(192.168.1.8):8009] Sending: http://user:s3cret@tv/stream")\n'
        'logging.getLogger("pychromecast.socket_client").debug('
        '"[TV(192.168.1.8):8009] Received: Message urn:x-cast:com.google.cast.tp.heartbeat '
        'from receiver-0 to sender-0: {\'type\': \'PONG\'}")\n'
        'logging.getLogger("pychromecast.controllers.heartbeat").debug("ping")\n'
        'logging.getLogger("tvhplayer.core.chromecast").info('
        '"Connected to Living room at 192.168.1.8")\n'
        'logging.getLogger("tvhplayer.test").warning("a warning")\n'
    )
    done = subprocess.run(
        [sys.executable, '-c', script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    terminal = done.stdout + done.stderr
    assert 's3cret' not in terminal
    assert 'Sending: http://user:***@tv/stream' in terminal
    assert 'Debug: tvhplayer.core.chromecast: Connected to Living room at 192.168.1.8' in terminal
    assert 'heartbeat' not in terminal
    assert 'ping' not in terminal
    assert terminal.count('a warning') == 1
    app_log = (tmp_path / 'logs' / logs.APP_LOG).read_text(encoding='utf-8')
    assert 'Sending: http://user:***@tv/stream' in app_log
    assert 'Connected to Living room at 192.168.1.8' in app_log


def test_packaged_run_keeps_chromecast_traffic_in_the_log_file(tmp_path):
    import subprocess
    from pathlib import Path

    script = (
        'import logging, sys\n'
        'sys.frozen = True\n'
        'from tvhplayer.core import logs\n'
        f'logs.configure_logging({str(tmp_path / "logs")!r})\n'
        'logging.getLogger("pychromecast.socket_client").debug("[TV] Sending: LOAD")\n'
        'logging.getLogger("tvhplayer.core.chromecast").info("Connected to Living room")\n'
    )
    done = subprocess.run(
        [sys.executable, '-c', script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    terminal = done.stdout + done.stderr
    assert 'Sending: LOAD' not in terminal
    assert 'Connected to Living room' not in terminal
    app_log = (tmp_path / 'logs' / logs.APP_LOG).read_text(encoding='utf-8')
    assert 'Sending: LOAD' in app_log
    assert 'Connected to Living room' in app_log


def test_unwritable_folder_keeps_the_console(tmp_path, restore_logging):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    logs.configure_logging(blocker / 'logs', capture_output=False)
    print('still printed')

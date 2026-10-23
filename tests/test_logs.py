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
    for name in (logs.SERVER_LOGGER, logs.OUTPUT_LOGGER):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_configure_writes_app_and_server_logs(tmp_path, restore_logging, capsys):
    folder = logs.configure_logging(tmp_path / 'logs')
    print('Debug: Fetching channels from http://u:pw@tv.lan:9981')
    logging.getLogger('tvhplayer.test').warning('something odd')
    logging.getLogger(logs.SERVER_LOGGER).info('Starting HTTP server')
    for handler in logging.getLogger().handlers + logging.getLogger(logs.SERVER_LOGGER).handlers:
        handler.flush()
    app_log = (folder / logs.APP_LOG).read_text(encoding='utf-8')
    server_log = (folder / logs.SERVER_LOG).read_text(encoding='utf-8')
    assert 'Debug: Fetching channels from http://u:***@tv.lan:9981' in app_log
    assert 'something odd' in app_log
    assert 'Starting HTTP server' in server_log
    assert 'Starting HTTP server' not in app_log
    assert 'Fetching channels' in capsys.readouterr().out


def test_unwritable_folder_keeps_the_console(tmp_path, restore_logging):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    logs.configure_logging(blocker / 'logs')
    print('still printed')

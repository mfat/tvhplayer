import os
import subprocess
import threading
import time

from tvhplayer.core.recorder import (
    LocalRecorder,
    build_ffmpeg_command,
    free_path,
    parse_ffmpeg_options,
    redact_command,
)


def test_ts_command_copies_streams():
    cmd = build_ffmpeg_command('http://127.0.0.1:9981/stream/channel/abc', '/tmp/a.ts')
    assert cmd[0] == 'ffmpeg'
    assert '-i' in cmd
    assert cmd[cmd.index('-i') + 1].endswith('/stream/channel/abc')
    assert '-f' in cmd and 'mpegts' in cmd
    assert cmd[-1] == '/tmp/a.ts'
    assert '-headers' not in cmd


def test_mp4_command_transcodes_audio():
    cmd = build_ffmpeg_command('http://host/stream', '/tmp/show.mp4')
    assert 'aac' in cmd
    assert 'mp4' in cmd


def test_mkv_command_copies_streams():
    cmd = build_ffmpeg_command('http://host/stream', '/tmp/show.mkv')
    assert cmd[-5:] == ['-c', 'copy', '-f', 'matroska', '/tmp/show.mkv']


def test_extra_options_come_last_so_they_win():
    extra = parse_ffmpeg_options('-c:a aac -b:a 128k -metadata "title=Evening news"')
    cmd = build_ffmpeg_command('http://host/stream', '/tmp/a.ts', extra_options=extra)
    assert cmd[-7:] == ['-c:a', 'aac', '-b:a', '128k', '-metadata', 'title=Evening news', '/tmp/a.ts']
    assert cmd.index('-c:a') > cmd.index('mpegts')


def test_auth_header_only_when_url_has_no_userinfo():
    with_header = build_ffmpeg_command(
        'http://127.0.0.1:9981/stream/channel/x', '/tmp/a.ts', 'user', 'secret'
    )
    assert '-headers' in with_header
    already_embedded = build_ffmpeg_command(
        'http://user:secret@127.0.0.1:9981/stream/channel/x', '/tmp/a.ts', 'user', 'secret'
    )
    assert '-headers' not in already_embedded
    ticket = build_ffmpeg_command(
        'http://127.0.0.1:9981/stream/channelid/4?ticket=tk', '/tmp/a.ts', 'user', 'secret'
    )
    assert '-headers' not in ticket


def test_redact_hides_basic_auth():
    cmd = build_ffmpeg_command(
        'http://user:secret@127.0.0.1:9981/stream/channel/x', '/tmp/a.ts'
    )
    text = redact_command(cmd)
    assert 'secret' not in text
    assert 'user:secret@' not in text


class _FakeProcess:
    def __init__(self, stderr):
        self.stderr = stderr
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 255

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired('ffmpeg', timeout)
        return self.returncode

    def communicate(self, timeout=None):
        raise AssertionError('communicate would deadlock on an unread pipe')


def test_start_drains_stderr_past_the_kernel_pipe(monkeypatch, tmp_path):
    read_fd, write_fd = os.pipe()
    process = _FakeProcess(os.fdopen(read_fd, 'rb', buffering=0))
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen['kwargs'] = kwargs
        return process

    monkeypatch.setattr('tvhplayer.core.recorder.subprocess.Popen', fake_popen)
    recorder = LocalRecorder()
    payload = b'START' + (b'x' * (256 * 1024)) + b'END'
    errors = []

    def writer():
        view = payload
        try:
            while view:
                written = os.write(write_fd, view)
                view = view[written:]
        except Exception as exc:
            errors.append(exc)
        finally:
            os.close(write_fd)

    thread = threading.Thread(target=writer, daemon=True)
    try:
        recorder.start('http://127.0.0.1:9981/stream/channel/abc', tmp_path / 'a.ts')
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        assert errors == []
        deadline = time.time() + 2
        text = ''
        while time.time() < deadline:
            text = recorder._stderr_text()
            if text.endswith('END'):
                break
            time.sleep(0.01)
        assert text.endswith('END')
        assert 'START' not in text
        assert len(text.encode()) <= 64 * 1024
        assert seen['kwargs']['stdin'] is subprocess.DEVNULL
        assert seen['kwargs']['stdout'] is subprocess.DEVNULL
        assert seen['kwargs']['stderr'] is subprocess.PIPE
        assert 'bufsize' not in seen['kwargs']
        process.returncode = 255
        status = recorder.status()
        assert status.return_code == 255
        assert status.stderr.endswith('END')
    finally:
        recorder.stop()
        if thread.ident is not None:
            thread.join(1)


def test_stop_sends_sigterm_without_reading_the_pipe_itself(monkeypatch, tmp_path):
    read_fd, write_fd = os.pipe()
    process = _FakeProcess(os.fdopen(read_fd, 'rb', buffering=0))
    monkeypatch.setattr(
        'tvhplayer.core.recorder.subprocess.Popen',
        lambda cmd, **kwargs: process,
    )
    recorder = LocalRecorder()
    try:
        recorder.start('http://127.0.0.1:9981/stream/channel/abc', tmp_path / 'a.ts')
        os.write(write_fd, b'warning\n')
        os.close(write_fd)
        write_fd = -1
        recorder.stop()
        assert process.terminated is True
        assert process.killed is False
        assert recorder._stderr_text() == 'warning\n'
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        recorder.stop()


def test_free_path_never_reuses_a_recording_name(tmp_path):
    path = str(tmp_path / 'recording_News_20260101_120000.ts')
    assert free_path(path) == path
    (tmp_path / 'recording_News_20260101_120000.ts').write_bytes(b'x')
    second = str(tmp_path / 'recording_News_20260101_120000_2.ts')
    assert free_path(path) == second
    assert free_path(path, {second}) == str(tmp_path / 'recording_News_20260101_120000_3.ts')

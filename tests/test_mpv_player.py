import sys
import threading
import types
from concurrent.futures import Future

import pytest

from tvhplayer.core import proxy
from tvhplayer.core.player import DEINTERLACE_AUTO, DEINTERLACE_OFF, DEINTERLACE_ON, NO_TRACK


class _EndFile:
    EOF = 0
    RESTARTED = 1
    ABORTED = 2
    QUIT = 3
    ERROR = 4
    REDIRECT = 5


class _EventID:
    END_FILE = 7
    PLAYBACK_RESTART = 21


def _event(kind, reason=None):
    return types.SimpleNamespace(
        event_id=types.SimpleNamespace(value=kind),
        data=types.SimpleNamespace(reason=reason),
    )


class _Mpv:
    def __init__(self, log_handler=None, loglevel=None, **options):
        self.options = options
        self.callbacks = []
        self.props = {}
        self.loaded = []
        self.commands = []
        self.messages = []
        self.idle_active = True
        self.volume = 100
        self.mute = False
        self.aid = 1
        self.sid = False
        self.deinterlace = 'no'
        self.track_list = []
        self.terminated = False

    def option_info(self, name):
        assert name == 'deinterlace'
        return {'name': name, 'type': 'Choice', 'choices': ['no', 'yes', 'auto']}

    def register_event_callback(self, callback):
        self.callbacks.append(callback)

    def fire(self, event):
        for callback in self.callbacks:
            callback(event)

    def __setitem__(self, name, value):
        self.props[name] = value

    def loadfile(self, url):
        self.loaded.append((url, self.props.get('http-proxy')))
        self.idle_active = False

    def command(self, *args):
        self.commands.append(args)
        if args == ('dump-cache', '0', '0', ''):
            self.dump_future.set_result(None)
        if args == ('stop',):
            self.idle_active = True

    def command_async(self, *args):
        self.messages.append(args)
        if args[0] == 'dump-cache':
            self.dump_future = Future()
            return self.dump_future

    def terminate(self):
        self.terminated = True


@pytest.fixture
def engine(monkeypatch):
    fake = types.SimpleNamespace(
        MPV=_Mpv,
        MpvEventID=_EventID,
        MpvEventEndFile=_EndFile,
        MpvGlGetProcAddressFn=lambda fn: fn,
        MpvRenderContext=lambda mpv, api, **kw: types.SimpleNamespace(mpv=mpv, api=api, params=kw),
    )
    monkeypatch.setitem(sys.modules, 'mpv', fake)
    monkeypatch.setattr(proxy, '_saved_http_proxy', proxy._HIDDEN)
    monkeypatch.setenv('http_proxy', 'http://proxy.example:3128')
    for name in ('no_proxy', 'NO_PROXY', 'HTTP_PROXY'):
        monkeypatch.delenv(name, raising=False)
    from tvhplayer.core.mpv_player import MpvPlayer

    player = MpvPlayer()
    seen = []
    player.set_handlers(
        on_playing=lambda: seen.append('playing'),
        on_stopped=lambda: seen.append('stopped'),
        on_error=lambda: seen.append('error'),
    )
    return player, player._mpv, seen


def test_mpv_draws_only_through_the_render_api(engine):
    _player, mpv, _seen = engine
    assert mpv.options['vo'] == 'libmpv'
    assert mpv.options['input_default_bindings'] is False


class _MpvWithoutLua(_Mpv):
    """libmpv built without Lua, as in the Flatpak: no osc or ytdl options."""

    LUA_ONLY = ('osc', 'ytdl')

    def __init__(self, log_handler=None, loglevel=None, **options):
        for name in self.LUA_ONLY:
            if name in options:
                raise AttributeError('mpv option does not exist', -5, (None, name.encode(), b'no'))
        super().__init__(log_handler, loglevel, **options)

    def __setitem__(self, name, value):
        if name in self.LUA_ONLY:
            raise AttributeError('mpv property does not exist', -8, (None, name.encode(), b'no'))
        super().__setitem__(name, value)


def test_mpv_scripts_are_off_with_lua(engine):
    _player, mpv, _seen = engine
    assert mpv.props['osc'] is False
    assert mpv.props['ytdl'] is False


def test_mpv_without_lua_starts(engine, monkeypatch):
    monkeypatch.setattr(sys.modules['mpv'], 'MPV', _MpvWithoutLua)
    from tvhplayer.core.mpv_player import MpvPlayer

    player = MpvPlayer()
    assert player._mpv.options['vo'] == 'libmpv'


def test_painting_does_not_wait_for_the_next_frame(engine):
    _player, mpv, _seen = engine
    assert mpv.options['video_timing_offset'] == 0


def test_first_picture_of_each_stream_reports_playing_once(engine):
    player, mpv, seen = engine
    player.play('http://nas.example:9981/stream/channel/1')
    mpv.fire(_event(_EventID.PLAYBACK_RESTART))
    mpv.fire(_event(_EventID.PLAYBACK_RESTART))
    assert seen == ['playing']
    player.play('http://nas.example:9981/stream/channel/2')
    mpv.fire(_event(_EventID.END_FILE, _EndFile.ABORTED))
    mpv.fire(_event(_EventID.PLAYBACK_RESTART))
    assert seen == ['playing', 'stopped', 'playing']


def test_open_failure_reports_an_error(engine):
    player, mpv, seen = engine
    player.play('http://nas.example:9981/stream/channel/1')
    mpv.fire(_event(_EventID.END_FILE, _EndFile.ERROR))
    mpv.fire(_event(_EventID.PLAYBACK_RESTART))
    assert seen == ['error']


def test_end_of_a_recording_reports_stopped(engine):
    player, mpv, seen = engine
    player.play('http://nas.example:9981/dvrfile/abc')
    mpv.fire(_event(_EventID.PLAYBACK_RESTART))
    mpv.fire(_event(_EventID.END_FILE, _EndFile.EOF))
    assert seen == ['playing', 'stopped']


def test_stop_then_play_again(engine):
    player, mpv, _seen = engine
    player.play('http://nas.example:9981/stream/channel/1')
    assert player.is_playing()
    player.stop()
    assert not player.is_playing()
    player.play('http://nas.example:9981/stream/channel/2')
    assert player.is_playing()
    assert [url for url, _proxy in mpv.loaded] == [
        'http://nas.example:9981/stream/channel/1',
        'http://nas.example:9981/stream/channel/2',
    ]


def test_proxy_is_chosen_per_stream(engine):
    import os

    player, mpv, _seen = engine
    assert 'http_proxy' not in os.environ
    player.play('http://127.0.0.1:24111/stream/channel/1')
    player.play('http://nas.example:9981/stream/channel/1')
    assert [p for _url, p in mpv.loaded] == ['', 'http://proxy.example:3128']


def test_tracks_volume_and_mute(engine):
    player, mpv, _seen = engine
    mpv.track_list = [
        {'id': 1, 'type': 'video'},
        {'id': 1, 'type': 'audio', 'lang': 'eng'},
        {'id': 2, 'type': 'audio', 'title': 'Audio description', 'lang': 'eng'},
        {'id': 1, 'type': 'sub'},
    ]
    assert player.audio_tracks() == [(1, 'eng'), (2, 'Audio description - eng')]
    assert player.subtitle_tracks() == [(1, 'Track 1')]
    assert player.subtitle_track() == NO_TRACK
    player.set_subtitle_track(1)
    assert player.subtitle_track() == 1
    player.set_subtitle_track(NO_TRACK)
    assert mpv.sid == 'no'
    player.set_volume(130)
    assert mpv.volume == 100
    player.set_muted(True)
    assert player.is_muted()


class _Mpv037(_Mpv):
    """libmpv before 0.38, as in Ubuntu 24.04: deinterlace is a flag, without auto."""

    def __setattr__(self, name, value):
        if name == 'deinterlace' and value not in ('yes', 'no', True, False):
            raise TypeError('Tried to get/set mpv property using wrong format, or passed invalid value',
                            -9, (None, b'deinterlace', str(value).encode()))
        super().__setattr__(name, value)

    def option_info(self, name):
        return {'name': name, 'type': 'Flag'}


def test_deinterlace_auto_on_an_mpv_without_it(engine, monkeypatch):
    monkeypatch.setattr(sys.modules['mpv'], 'MPV', _Mpv037)
    from tvhplayer.core.mpv_player import MpvPlayer

    player = MpvPlayer()
    player.set_deinterlace(DEINTERLACE_AUTO)
    # With VA-API, 0.37's deinterlacer leaves progressive pictures alone, as auto does.
    assert player._mpv.deinterlace == 'yes'
    assert player.deinterlace() == DEINTERLACE_AUTO
    player.set_deinterlace(DEINTERLACE_OFF)
    assert player._mpv.deinterlace == 'no'


def test_deinterlace_changes_the_running_picture(engine):
    player, mpv, _seen = engine
    assert player.set_deinterlace(DEINTERLACE_ON) is True
    assert mpv.deinterlace == 'yes'
    player.set_deinterlace(DEINTERLACE_OFF)
    assert mpv.deinterlace == 'no'
    player.set_deinterlace(DEINTERLACE_AUTO)
    assert mpv.deinterlace == 'auto'
    assert player.deinterlace() == DEINTERLACE_AUTO


def test_messages_do_not_wait_for_mpv(engine):
    player, mpv, _seen = engine
    player.show_message('101  News', 2500)
    assert mpv.messages == [('show-text', '101  News', '2500')]


def test_render_context_gets_the_wayland_display(engine):
    player, mpv, _seen = engine
    context = player.create_render_context(lambda name: 0, wl_display=1234)
    assert context.api == 'opengl'
    assert context.params['wl_display'] == 1234
    assert 'wl_display' not in player.create_render_context(lambda name: 0).params


def test_close_frees_the_widget_render_context_before_mpv(engine):
    player, mpv, _seen = engine
    order = []

    class _Surface:
        def bind(self, bound):
            order.append(('bind', bound))

        def release(self):
            order.append(('release', mpv.terminated))

    player.attach(_Surface())
    player.close()
    assert order == [('bind', player), ('release', False)]
    assert mpv.terminated
    assert mpv.commands == [('stop',)]
    assert player._on_playing is None
    assert player._on_stopped is None
    assert player._on_error is None


def test_real_libmpv_reports_failure_and_playback(monkeypatch):
    """Against the installed libmpv, when there is one."""
    try:
        import mpv  # noqa: F401
    except (ImportError, OSError):
        pytest.skip('libmpv is not installed')
    from tvhplayer.core.mpv_player import MpvPlayer

    player = MpvPlayer()
    seen = []
    done = threading.Event()

    def note(name):
        seen.append(name)
        done.set()

    player._mpv['ao'] = 'null'
    player.set_handlers(on_playing=lambda: note('playing'), on_error=lambda: note('error'))
    try:
        player.play('http://127.0.0.1:9/nothing.ts')
        assert done.wait(10)
        assert seen == ['error']
        done.clear()
        player.play('av://lavfi:sine=frequency=440:duration=5')
        assert done.wait(10)
        assert seen == ['error', 'playing']
        player.stop()
    finally:
        player.close()


@pytest.mark.parametrize('position', [None, 0.5])
def test_pause_and_resume_without_a_seekable_buffer(engine, position):
    player, mpv, _seen = engine
    assert player.timeshift() is None
    player.play('http://localhost/live')
    mpv.time_pos = position
    mpv.demuxer_cache_state = {'seekable-ranges': []}

    state = player.timeshift()
    assert state is not None and not state.paused
    assert state.behind == 0 and state.span == 0
    assert not player.skip(-10)

    # Use the same state-based toggle as the window's Pause/Resume command.
    player.set_paused(not player.timeshift().paused)
    assert mpv.pause is True and player.timeshift().paused
    player.set_paused(not player.timeshift().paused)
    assert mpv.pause is False and not player.timeshift().paused

    player.stop()
    assert player.timeshift() is None
    player.close()
    assert player.timeshift() is None


def test_disk_timeshift_stops_writes_at_limit_and_rearms_next_channel(engine, tmp_path):
    player, mpv, _seen = engine
    player.set_timeshift_store(str(tmp_path), 1000)
    assert 'cache-on-disk' not in mpv.props
    player.play('http://localhost/live')
    assert mpv.props['cache-on-disk'] is True
    assert mpv.props['demuxer-max-bytes'] == '150MiB'
    mpv.time_pos = 10.0
    mpv.pause = False
    mpv.demuxer_cache_state = {
        'seekable-ranges': [{'start': 0.0, 'end': 20.0}],
        'file-cache-bytes': 999,
    }
    assert player.timeshift().span == 20
    assert mpv.props['cache-on-disk'] is True
    mpv.demuxer_cache_state['file-cache-bytes'] = 1001
    assert player.timeshift().span == 20
    assert mpv.props['cache-on-disk'] is False
    player.timeshift()
    assert mpv.props['cache-on-disk'] is False
    player.play('http://localhost/next')
    assert mpv.props['cache-on-disk'] is True
    player.set_timeshift_store(None)
    assert mpv.props['cache-on-disk'] is True
    player.play('http://localhost/third')
    assert mpv.props['cache-on-disk'] is False


def _buffered_recording_engine(engine):
    player, mpv, _seen = engine
    player.play('http://localhost/live')
    mpv.time_pos = 10.0
    mpv.pause = True
    mpv.demuxer_cache_state = {'seekable-ranges': [{'start': 0.0, 'end': 30.0}]}
    return player, mpv


def test_buffer_recording_keeps_the_start_chosen_before_the_dialog(engine, tmp_path):
    player, mpv = _buffered_recording_engine(engine)
    point = player.buffer_recording_point()
    mpv.time_pos = 15.0
    path = tmp_path / 'recording.ts'
    recorder = player.record_buffer(path, point)
    assert mpv.messages[-1] == ('dump-cache', '10.0', 'no', str(path))
    assert recorder.is_running and not mpv.pause
    path.write_bytes(b'buffered footage')
    assert recorder.status().size == 16
    with pytest.raises(RuntimeError, match='already running'):
        player.record_buffer(tmp_path / 'second.ts', point)
    recorder.stop()
    assert not recorder.is_running
    assert recorder.status().return_code == 0
    recorder.stop()  # Does not stop a later recording.
    assert mpv.commands.count(('dump-cache', '0', '0', '')) == 1


@pytest.mark.parametrize('change', ['expired', 'channel', 'stopped'])
def test_buffer_recording_rejects_a_start_that_is_no_longer_available(engine, tmp_path, change):
    player, mpv = _buffered_recording_engine(engine)
    point = player.buffer_recording_point()
    if change == 'expired':
        mpv.demuxer_cache_state = {'seekable-ranges': [{'start': 11.0, 'end': 40.0}]}
    elif change == 'channel':
        player.play('http://localhost/other')
    else:
        player.stop()
    with pytest.raises(RuntimeError, match='changed|no longer buffered'):
        player.record_buffer(tmp_path / 'recording.ts', point)
    assert not mpv.messages


@pytest.mark.parametrize('action', ['stop', 'play', 'close'])
def test_buffer_recording_finishes_before_playback_changes(engine, tmp_path, action):
    player, mpv = _buffered_recording_engine(engine)
    recorder = player.record_buffer(tmp_path / 'recording.ts', player.buffer_recording_point())
    if action == 'play':
        player.play('http://localhost/other')
    else:
        getattr(player, action)()
    assert not recorder.is_running
    assert ('dump-cache', '0', '0', '') in mpv.commands


def test_buffer_recording_reports_async_write_failure(engine, tmp_path):
    player, mpv = _buffered_recording_engine(engine)
    recorder = player.record_buffer(tmp_path / 'recording.ts', player.buffer_recording_point())
    mpv.dump_future.set_exception(RuntimeError('Disk full'))
    status = recorder.status()
    assert not status.running and status.return_code == 1
    assert status.stderr == 'Disk full'
    recorder.stop()


@pytest.mark.parametrize('disk', [False, True])
def test_real_buffer_recording_contains_rewound_and_new_footage(tmp_path, disk):
    import shutil
    import subprocess
    import time

    try:
        import mpv  # noqa: F401
    except (ImportError, OSError):
        pytest.skip('libmpv is not installed')
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg is not installed')
    from tvhplayer.core.mpv_player import MpvPlayer

    source = tmp_path / 'source.ts'
    output = tmp_path / 'recording.ts'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
        '-t', '12', '-c:v', 'mpeg2video', '-g', '10', '-c:a', 'mp2', str(source),
    ], check=True, timeout=15)

    def wait_for(predicate):
        deadline = time.monotonic() + 10
        while not predicate():
            assert time.monotonic() < deadline, 'mpv did not reach the expected state'
            time.sleep(0.02)

    def frame_hashes(path):
        result = subprocess.run([
            'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
            '-f', 'framemd5', '-',
        ], capture_output=True, text=True, check=True, timeout=15)
        assert not result.stderr
        return [line.rsplit(',', 1)[-1].strip() for line in result.stdout.splitlines()
                if line and not line.startswith('#')]

    player = MpvPlayer()
    player._mpv['vo'] = 'null'
    player._mpv['ao'] = 'null'
    # A local fixture, with the same seekable cache as a network stream. Limit
    # readahead so recording must append new packets after dumping the cache.
    player._mpv['demuxer-seekable-cache'] = 'yes'
    player._mpv['demuxer-readahead-secs'] = 2
    player._mpv['cache-secs'] = 2
    if disk:
        player.set_timeshift_store(str(tmp_path / 'cache'), 100_000_000)
    try:
        player.play(str(source))
        wait_for(lambda: (player._mpv.time_pos or 0) >= 2.2)
        player.set_paused(True)
        assert player.skip(-1)
        wait_for(lambda: player._mpv.time_pos is not None and player._mpv.time_pos < 2)
        point = player.buffer_recording_point()
        assert point is not None
        initial_end = player._mpv.demuxer_cache_state['seekable-ranges'][0]['end']
        recorder = player.record_buffer(output, point)
        assert not player._mpv.pause
        wait_for(lambda: player._mpv.demuxer_cache_state['seekable-ranges'][0]['end'] > initial_end + 1)
        recorder.stop()
        assert recorder.status().return_code == 0
        original, recorded = frame_hashes(source), frame_hashes(output)
        first = original.index(recorded[0])
        last = original.index(recorded[-1])
        # It starts near the chosen position (rounded back to a keyframe),
        # before the live picture, and includes frames beyond the initial cache.
        assert max(0, int(point.position * 10) - 15) <= first <= int(point.position * 10)
        assert last > int(initial_end * 10)
        assert recorded == original[first:last + 1]
    finally:
        player.close()

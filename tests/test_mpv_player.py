import sys
import threading
import types

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
        if args == ('stop',):
            self.idle_active = True

    def command_async(self, *args):
        self.messages.append(args)

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

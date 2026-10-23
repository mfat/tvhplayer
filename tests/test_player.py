import sys
import types

from tvhplayer.core.vlc_player import VlcPlayer


class _Events:
    def __init__(self):
        self.handlers = {}

    def event_attach(self, kind, callback):
        self.handlers[kind] = callback


class _MediaPlayer:
    def __init__(self):
        self.media = None
        self.playing = False
        self.volume = None
        self.muted = False
        self.key_input = None
        self.mouse_input = None
        self.stopped = False
        self.window_id = None
        self._events = _Events()

    def event_manager(self):
        return self._events

    def set_xwindow(self, handle):
        self.window_id = handle

    def set_media(self, media):
        self.media = media

    def play(self):
        self.playing = True

    def stop(self):
        self.playing = False
        self.stopped = True

    def is_playing(self):
        return self.playing

    def audio_set_volume(self, value):
        self.volume = value

    def audio_get_mute(self):
        return self.muted

    def audio_set_mute(self, value):
        self.muted = bool(value)

    def video_set_key_input(self, value):
        self.key_input = value

    def video_set_mouse_input(self, value):
        self.mouse_input = value

    def set_hardware_decoding(self, value):
        return None


class _Instance:
    def __init__(self, player):
        self.player = player
        self.urls = []

    def media_player_new(self):
        return self.player

    def media_new(self, url):
        self.urls.append(url)
        return url


def _install_vlc(monkeypatch, instance):
    monkeypatch.setitem(
        sys.modules,
        'vlc',
        types.SimpleNamespace(
            Instance=lambda *args, **kwargs: instance,
            EventType=types.SimpleNamespace(
                MediaPlayerPlaying='playing',
                MediaPlayerStopped='stopped',
                MediaPlayerEndReached='ended',
                MediaPlayerEncounteredError='error',
            ),
            MediaStats=object,
            __version__='stub',
        ),
    )


def test_play_stop_mute_and_stopped_callback_is_scheduled(monkeypatch):
    media = _MediaPlayer()
    instance = _Instance(media)
    _install_vlc(monkeypatch, instance)
    engine = VlcPlayer()
    seen = []
    scheduled = []
    engine.set_handlers(
        lambda: seen.append('playing'),
        lambda: seen.append('stopped'),
        lambda fn: scheduled.append(fn),
        on_error=lambda: seen.append('error'),
    )
    engine.attach(7)
    assert media.window_id == 7
    assert media.key_input is False
    assert media.mouse_input is False

    engine.play('http://tv.example/stream')
    assert instance.urls == ['http://tv.example/stream']
    assert engine.is_playing() is True
    engine.set_volume(40)
    assert media.volume == 40
    assert engine.is_muted() is False
    engine.set_muted(True)
    assert engine.is_muted() is True

    media._events.handlers['stopped'](None)
    assert len(scheduled) == 1
    assert seen == []
    scheduled[0]()
    assert seen == ['stopped']

    media._events.handlers['ended'](None)
    scheduled[-1]()
    assert seen == ['stopped', 'stopped']

    media._events.handlers['error'](None)
    scheduled[-1]()
    assert seen == ['stopped', 'stopped', 'error']

    engine.stop()
    assert media.stopped is True
    assert engine.is_playing() is False


def test_close_stops_and_drops_the_player(monkeypatch):
    media = _MediaPlayer()
    _install_vlc(monkeypatch, _Instance(media))
    engine = VlcPlayer()
    engine.close()
    assert media.stopped is True
    assert engine.is_playing() is False
    engine.log_stats()

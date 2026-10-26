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


class _MarqueeOption:
    Enable, Text, Timeout, Position, X, Y, Opacity = range(7)


class _MarqueePlayer(_MediaPlayer):
    def __init__(self):
        super().__init__()
        self.marquee = {}
        self.log = []

    def video_set_marquee_int(self, option, value):
        self.marquee[option] = value

    def video_set_marquee_string(self, option, value):
        self.marquee[option] = value
        self.log.append(('text', value))

    def set_media(self, media):
        super().set_media(media)
        self.log.append(('media', media))

    def stop(self):
        super().stop()
        self.log.append(('stop', None))


def test_messages_are_drawn_over_the_picture_and_never_carry_over(monkeypatch):
    media = _MarqueePlayer()
    _install_vlc(monkeypatch, _Instance(media))
    sys.modules['vlc'].VideoMarqueeOption = _MarqueeOption
    engine = VlcPlayer()
    option = _MarqueeOption
    assert media.marquee[option.Enable] == 1
    assert media.marquee[option.Position] == 5

    engine.play('http://tv.example/one')
    engine.show_message('Volume 40', 2000)
    assert media.marquee[option.Timeout] == 2000
    assert media.marquee[option.Text] == 'Volume 40'

    # A new picture inherits the last text, so it is cleared before the next media.
    media.log.clear()
    engine.play('http://tv.example/two')
    assert media.log[:2] == [('text', ''), ('media', 'http://tv.example/two')]

    media.log.clear()
    engine.stop()
    assert media.log == [('text', ''), ('stop', None)]


def test_messages_are_skipped_without_marquee_support(monkeypatch):
    media = _MediaPlayer()
    _install_vlc(monkeypatch, _Instance(media))
    engine = VlcPlayer()
    engine.play('http://tv.example/one')
    engine.show_message('Muted')
    engine.stop()
    assert media.stopped is True


def test_deinterlace_back_to_automatic_starts_a_new_media_player(monkeypatch):
    first = _MediaPlayer()
    instance = _Instance(first)
    _install_vlc(monkeypatch, instance)
    engine = VlcPlayer()
    seen = []
    engine.set_handlers(lambda: seen.append('playing'), None, None)
    engine.attach(9)
    modes = []
    first.video_set_deinterlace = modes.append
    assert engine.set_deinterlace('on') is True
    assert modes == ['yadif2x']
    engine.play('http://tv.example/a')
    assert modes == ['yadif2x', 'yadif2x']
    assert engine.set_deinterlace('off') is True
    assert modes[-1] == ''

    second = _MediaPlayer()
    instance.player = second
    first.audio_get_volume = lambda: 30
    first.muted = True
    assert engine.set_deinterlace('auto') is False
    assert first.stopped is True
    assert second.window_id == 9
    assert second.volume == 30
    assert second.muted is True
    second._events.handlers['playing'](None)
    assert seen == ['playing']
    assert engine.deinterlace() == 'auto'

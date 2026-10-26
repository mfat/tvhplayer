"""libvlc engine. The window passes a URL and a native window id."""

from __future__ import annotations

import os
import sys
import traceback

from .player import DEINTERLACE_AUTO, DEINTERLACE_MODES, DEINTERLACE_OFF, DEINTERLACE_ON, NO_TRACK, Player
from .proxy import hide_http_proxy_from_vlc

VLC_ARGS = (
    '--avcodec-hw=any',
    '--file-caching=1000',
    '--network-caching=1000',
    '--no-video-title-show',
    '--no-snapshot-preview',
    # Deinterlace interlaced broadcasts, with the method VLC picks for the decoder in use.
    '--deinterlace=-1',
)
# The filter used when deinterlacing is always on: one picture per field, smooth on 1080i TV.
DEINTERLACE_FILTER = 'yadif2x'


class VlcPlayer(Player):
    """libvlc inside the Qt video widget."""

    def __init__(self):
        super().__init__()
        import vlc

        self._vlc = vlc
        self._events_bound = False
        self._window_id = None
        self._deinterlace = DEINTERLACE_AUTO
        # libvlc reads -1 and drops mute changes while no sound output is open,
        # so the wanted state is kept here and applied once the output opens.
        self._muted = False
        _prepare_frozen_plugins()
        # libvlc ignores no_proxy, so a local or LAN server would go through the proxy.
        hide_http_proxy_from_vlc()
        self._instance = vlc.Instance(list(VLC_ARGS))
        if not self._instance:
            raise RuntimeError('VLC Instance creation returned None')
        self._player = self._new_media_player()

    def _new_media_player(self):
        player = self._instance.media_player_new()
        if not player:
            raise RuntimeError('VLC media player creation returned None')
        self._player = player
        self._setup_marquee()
        return player

    def attach(self, window_id):
        self._window_id = window_id
        player = self._player
        if sys.platform.startswith('linux'):
            if window_id is not None:
                player.set_xwindow(int(window_id))
        elif sys.platform == 'win32':
            player.set_hwnd(int(window_id))
        elif sys.platform == 'darwin':
            player.set_nsobject(int(window_id))
        if hasattr(player, 'set_hardware_decoding'):
            player.set_hardware_decoding(True)
        self._release_input()

    def set_handlers(self, on_playing=None, on_stopped=None, schedule=None, on_error=None):
        super().set_handlers(on_playing, on_stopped, schedule, on_error)
        if self._events_bound or self._player is None:
            return
        manager = self._player.event_manager()
        event = self._vlc.EventType
        manager.event_attach(event.MediaPlayerPlaying, lambda _event: self._emit(self._on_playing))
        manager.event_attach(event.MediaPlayerStopped, lambda _event: self._emit(self._on_stopped))
        manager.event_attach(event.MediaPlayerEndReached, lambda _event: self._emit(self._on_stopped))
        error = getattr(event, 'MediaPlayerEncounteredError', None)
        if error is not None:
            manager.event_attach(error, lambda _event: self._emit(self._on_error))
        # Sent when a new sound output opens. libvlc must not be called on its thread.
        audio_volume = getattr(event, 'MediaPlayerAudioVolume', None)
        if audio_volume is not None:
            manager.event_attach(audio_volume, lambda _event: self._schedule(self._apply_mute))
        self._events_bound = True

    def audio_tracks(self):
        return self._tracks('audio_get_track_description', skip_disable=True)

    def audio_track(self):
        return self._track_id('audio_get_track')

    def set_audio_track(self, track_id):
        if self._player is not None:
            self._player.audio_set_track(int(track_id))

    def subtitle_tracks(self):
        return self._tracks('video_get_spu_description', skip_disable=True)

    def subtitle_track(self):
        return self._track_id('video_get_spu')

    def set_subtitle_track(self, track_id):
        if self._player is not None:
            self._player.video_set_spu(int(track_id))

    def _tracks(self, method, skip_disable=False):
        getter = getattr(self._player, method, None)
        if getter is None:
            return []
        tracks = []
        for track_id, name in getter() or []:
            if skip_disable and track_id == NO_TRACK:
                continue
            if isinstance(name, bytes):
                name = name.decode('utf-8', 'replace')
            tracks.append((int(track_id), str(name or f'Track {track_id}')))
        return tracks

    def _track_id(self, method):
        getter = getattr(self._player, method, None)
        if getter is None:
            return NO_TRACK
        try:
            return int(getter())
        except (TypeError, ValueError):
            return NO_TRACK

    def deinterlace(self):
        return self._deinterlace

    def set_deinterlace(self, mode):
        if mode not in DEINTERLACE_MODES or mode == self._deinterlace:
            return True
        self._deinterlace = mode
        if mode == DEINTERLACE_AUTO:
            # libvlc 3 can turn the filter on or off but not back to automatic;
            # a new media player starts automatic again.
            self._replace_media_player()
            return False
        self._apply_deinterlace()
        return True

    def _apply_deinterlace(self):
        if self._player is None or not hasattr(self._player, 'video_set_deinterlace'):
            return
        if self._deinterlace == DEINTERLACE_ON:
            self._player.video_set_deinterlace(DEINTERLACE_FILTER)
        elif self._deinterlace == DEINTERLACE_OFF:
            self._player.video_set_deinterlace('')

    def _replace_media_player(self):
        old = self._player
        volume = old.audio_get_volume() if hasattr(old, 'audio_get_volume') else None
        try:
            old.stop()
        except Exception:
            pass
        if hasattr(old, 'release'):
            old.release()
        self._new_media_player()
        self._events_bound = False
        self.set_handlers(self._on_playing, self._on_stopped, None, self._on_error)
        if self._window_id is not None:
            self.attach(self._window_id)
        if volume is not None and volume >= 0:
            self._player.audio_set_volume(volume)
        self._player.audio_set_mute(self._muted)

    def play(self, url: str):
        # Each new picture inherits the last marquee text. Clear it so the
        # previous channel's message does not reappear.
        self._set_marquee_text('')
        media = self._instance.media_new(url)
        self._player.set_media(media)
        self._apply_deinterlace()
        self._player.play()
        self._release_input()

    def stop(self):
        if self._player is not None:
            self._set_marquee_text('')
            self._player.stop()

    def show_message(self, text: str, duration_ms: int = 3000):
        """VLC's marquee: drawn into the video, so it shows in fullscreen too."""
        option = self._marquee_option()
        if option is None or self._player is None:
            return
        self._player.video_set_marquee_int(option.Timeout, int(duration_ms))
        self._set_marquee_text(text)

    def _marquee_option(self):
        option = getattr(self._vlc, 'VideoMarqueeOption', None)
        if option is None or not hasattr(self._player, 'video_set_marquee_int'):
            return None
        return option

    def _setup_marquee(self):
        """Enable the marquee once. The player keeps it for every later picture."""
        option = self._marquee_option()
        if option is None:
            return
        set_int = self._player.video_set_marquee_int
        set_int(option.Enable, 1)
        # Top left. Size 0 keeps VLC's default, which scales with the video height.
        set_int(option.Position, 5)
        set_int(option.X, 20)
        set_int(option.Y, 20)
        set_int(option.Opacity, 255)

    def _set_marquee_text(self, text):
        option = self._marquee_option()
        if option is not None and self._player is not None:
            self._player.video_set_marquee_string(option.Text, text)

    def is_playing(self) -> bool:
        return bool(self._player and self._player.is_playing())

    def set_volume(self, value: int):
        self._player.audio_set_volume(int(value))

    def is_muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool):
        self._muted = bool(muted)
        self._apply_mute()

    def _apply_mute(self):
        player = self._player
        if player is None:
            return
        state = player.audio_get_mute()
        if state is None or state < 0 or bool(state) != self._muted:
            player.audio_set_mute(self._muted)

    def log_stats(self):
        """Print decoded-picture counts once a stream is actually playing."""
        player = self._player
        if player is None or not player.is_playing():
            return
        try:
            media = player.get_media()
            if not media:
                print('No media currently playing')
                return
            try:
                stats = media.get_stats()
            except TypeError:
                stats = self._vlc.MediaStats()
                media.get_stats(stats)
            print('VLC Playback Statistics:')
            print(f'Decoded video blocks: {stats.decoded_video}')
            print(f'Displayed pictures: {stats.displayed_pictures}')
            print(f'Lost pictures: {stats.lost_pictures}')
            if hasattr(player, 'get_role'):
                print(f'Media player role: {player.get_role()}')
            print("Hardware acceleration is active if you see 'Using ... for hardware decoding' in the logs above")
            print('For more details, run VLC with the same content and use:')
            print('Tools -> Messages -> Info to see which decoder is being used')
        except Exception as exc:
            print(f'Error checking hardware acceleration: {exc}')
            print(f'Traceback: {traceback.format_exc()}')

    def close(self):
        player = self._player
        self._player = None
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
            if hasattr(player, 'release'):
                player.release()
        instance = self._instance
        self._instance = None
        if instance is not None and hasattr(instance, 'release'):
            instance.release()

    def _release_input(self):
        """Leave mouse and keyboard to Qt."""
        player = self._player
        if player is None:
            return
        try:
            player.video_set_key_input(False)
            player.video_set_mouse_input(False)
        except Exception as exc:
            print(f'Debug: Could not disable VLC input grabbing: {exc}')


def _prepare_frozen_plugins():
    """Point a PyInstaller build at the bundled VLC plugins."""
    if not getattr(sys, 'frozen', False):
        return
    base_path = sys._MEIPASS
    plugin_path = os.path.join(base_path, 'vlc', 'plugins')
    os.environ['VLC_PLUGIN_PATH'] = plugin_path
    if sys.platform.startswith('linux'):
        os.environ['LD_LIBRARY_PATH'] = base_path

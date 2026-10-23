"""libvlc engine. The window passes a URL and a native window id."""

from __future__ import annotations

import os
import sys
import traceback

from .player import Player

VLC_ARGS = (
    '--avcodec-hw=any',
    '--file-caching=1000',
    '--network-caching=1000',
    '--no-video-title-show',
    '--no-snapshot-preview',
)


class VlcPlayer(Player):
    """libvlc inside the Qt video widget."""

    def __init__(self):
        super().__init__()
        import vlc

        self._vlc = vlc
        self._events_bound = False
        _prepare_frozen_plugins()
        self._instance = vlc.Instance(list(VLC_ARGS))
        if not self._instance:
            raise RuntimeError('VLC Instance creation returned None')
        self._player = self._instance.media_player_new()
        if not self._player:
            raise RuntimeError('VLC media player creation returned None')

    def attach(self, window_id):
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
        self._events_bound = True

    def play(self, url: str):
        media = self._instance.media_new(url)
        self._player.set_media(media)
        self._player.play()
        self._release_input()

    def stop(self):
        if self._player is not None:
            self._player.stop()

    def is_playing(self) -> bool:
        return bool(self._player and self._player.is_playing())

    def set_volume(self, value: int):
        self._player.audio_set_volume(int(value))

    def is_muted(self) -> bool:
        return bool(self._player and self._player.audio_get_mute())

    def set_muted(self, muted: bool):
        self._player.audio_set_mute(bool(muted))

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

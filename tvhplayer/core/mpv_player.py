"""libmpv engine. The window passes a URL and an OpenGL video widget.

mpv runs with ``vo=libmpv``: it opens no window of its own. The widget owns
the OpenGL context and asks this engine for a render context once it has one.
"""

from __future__ import annotations

import locale

from .player import DEINTERLACE_AUTO, DEINTERLACE_MODES, DEINTERLACE_OFF, DEINTERLACE_ON, NO_TRACK, Player
from .proxy import hide_http_proxy_from_vlc, stream_proxy

MPV_OPTIONS = {
    'vo': 'libmpv',
    'hwdec': 'auto-safe',
    # A player inside the app: no mpv keys, controls, scripts or config files.
    'input_default_bindings': False,
    'input_vo_keyboard': False,
    'load_scripts': False,
    'config': False,
    'idle': True,
    'keep_open': False,
    'audio_client_name': 'TVHplayer',
    # mpv hands a frame over this long before its display time, and the widget's
    # paint then waits out the rest. Every repaint of a resize waited up to a frame.
    'video_timing_offset': 0,
}
# mpv's built-in Lua scripts, which load_scripts does not cover. A libmpv built
# without Lua, as in the Flatpak, has neither the scripts nor these options.
LUA_SCRIPT_OPTIONS = {'osc': False, 'ytdl': False}
DEINTERLACE_VALUES = {DEINTERLACE_AUTO: 'auto', DEINTERLACE_ON: 'yes', DEINTERLACE_OFF: 'no'}


class MpvPlayer(Player):
    """libmpv drawing into the window's OpenGL video widget."""

    def __init__(self):
        super().__init__()
        import mpv

        self._mpv_module = mpv
        self._surface = None
        self._deinterlace = DEINTERLACE_AUTO
        # Set by play(); the first picture of that stream reports playback started.
        self._waiting_for_picture = False
        # The proxy goes to mpv per stream, so a local or LAN server is reached directly.
        hide_http_proxy_from_vlc()
        # QApplication sets the numeric locale from the desktop; libmpv refuses anything but C.
        locale.setlocale(locale.LC_NUMERIC, 'C')
        self._mpv = mpv.MPV(log_handler=_log, loglevel='warn', **MPV_OPTIONS)
        # Set after creation: an unknown option at creation leaves a running mpv behind.
        for name, value in LUA_SCRIPT_OPTIONS.items():
            try:
                self._mpv[name] = value
            except AttributeError:
                pass
        self._mpv.register_event_callback(self._on_event)

    def attach(self, surface):
        """``surface`` is the video widget. It creates the render context when its GL context exists."""
        self._surface = surface
        surface.bind(self)

    def create_render_context(self, get_proc_address, wl_display=None):
        """Called by the video widget with its OpenGL context current.

        ``get_proc_address(name: bytes) -> int`` looks up an OpenGL function.
        ``wl_display`` lets mpv open VA-API on Wayland, so decoded frames stay on the GPU.
        """
        mpv = self._mpv_module
        # Kept on self: ctypes does not hold the C callback alive on its own.
        self._proc_address = mpv.MpvGlGetProcAddressFn(lambda _ctx, name: get_proc_address(name) or None)
        params = {}
        if wl_display:
            params['wl_display'] = wl_display
        return mpv.MpvRenderContext(
            self._mpv, 'opengl', opengl_init_params={'get_proc_address': self._proc_address}, **params
        )

    def _on_event(self, event):
        mpv = self._mpv_module
        kind = event.event_id.value
        if kind == mpv.MpvEventID.PLAYBACK_RESTART:
            if self._waiting_for_picture:
                self._waiting_for_picture = False
                self._emit(self._on_playing)
        elif kind == mpv.MpvEventID.END_FILE:
            reason = event.data.reason
            if reason == mpv.MpvEventEndFile.ERROR:
                self._waiting_for_picture = False
                self._emit(self._on_error)
            elif reason in (mpv.MpvEventEndFile.EOF, mpv.MpvEventEndFile.ABORTED):
                self._emit(self._on_stopped)

    def play(self, url: str):
        self._waiting_for_picture = True
        self._mpv['http-proxy'] = stream_proxy(url)
        self._mpv.loadfile(url)

    def stop(self):
        self._waiting_for_picture = False
        self._mpv.command('stop')

    def is_playing(self) -> bool:
        try:
            return not self._mpv.idle_active
        except Exception:
            return False

    def set_volume(self, value: int):
        self._mpv.volume = max(0, min(100, int(value)))

    def is_muted(self) -> bool:
        return bool(self._mpv.mute)

    def set_muted(self, muted: bool):
        self._mpv.mute = bool(muted)

    def audio_tracks(self):
        return self._tracks('audio')

    def audio_track(self):
        return _track_id(self._mpv.aid)

    def set_audio_track(self, track_id):
        self._mpv.aid = int(track_id)

    def subtitle_tracks(self):
        return self._tracks('sub')

    def subtitle_track(self):
        return _track_id(self._mpv.sid)

    def set_subtitle_track(self, track_id):
        self._mpv.sid = 'no' if int(track_id) == NO_TRACK else int(track_id)

    def _tracks(self, kind):
        tracks = []
        for track in self._mpv.track_list or []:
            if track.get('type') != kind:
                continue
            track_id = int(track['id'])
            parts = [str(part) for part in (track.get('title'), track.get('lang')) if part]
            tracks.append((track_id, ' - '.join(parts) or f'Track {track_id}'))
        return tracks

    def deinterlace(self):
        return self._deinterlace

    def set_deinterlace(self, mode):
        if mode not in DEINTERLACE_MODES:
            return True
        self._deinterlace = mode
        value = DEINTERLACE_VALUES[mode]
        if value == 'auto' and not self._has_deinterlace_auto():
            # mpv before 0.38 (Ubuntu 24.04, the AppImage) has no auto. Its yes
            # leaves progressive pictures alone when VA-API decodes, as auto does.
            value = 'yes'
        self._mpv.deinterlace = value
        return True

    def _has_deinterlace_auto(self):
        try:
            choices = self._mpv.option_info('deinterlace').get('choices') or ()
        except Exception:
            return True
        return 'auto' in choices

    def show_message(self, text: str, duration_ms: int = 3000):
        """mpv's on-screen text: drawn into the picture, so it shows in fullscreen too.

        Sent without waiting: while a stream opens, mpv answers late, and the
        window could not draw frames meanwhile.
        """
        self._mpv.command_async('show-text', text, str(int(duration_ms)))

    def log_stats(self):
        if not self.is_playing():
            return
        mpv = self._mpv
        surface = self._surface
        print('mpv Playback Statistics:')
        if surface is not None:
            print(f'Video output: libmpv render API into a Qt OpenGL widget ({surface.platform_name()})')
        print(f'Video codec: {mpv.video_codec}')
        print(f'Hardware decoding: {mpv.hwdec_current or "no"}')
        print(f'Dropped frames: {mpv.frame_drop_count} (decoder: {mpv.decoder_frame_drop_count})')

    def close(self):
        surface, self._surface = self._surface, None
        # The render context must go before the mpv handle, with its GL context current.
        if surface is not None:
            surface.release()
        player, self._mpv = self._mpv, None
        if player is not None:
            player.terminate()


def _track_id(value):
    if isinstance(value, bool) or value is None:
        return NO_TRACK
    try:
        return int(value)
    except (TypeError, ValueError):
        return NO_TRACK


def _log(level, prefix, text):
    print(f'Debug: mpv {level} {prefix}: {text.strip()}')

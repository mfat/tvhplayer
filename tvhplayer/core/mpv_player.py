"""libmpv engine. The window passes a URL and an OpenGL video widget.

mpv runs with ``vo=libmpv``: it opens no window of its own. The widget owns
the OpenGL context and asks this engine for a render context once it has one.
"""

from __future__ import annotations

import locale
from pathlib import Path

from .player import (
    DEINTERLACE_AUTO, DEINTERLACE_MODES, DEINTERLACE_OFF, DEINTERLACE_ON, NO_TRACK, Player, Timeshift,
)
from .proxy import hide_http_proxy, stream_proxy

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
# Seconds of stream ffmpeg reads to learn the tracks; 0 leaves it to ffmpeg. Much
# shorter can leave a sound track without the details it needs to play.
FAST_START_ANALYZE_SECONDS = 0.5
# mpv's own buffer sizes, used again when timeshift leaves the disk.
MEMORY_AHEAD_BYTES = '150MiB'
MEMORY_BEHIND_BYTES = '50MiB'
# The newest buffered picture runs about a second ahead of the one shown, so
# "live" is anything this close to it, and going live stops this short of it.
LIVE_SLACK_SECONDS = 3.0
LIVE_MARGIN_SECONDS = 1.0


class MpvPlayer(Player):
    """libmpv drawing into the window's OpenGL video widget."""

    def __init__(self):
        super().__init__()
        import mpv

        self._mpv_module = mpv
        self._surface = None
        self._deinterlace = DEINTERLACE_AUTO
        self._last_buffered = None
        # Set by play(); the first picture of that stream reports playback started.
        self._waiting_for_picture = False
        # The proxy goes to mpv per stream, so a local or LAN server is reached directly.
        hide_http_proxy()
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
        # mpv keeps pause across files; a new channel always starts playing.
        self._mpv.pause = False
        self._last_buffered = None
        self._mpv.loadfile(url)

    def stop(self):
        self._waiting_for_picture = False
        self._last_buffered = None
        self._mpv.command('stop')
        self._mpv.pause = False

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

    def set_fast_start(self, on):
        self._mpv['demuxer-lavf-analyzeduration'] = FAST_START_ANALYZE_SECONDS if on else 0

    def _buffered(self):
        """``(position, start, end)`` of the buffered stretch being played, or None.

        While a seek or pause settles, mpv can report no position for a moment;
        the last reading stands in for it.
        """
        try:
            if self._mpv is None or self._mpv.idle_active:
                self._last_buffered = None
                return None
            position = self._mpv.time_pos
            state = self._mpv.demuxer_cache_state or {}
        except Exception:
            return self._last_buffered
        ranges = [(r['start'], r['end']) for r in state.get('seekable-ranges') or []]
        here = [] if position is None else [r for r in ranges if r[0] <= position <= r[1] + LIVE_MARGIN_SECONDS]
        if not here:
            return self._last_buffered
        start, end = max(here, key=lambda r: r[1])
        self._last_buffered = (position, start, end)
        return self._last_buffered

    def timeshift(self):
        mpv = self._mpv
        buffered = self._buffered()
        if mpv is None or buffered is None:
            return None
        position, start, end = buffered
        behind = end - position
        return Timeshift(bool(mpv.pause), 0.0 if behind < LIVE_SLACK_SECONDS else behind, end - start)

    def set_paused(self, paused):
        self._mpv.pause = bool(paused)

    def skip(self, seconds):
        buffered = self._buffered()
        if buffered is None:
            return False
        position, start, end = buffered
        target = max(start, min(position + seconds, end - LIVE_MARGIN_SECONDS))
        if abs(target - position) < 0.5:
            return False
        self._seek_to(target)
        return True

    def go_live(self):
        self._mpv.pause = False
        buffered = self._buffered()
        if buffered is not None and buffered[2] - buffered[0] >= LIVE_SLACK_SECONDS:
            self._seek_to(buffered[2] - LIVE_MARGIN_SECONDS)

    def _seek_to(self, seconds):
        # mpv counts a negative absolute seek from the end; the buffer can start at -0.0000002.
        self._mpv.command('seek', f'{max(seconds, 0.0):.3f}', 'absolute')

    def set_timeshift_store(self, folder, size_bytes=0):
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            half = max(int(size_bytes) // 2, 1)
            self._mpv['cache'] = 'yes'
            self._mpv['demuxer-cache-dir'] = str(folder)
            self._mpv['demuxer-max-bytes'] = half
            self._mpv['demuxer-max-back-bytes'] = half
            self._mpv['cache-on-disk'] = True
        else:
            self._mpv['cache-on-disk'] = False
            self._mpv['cache'] = 'auto'
            self._mpv['demuxer-max-bytes'] = MEMORY_AHEAD_BYTES
            self._mpv['demuxer-max-back-bytes'] = MEMORY_BEHIND_BYTES

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
        # Quiesce playback first; native callbacks must not reach a closing Qt window.
        self._on_playing = self._on_stopped = self._on_error = None
        player = self._mpv
        if player is not None:
            try:
                player.command('stop')
            except (OSError, RuntimeError):
                pass
        surface, self._surface = self._surface, None
        # Release the GL context (and its live ctypes callback) before the mpv handle.
        if surface is not None:
            surface.release()
        self._mpv = None
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

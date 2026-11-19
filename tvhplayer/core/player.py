"""Playback engine used by the desktop window.

The window owns the video widget. An engine opens a URL in that widget.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

# Deinterlacing: the engine decides from the stream, always on, or off.
DEINTERLACE_AUTO = 'auto'
DEINTERLACE_ON = 'on'
DEINTERLACE_OFF = 'off'
DEINTERLACE_MODES = (DEINTERLACE_AUTO, DEINTERLACE_ON, DEINTERLACE_OFF)

# mpv --hwdec. Software on Windows (libmpv/OpenGL path); auto-safe elsewhere.
_HARDWARE_DECODING_COMMON: Tuple[Tuple[str, str], ...] = (
    ('Software', 'no'),
    ('Hardware — automatic', 'auto-safe'),
    ('Hardware — copy-back', 'auto-copy'),
    ('NVIDIA — copy-back', 'nvdec-copy'),
)
_HARDWARE_DECODING_WINDOWS: Tuple[Tuple[str, str], ...] = (
    ('Direct3D 11 — copy-back', 'd3d11va-copy'),
)
HARDWARE_DECODING_MODES = tuple(dict.fromkeys(
    mode for _, mode in _HARDWARE_DECODING_COMMON + _HARDWARE_DECODING_WINDOWS
))


def hardware_decoding_default(platform: Optional[str] = None) -> str:
    """Default ``hwdec`` for new configs on this platform."""
    platform = sys.platform if platform is None else platform
    return 'no' if platform == 'win32' else 'auto-safe'


HARDWARE_DECODING_DEFAULT = hardware_decoding_default()


def hardware_decoding_choices(platform: Optional[str] = None) -> Sequence[Tuple[str, str]]:
    """Labels and mpv ``hwdec`` values for Settings on this platform."""
    platform = sys.platform if platform is None else platform
    if platform == 'win32':
        return _HARDWARE_DECODING_COMMON + _HARDWARE_DECODING_WINDOWS
    return _HARDWARE_DECODING_COMMON


# The track id that turns subtitles off.
NO_TRACK = -1


class Timeshift(NamedTuple):
    """Where the picture is in what the player has buffered of a live stream."""
    paused: bool
    # Seconds behind live; 0 when live.
    behind: float
    # Seconds buffered in all, from the oldest picture kept to live.
    span: float


class BufferRecordingPoint(NamedTuple):
    """A position in one particular playback session, captured before the recording dialog."""
    stream: int
    position: float
    behind: float


class Player(ABC):
    """Play one media URL into the window's video surface."""

    def __init__(self):
        self._on_playing: Optional[Callable[[], None]] = None
        self._on_stopped: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[], None]] = None
        self._schedule: Callable[[Callable[[], None]], None] = lambda fn: fn()

    def set_handlers(self, on_playing=None, on_stopped=None, schedule=None, on_error=None):
        """Register start, stop, and failure callbacks.

        ``schedule`` runs a callback on the UI thread. The default calls it
        immediately. ``on_stopped`` also covers the media ending on its own.
        ``on_error`` runs when the engine cannot open the stream.
        """
        self._on_playing = on_playing
        self._on_stopped = on_stopped
        self._on_error = on_error
        if schedule is not None:
            self._schedule = schedule

    def _emit(self, callback):
        if callback is not None:
            self._schedule(callback)

    @abstractmethod
    def attach(self, window_id):
        """Draw video into this native window id, or the video widget for libmpv."""

    @abstractmethod
    def play(self, url: str):
        """Open ``url`` and start playback."""

    @abstractmethod
    def stop(self):
        """Stop playback."""

    @abstractmethod
    def is_playing(self) -> bool:
        """True while a picture or sound is coming out."""

    @abstractmethod
    def set_volume(self, value: int):
        """Set volume. The window uses 0–100."""

    @abstractmethod
    def is_muted(self) -> bool:
        """True when sound is silenced."""

    @abstractmethod
    def set_muted(self, muted: bool):
        """Silence or restore sound."""

    def audio_tracks(self) -> List[Tuple[int, str]]:
        """``(id, name)`` of each sound track in the stream. The default has none."""
        return []

    def audio_track(self) -> int:
        return NO_TRACK

    def set_audio_track(self, track_id: int):
        """Play this sound track. The default does nothing."""

    def subtitle_tracks(self) -> List[Tuple[int, str]]:
        """``(id, name)`` of each subtitle track, teletext pages included. The default has none."""
        return []

    def subtitle_track(self) -> int:
        return NO_TRACK

    def set_subtitle_track(self, track_id: int):
        """Show this subtitle track, or none with ``NO_TRACK``. The default does nothing."""

    def deinterlace(self) -> str:
        return DEINTERLACE_AUTO

    def set_deinterlace(self, mode: str) -> bool:
        """Choose one of ``DEINTERLACE_MODES``.

        Returns True when the picture already changed, False when it takes
        effect the next time a stream starts.
        """
        return False

    def set_hardware_decoding(self, mode: str):
        """Choose hardware decoding for the next stream. The default does nothing."""

    def set_fast_start(self, on: bool):
        """Probe new streams briefly, for a quicker first picture. Applies from the next stream.

        The default does nothing.
        """

    def timeshift(self) -> Optional[Timeshift]:
        """Where the picture is while the stream can pause and go back, else None."""
        return None

    def set_paused(self, paused: bool):
        """Pause or resume the stream. The default does nothing."""

    def skip(self, seconds: float) -> bool:
        """Move within what is buffered, back when negative. False when it cannot."""
        return False

    def go_live(self):
        """Resume at the newest buffered picture. The default does nothing."""

    def set_timeshift_store(self, folder: Optional[str], size_bytes: int = 0):
        """Buffer streams in ``folder`` on disk up to ``size_bytes``, or in memory with None.

        Applies from the next stream. The default does nothing.
        """

    def buffer_recording_point(self):
        """Capture a buffered recording start, or None when unavailable."""
        return None

    def record_buffer(self, file_path, point):
        """Record from a captured position through live; return a local recorder."""
        raise RuntimeError('Recording from the timeshift buffer is unavailable')

    def show_message(self, text: str, duration_ms: int = 3000):
        """Draw short text over the picture, then let it fade. The default does nothing."""

    def log_stats(self):
        """Print engine-specific playback stats. The default does nothing."""

    def media_info(self):
        """Return a cancellable Future containing a plain-text media snapshot.

        Submitting the request must not wait for the playback engine.
        """
        from concurrent.futures import Future

        result = Future()
        result.set_result(None)
        return result

    def begin_shutdown(self):
        """Quiesce playback without waiting; close() releases native resources later."""
        self._on_playing = self._on_stopped = self._on_error = None

    def close(self):
        """Release the engine. The default does nothing."""

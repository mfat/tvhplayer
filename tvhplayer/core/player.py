"""Playback engine used by the desktop window.

The window owns the video widget. An engine opens a URL in that widget.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Tuple

# Deinterlacing: the engine decides from the stream, always on, or off.
DEINTERLACE_AUTO = 'auto'
DEINTERLACE_ON = 'on'
DEINTERLACE_OFF = 'off'
DEINTERLACE_MODES = (DEINTERLACE_AUTO, DEINTERLACE_ON, DEINTERLACE_OFF)
# The track id that turns subtitles off.
NO_TRACK = -1


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

    def show_message(self, text: str, duration_ms: int = 3000):
        """Draw short text over the picture, then let it fade. The default does nothing."""

    def log_stats(self):
        """Print engine-specific playback stats. The default does nothing."""

    def close(self):
        """Release the engine. The default does nothing."""

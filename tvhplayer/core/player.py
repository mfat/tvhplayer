"""Playback engine used by the desktop window.

The window owns the video widget. An engine opens a URL in that widget.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional


class Player(ABC):
    """Play one media URL into a native window id."""

    def __init__(self):
        self._on_playing: Optional[Callable[[], None]] = None
        self._on_stopped: Optional[Callable[[], None]] = None
        self._schedule: Callable[[Callable[[], None]], None] = lambda fn: fn()

    def set_handlers(self, on_playing=None, on_stopped=None, schedule=None):
        """Register start and stop callbacks.

        ``schedule`` runs a callback on the UI thread. The default calls it
        immediately. ``on_stopped`` also covers the media ending on its own.
        """
        self._on_playing = on_playing
        self._on_stopped = on_stopped
        if schedule is not None:
            self._schedule = schedule

    def _emit(self, callback):
        if callback is not None:
            self._schedule(callback)

    @abstractmethod
    def attach(self, window_id):
        """Draw video into this native window id."""

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

    def log_stats(self):
        """Print engine-specific playback stats. The default does nothing."""

    def close(self):
        """Release the engine. The default does nothing."""

"""A local recording supplied by mpv's continuous cache dump."""

import os
import time

from .recorder import RecorderStatus, STALL_LIMIT


class BufferRecorder:
    """Expose the local-recorder interface for an asynchronous mpv cache dump.

    The future completes when the stream closes, writing fails, or stop closes
    the dump. Keeping it lets the UI detect a channel change or a write error.
    """

    def __init__(self, file_path, future, stop_dump):
        self.file_path = str(file_path)
        self.started_at = time.time()
        self._future = future
        self._stop_dump = stop_dump
        self.last_size = None
        self.stall_count = 0

    @property
    def is_running(self):
        return not self._future.done()

    def stop(self):
        if self.is_running:
            # An empty filename closes the muxer and completes the original
            # command. Cancelling python-mpv's future loses its completion reply.
            self._stop_dump()
            # A write failure must not prevent stopping/changing playback.
            # Keep the exception available through status() for the monitor.
            self._future.exception(timeout=5)

    def status(self):
        exists = os.path.exists(self.file_path)
        size = os.path.getsize(self.file_path) if exists else 0
        running = self.is_running
        if running and exists and size == self.last_size:
            self.stall_count += 1
        else:
            self.stall_count = 0
        self.last_size = size
        error = self._future.exception() if not running else None
        return RecorderStatus(
            file_path=self.file_path, exists=exists, size=size,
            elapsed=time.time() - self.started_at, running=running,
            stalled=self.stall_count > STALL_LIMIT,
            return_code=None if running else (1 if error else 0),
            stderr=str(error) if error else '',
        )

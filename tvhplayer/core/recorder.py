"""Local ffmpeg recording. No Qt imports."""

from __future__ import annotations

import base64
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from .processes import no_window_flags
from .proxy import child_env

log = logging.getLogger(__name__)

STALL_LIMIT = 5
# Keep the tail. A live stream can warn for hours; the pipe only has to stay drained.
_STDERR_LIMIT = 64 * 1024


# File extension -> (label, description, ffmpeg output options). The extension picks the format.
RECORDING_FORMATS = {
    'ts': (
        'MPEG-TS (.ts)',
        'The stream exactly as the server sends it. Plays everywhere, even if the recording is cut off.',
        ['-c', 'copy', '-f', 'mpegts'],
    ),
    'mp4': (
        'MP4 (.mp4)',
        'Video copied, audio converted to AAC. Plays on phones and TVs; a recording cut off by a crash cannot be played.',
        ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-f', 'mp4'],
    ),
    'mkv': (
        'Matroska (.mkv)',
        'The stream as the server sends it, in a file that is quick to seek in.',
        ['-c', 'copy', '-f', 'matroska'],
    ),
}
DEFAULT_FORMAT = 'ts'


def recording_format(file_path):
    ext = os.path.splitext(str(file_path))[1].lower().lstrip('.')
    return ext if ext in RECORDING_FORMATS else DEFAULT_FORMAT


def parse_ffmpeg_options(text):
    """Split the user's extra ffmpeg output options; raises ValueError when they do not parse."""
    return shlex.split(text or '')


@dataclass
class RecorderStatus:
    file_path: str
    exists: bool
    size: int
    elapsed: float
    running: bool
    stalled: bool
    return_code: Optional[int]
    stderr: str = ''


def build_ffmpeg_command(stream_url, file_path, username='', password='', extra_options=()):
    """Return the ffmpeg argv used for a local recording.

    ``extra_options`` come after the format's own output options, so they win.
    """
    cmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel', 'warning',
        '-nostats',
        '-y',
    ]
    parsed = urlparse(stream_url)
    if (username or password) and not parsed.username and 'ticket' not in parse_qs(parsed.query):
        token = base64.b64encode(f'{username}:{password}'.encode('utf-8')).decode('ascii')
        cmd.extend(['-headers', f'Authorization: Basic {token}\r\n'])
    cmd.extend([
        '-i', stream_url,
        '-analyzeduration', '10M',
        '-probesize', '10M',
    ])
    cmd.extend(RECORDING_FORMATS[recording_format(file_path)][2])
    cmd.extend(extra_options)
    cmd.append(str(file_path))
    return cmd


def free_path(path, taken=()) -> str:
    """``path``, or ``name_2.ext``, ``name_3.ext``... when it exists or is in ``taken``.

    ffmpeg runs with ``-y``, so a new recording must never reuse a file name.
    """
    stem, ext = os.path.splitext(str(path))
    candidate, number = str(path), 1
    while os.path.lexists(candidate) or candidate in taken:
        number += 1
        candidate = f'{stem}_{number}{ext}'
    return candidate


def redact_command(cmd: List[str]) -> str:
    """Hide Basic-auth tokens and user:pass in URLs for logs."""
    redacted = []
    skip_next = False
    for index, part in enumerate(cmd):
        if skip_next:
            skip_next = False
            redacted.append('Authorization: Basic ***')
            continue
        if part == '-headers':
            redacted.append(part)
            skip_next = True
            continue
        if '://' in part and '@' in part:
            parsed = urlparse(part)
            host = parsed.hostname or ''
            port = f':{parsed.port}' if parsed.port else ''
            redacted.append(parsed._replace(netloc=f'***:***@{host}{port}').geturl())
            continue
        redacted.append(part)
    return ' '.join(redacted)


class LocalRecorder:
    # Windows has no SIGTERM: terminate() kills ffmpeg before it writes the end
    # of the file, which an MP4 needs. There ffmpeg is asked to quit with 'q'.
    stops_with_q = sys.platform == 'win32'

    def __init__(self, ffmpeg_executable='ffmpeg'):
        self.ffmpeg_executable = ffmpeg_executable
        self.process = None
        self.file_path = None
        self.started_at = None
        self.last_size = None
        self.stall_count = 0
        self._stderr = bytearray()
        self._stderr_lock = threading.Lock()
        self._stderr_thread = None

    @property
    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, stream_url, file_path, username='', password='', extra_options=()):
        self.stop()
        cmd = build_ffmpeg_command(stream_url, file_path, username, password, extra_options)
        if cmd[0] != self.ffmpeg_executable:
            cmd[0] = self.ffmpeg_executable
        log.info('Starting local recording: %s', redact_command(cmd))
        # stdout is unused. stderr has to be drained: the kernel pipe is 64 KB,
        # and a full pipe blocks ffmpeg so SIGTERM never reaches the trailer.
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if self.stops_with_q else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=child_env(stream_url),
            creationflags=no_window_flags(),
        )
        self.file_path = str(file_path)
        self.started_at = time.time()
        self.last_size = None
        self.stall_count = 0
        with self._stderr_lock:
            self._stderr = bytearray()
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(self.process.stderr,),
            daemon=True,
        )
        self._stderr_thread.start()
        return cmd

    def _read_stderr(self, pipe):
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                with self._stderr_lock:
                    self._stderr.extend(chunk)
                    extra = len(self._stderr) - _STDERR_LIMIT
                    if extra > 0:
                        del self._stderr[:extra]
        except Exception:
            log.debug('stderr reader stopped', exc_info=True)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _stderr_text(self) -> str:
        with self._stderr_lock:
            data = bytes(self._stderr)
        return data.decode('utf-8', 'replace')

    def stop(self, timeout=5):
        process = self.process
        thread = self._stderr_thread
        self.process = None
        self._stderr_thread = None
        if process is None:
            return
        if process.poll() is None and self.stops_with_q and process.stdin is not None:
            try:
                process.stdin.write(b'q')
                process.stdin.flush()
                process.stdin.close()
                process.wait(timeout=timeout)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        if thread is not None:
            thread.join(timeout=1)
        self.last_size = None
        self.stall_count = 0

    def status(self) -> RecorderStatus:
        path = self.file_path or ''
        exists = bool(path) and os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        elapsed = time.time() - self.started_at if self.started_at else 0.0
        return_code = self.process.poll() if self.process is not None else None
        running = return_code is None and self.process is not None
        stalled = False
        if running and exists:
            if self.last_size is not None and size == self.last_size:
                self.stall_count += 1
                stalled = self.stall_count > STALL_LIMIT
            else:
                self.stall_count = 0
            self.last_size = size
        stderr = ''
        if return_code is not None and self.process is not None:
            thread = self._stderr_thread
            if thread is not None:
                thread.join(timeout=1)
            stderr = self._stderr_text()
        return RecorderStatus(
            file_path=path,
            exists=exists,
            size=size,
            elapsed=elapsed,
            running=running,
            stalled=stalled,
            return_code=return_code,
            stderr=stderr,
        )

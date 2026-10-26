"""Converting recordings for editing with ffmpeg. No Qt imports.

An edit-friendly copy has a constant frame rate and a keyframe every second,
so video editors seek and scrub through it smoothly. The frame rate comes
from the recording; the user's options pick the encoder and its quality.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from fractions import Fraction
from typing import List, Optional

from .recorder import parse_ffmpeg_options

log = logging.getLogger(__name__)

DEFAULT_CONVERT_OPTIONS = '-c:v libx264 -preset veryfast -crf 18 -c:a copy -movflags +faststart'
EDIT_SUFFIX = '_edit'
EDIT_EXTENSION = '.mp4'
_STDERR_LIMIT = 64 * 1024

WAITING = 'waiting'
CONVERTING = 'converting'
DONE = 'done'
FAILED = 'failed'
CANCELLED = 'cancelled'

_encoders = {}


def parse_rate(text) -> Optional[Fraction]:
    """'50/1' -> Fraction(50); None for ffprobe's '0/0' or anything unreadable."""
    try:
        rate = Fraction(str(text))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe(path, ffprobe='ffprobe'):
    """The first video stream's frame rate (a Fraction or None) and the duration in seconds (or None)."""
    cmd = [
        ffprobe, '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=avg_frame_rate,r_frame_rate:format=duration',
        '-of', 'json',
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        data = json.loads(result.stdout or '{}')
    except (OSError, subprocess.TimeoutExpired, ValueError):
        log.debug('ffprobe failed for %s', path, exc_info=True)
        return None, None
    rate = None
    for stream in data.get('streams') or []:
        rate = parse_rate(stream.get('avg_frame_rate')) or parse_rate(stream.get('r_frame_rate'))
        if rate is not None:
            break
    try:
        duration = float((data.get('format') or {}).get('duration'))
    except (TypeError, ValueError):
        duration = None
    return rate, duration if duration and duration > 0 else None


def frame_rate_options(rate, fps_mode=True) -> List[str]:
    """Constant frame rate with a keyframe every second. ``fps_mode`` False is for ffmpeg before 5.1."""
    if rate is None:
        return []
    gop = str(max(1, round(rate)))
    sync = ['-fps_mode', 'cfr'] if fps_mode else ['-vsync', 'cfr']
    text = str(rate.numerator) if rate.denominator == 1 else f'{rate.numerator}/{rate.denominator}'
    return sync + ['-r', text, '-g', gop, '-keyint_min', gop]


def build_convert_command(source, target, options, rate=None, fps_mode=True, ffmpeg='ffmpeg'):
    """The ffmpeg argv for an edit-friendly copy. ``options`` come last, so they win."""
    return [
        ffmpeg,
        '-hide_banner',
        '-nostdin',
        '-loglevel', 'error',
        '-nostats',
        '-progress', 'pipe:1',
        '-y',
        '-i', str(source),
        # Broadcast subtitles are pictures, which MP4 cannot hold.
        '-sn', '-dn',
        *frame_rate_options(rate, fps_mode),
        *options,
        str(target),
    ]


def edit_path(source, folder=None, taken=()):
    """``show.ts`` -> ``show_edit.mp4`` in ``folder`` (the source's own by default).

    Never an existing file, nor one in ``taken``: the targets of conversions not finished yet.
    """
    folder = folder or os.path.dirname(os.path.abspath(str(source)))
    stem = os.path.splitext(os.path.basename(str(source)))[0]
    path = os.path.join(folder, f'{stem}{EDIT_SUFFIX}{EDIT_EXTENSION}')
    number = 2
    while os.path.exists(path) or path in taken:
        path = os.path.join(folder, f'{stem}{EDIT_SUFFIX}_{number}{EDIT_EXTENSION}')
        number += 1
    return path


def requested_encoder(options) -> Optional[str]:
    """The video encoder the options name, or None when they leave it to ffmpeg."""
    encoder = None
    for flag, value in zip(options, options[1:]):
        if flag in ('-c:v', '-codec:v', '-vcodec', '-c:v:0', '-codec:v:0'):
            encoder = value
    return encoder


def available_encoders(ffmpeg='ffmpeg'):
    """Encoder names this ffmpeg has, read once. Empty when ffmpeg cannot be run."""
    if ffmpeg not in _encoders:
        names = set()
        try:
            result = subprocess.run(
                [ffmpeg, '-hide_banner', '-encoders'],
                capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
            )
            started = False
            for line in result.stdout.splitlines():
                if line.strip().startswith('------'):
                    started = True
                    continue
                parts = line.split()
                if started and len(parts) >= 2:
                    names.add(parts[1])
        except (OSError, subprocess.TimeoutExpired):
            log.debug('Could not list ffmpeg encoders', exc_info=True)
        _encoders[ffmpeg] = names
    return _encoders[ffmpeg]


def missing_encoder(text, ffmpeg='ffmpeg') -> Optional[str]:
    """Why ``text`` cannot convert with this ffmpeg, or None when it can. Raises ValueError for bad quoting."""
    options = parse_ffmpeg_options(text)
    encoders = available_encoders(ffmpeg)
    if not encoders:
        return 'ffmpeg was not found.'
    encoder = requested_encoder(options)
    if encoder and encoder != 'copy' and encoder not in encoders:
        return f'This ffmpeg has no {encoder} encoder.'
    return None


class Conversion:
    """One edit-friendly copy. ``run`` blocks; the UI starts it on a thread and reads the fields."""

    def __init__(self, source, target, options, delete_original=False, ffmpeg='ffmpeg', ffprobe='ffprobe'):
        self.source = str(source)
        self.target = str(target)
        self.options = list(options)
        self.delete_original = delete_original
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.status = WAITING
        self.progress = None
        self.error = ''
        self._process = None
        self._cancelled = False
        self._lock = threading.Lock()

    @property
    def is_active(self):
        return self.status in (WAITING, CONVERTING)

    def cancel(self):
        with self._lock:
            self._cancelled = True
            process = self._process
            if self.status == WAITING:
                self.status = CANCELLED
        if process is not None and process.poll() is None:
            process.terminate()

    def start(self):
        """Run on a thread of its own. Only a waiting conversion starts."""
        with self._lock:
            if self.status != WAITING:
                return
            self.status = CONVERTING
        threading.Thread(target=self.run, name='convert', daemon=True).start()

    def run(self):
        with self._lock:
            if self._cancelled:
                self.status = CANCELLED
                return
            self.status = CONVERTING
        rate, duration = probe(self.source, self.ffprobe)
        self.progress = 0.0 if duration else None
        for fps_mode in (True, False):
            code, stderr = self._run_ffmpeg(
                build_convert_command(self.source, self.target, self.options, rate, fps_mode, self.ffmpeg),
                duration,
            )
            if self._cancelled:
                self._remove(self.target)
                self.status = CANCELLED
                return
            if code == 0:
                break
            if fps_mode and rate is not None and 'fps_mode' in stderr:
                log.info('ffmpeg has no -fps_mode; converting again with -vsync')
                continue
            self._remove(self.target)
            lines = [line.strip() for line in stderr.splitlines() if line.strip()]
            self.error = lines[-1] if lines else f'ffmpeg stopped with code {code}'
            self.status = FAILED
            return
        self.progress = 1.0
        if self.delete_original:
            try:
                os.remove(self.source)
            except OSError as exc:
                log.warning('Could not delete %s after converting it: %s', self.source, exc)
        self.status = DONE

    def _run_ffmpeg(self, cmd, duration):
        log.info('Converting for editing: %s', ' '.join(cmd))
        stderr = bytearray()

        def drain(pipe):
            for chunk in iter(lambda: pipe.read(4096), b''):
                stderr.extend(chunk)
                del stderr[:max(0, len(stderr) - _STDERR_LIMIT)]

        try:
            with self._lock:
                if self._cancelled:
                    return None, ''
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
        except OSError as exc:
            return None, str(exc)
        process = self._process
        reader = threading.Thread(target=drain, args=(process.stderr,), daemon=True)
        reader.start()
        for raw in process.stdout:
            line = raw.decode('utf-8', 'replace').strip()
            # out_time_us and out_time_ms are both in microseconds.
            if duration and line.startswith(('out_time_us=', 'out_time_ms=')):
                try:
                    seconds = int(line.split('=', 1)[1]) / 1_000_000
                except ValueError:
                    continue
                self.progress = min(max(seconds / duration, 0.0), 0.99)
        code = process.wait()
        reader.join(timeout=1)
        with self._lock:
            self._process = None
        return code, bytes(stderr).decode('utf-8', 'replace')

    @staticmethod
    def _remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

"""Debug output for the playback spinner: what holds up its ticks.

Off unless ``TVHPLAYER_DEBUG_SPINNER`` is set. While the spinner turns, a
watchdog thread notices when its next tick is overdue and samples what every
thread is doing until the tick comes. A late tick is then printed with how
late it was and those samples: the main thread's stack in full, and for each
other thread where it was, marked "waiting" when it sat in a blocking call
(those cannot hold the GIL). A spinner paint that takes long is noted too, and
each run ends with a summary of its late ticks.

The main thread only records times; the watchdog thread does the printing, so
the report itself does not hold up the next tick.

A thread that holds the GIL can keep the watchdog from sampling at all. As a
backup, faulthandler is armed on every tick: when a tick is FAULT_SECONDS
overdue, its C thread writes every thread's stack to a file without the GIL,
and that dump is printed with the late tick.
"""

from __future__ import annotations

import faulthandler
import os
import re
import sys
import tempfile
import threading
import time
import traceback

DEBUG_ENV = 'TVHPLAYER_DEBUG_SPINNER'
# The spinner ticks every 16 ms; a gap this long between ticks is reported.
LATE_SECONDS = 0.05
# Once a tick is this overdue, the watchdog samples every SAMPLE_SECONDS.
SAMPLE_AFTER_SECONDS = 0.025
SAMPLE_SECONDS = 0.005
MAX_SAMPLES = 40
# A tick this overdue gets a faulthandler dump, which needs no GIL.
FAULT_SECONDS = 0.06
# A spinner paint slower than this is noted.
SLOW_PAINT_SECONDS = 0.008
# Frames shown for the main thread and for threads that were running Python.
STACK_DEPTH = 12
# A top line with one of these calls is a thread waiting in C, without the GIL.
_WAITING = re.compile(
    r'(wait|read|recv|select|poll|sleep|accept|acquire|join|readline|exec|urlopen|getaddrinfo|connect)\w*\('
)

_start = time.monotonic()
_watch = None


def enabled():
    value = os.environ.get(DEBUG_ENV, '').strip()
    return bool(value) and value != '0'


def note(text):
    print(f"Debug: [spinner {time.monotonic() - _start:8.3f}] {text}", flush=True)


def _stack(frame, depth=STACK_DEPTH):
    return traceback.extract_stack(frame)[-depth:]


def _where(summary):
    if not summary:
        return '(no Python frame)'
    top = summary[-1]
    return f'{os.path.basename(top.filename)}:{top.lineno} {top.name}: {(top.line or "").strip()}'


def _is_waiting(summary):
    return bool(summary) and bool(_WAITING.search(summary[-1].line or ''))


def snapshot(skip_ident=None):
    """Every thread's stack right now, as {thread name: StackSummary}."""
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    main = threading.main_thread().ident
    shot = {}
    for ident, frame in sys._current_frames().items():
        if ident == skip_ident:
            continue
        name = 'MAIN' if ident == main else names.get(ident, f'thread-{ident}')
        shot[name] = _stack(frame)
    return shot


def format_late(gap, samples):
    """Text for one late tick and the samples taken while it was overdue."""
    lines = [f'tick late: {gap * 1000:.0f} ms since the last one, {len(samples)} samples while overdue']
    if not samples:
        lines.append('  (no samples: the watchdog did not get to run either, so a thread held the GIL)')
        return '\n'.join(lines)
    total = len(samples)
    names = sorted({name for shot in samples for name in shot}, key=lambda n: (n != 'MAIN', n))
    for name in names:
        counts = {}
        for shot in samples:
            summary = shot.get(name)
            if summary is None:
                continue
            key = tuple((f.filename, f.lineno, f.name) for f in summary)
            entry = counts.setdefault(key, [0, summary])
            entry[0] += 1
        ranked = sorted(counts.values(), key=lambda entry: -entry[0])
        busy = [(count, summary) for count, summary in ranked if not _is_waiting(summary)]
        if name != 'MAIN' and not busy:
            lines.append(f'  {name}: waiting at {_where(ranked[0][1])}')
            continue
        shown = ranked if name == 'MAIN' else busy
        lines.append(f'  {name}:')
        for count, summary in shown[:3]:
            state = 'waiting' if _is_waiting(summary) else 'RUNNING'
            lines.append(f'    {count}/{total} {state}:')
            for frame in summary:
                lines.append(f'      {os.path.basename(frame.filename)}:{frame.lineno} {frame.name}: '
                             f'{(frame.line or "").strip()}')
    return '\n'.join(lines)


class SpinnerWatch:
    """Times the spinner's ticks and samples the threads while one is overdue."""

    def __init__(self, out=note, dump=True):
        self._out = out
        # faulthandler needs a real file; stdout may be the app.log copier.
        self._dump = tempfile.TemporaryFile() if dump else None
        self._dump_read = 0
        self._lock = threading.Lock()
        self._running = False
        self._last = 0.0
        self._samples = []
        self._reports = []
        self._run_started = 0.0
        self._ticks = 0
        self._late = []
        self._wake = threading.Event()
        self._thread = None

    def started(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            now = time.monotonic()
            self._last = self._run_started = now
            self._samples = []
            self._ticks = 0
            self._late = []
        self._arm()
        self._reports.append(f'spinner started, GIL switch interval {sys.getswitchinterval() * 1000:.0f} ms')
        if self._thread is None:
            self._thread = threading.Thread(target=self._watchdog, name='spinner-debug', daemon=True)
            self._thread.start()
        self._wake.set()

    def stopped(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            now = time.monotonic()
            # A stall that the stop ended, as when the window is busy just as
            # the picture comes, has no next tick to report it.
            gap = now - self._last
            if gap > LATE_SECONDS:
                self._late.append(gap)
                self._reports.append((gap, self._samples))
            self._samples = []
            self._disarm()
            took = now - self._run_started
            late = list(self._late)
            ticks = self._ticks
        worst = f', worst {max(late) * 1000:.0f} ms' if late else ''
        self._reports.append(
            f'spinner stopped after {took:.1f} s: {ticks} ticks, {len(late)} late{worst}'
        )
        self._wake.set()

    def tick(self):
        now = time.monotonic()
        with self._lock:
            if not self._running:
                return
            gap = now - self._last
            self._last = now
            self._ticks += 1
            samples, self._samples = self._samples, []
            self._arm()
            if gap > LATE_SECONDS:
                self._late.append(gap)
                self._reports.append((gap, samples))
                self._wake.set()

    def _arm(self):
        if self._dump is not None:
            faulthandler.dump_traceback_later(FAULT_SECONDS, file=self._dump)

    def _disarm(self):
        if self._dump is not None:
            faulthandler.cancel_dump_traceback_later()

    def _new_dump(self):
        """What faulthandler wrote since the last call, without moving its file offset."""
        if self._dump is None:
            return ''
        fd = self._dump.fileno()
        size = os.fstat(fd).st_size
        if size <= self._dump_read:
            return ''
        data = os.pread(fd, size - self._dump_read, self._dump_read)
        self._dump_read += len(data)
        return data.decode('utf-8', errors='replace')

    def painted(self, seconds):
        if seconds > SLOW_PAINT_SECONDS and self._running:
            self._reports.append(f'slow spinner paint: {seconds * 1000:.1f} ms')
            self._wake.set()

    def _watchdog(self):
        me = threading.get_ident()
        while True:
            self._flush()
            with self._lock:
                running = self._running
                overdue = time.monotonic() - self._last
            if not running:
                self._wake.wait()
                self._wake.clear()
                continue
            if overdue > SAMPLE_AFTER_SECONDS:
                shot = snapshot(skip_ident=me)
                with self._lock:
                    # Dropped when the tick came while the sample was taken.
                    still_overdue = time.monotonic() - self._last > SAMPLE_AFTER_SECONDS
                    if self._running and still_overdue and len(self._samples) < MAX_SAMPLES:
                        self._samples.append(shot)
            time.sleep(SAMPLE_SECONDS)

    def _flush(self):
        while self._reports:
            item = self._reports.pop(0)
            if not isinstance(item, tuple):
                # A dump here belongs to no late tick.
                self._new_dump()
                self._out(item)
                continue
            text = format_late(*item)
            dump = self._new_dump()
            if dump:
                text += '\n  faulthandler, all threads while the tick was overdue:\n'
                text += '\n'.join(f'    {line}' for line in dump.rstrip().splitlines())
            self._out(text)


def install():
    """Start watching when ``TVHPLAYER_DEBUG_SPINNER`` asks for it."""
    global _watch
    if _watch is None and enabled():
        _watch = SpinnerWatch()
        note('debug on')
    return _watch


def started():
    if _watch is not None:
        _watch.started()


def stopped():
    if _watch is not None:
        _watch.stopped()


def tick():
    if _watch is not None:
        _watch.tick()


def painted(seconds):
    if _watch is not None:
        _watch.painted(seconds)

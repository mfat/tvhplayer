"""Debug output for the busy cursor: what the app does to the cursor and its windows.

Off unless ``TVHPLAYER_DEBUG_CURSOR`` is set. With ``1`` it prints, with a time
since start: cursor changes on widgets, the application override cursor,
windows shown, hidden, activated and deactivated, application state changes,
programs started, and the event loop stalling, with the main thread's stack
when a stall lasts. With ``2`` Qt's Wayland logging is turned on as well, which
shows activation tokens and cursor surfaces.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

DEBUG_ENV = 'TVHPLAYER_DEBUG_CURSOR'
# A gap between timer ticks this long is reported as a stall.
STALL_SECONDS = 0.25
# A stall this long dumps the main thread's stack.
STACK_SECONDS = 1.0
# Qt's Wayland categories without pointer and key input, which would bury the rest.
WAYLAND_RULES = 'qt.qpa.wayland*=true;qt.qpa.wayland.input*=false'

_start = time.monotonic()
_installed = None

_WINDOW_EVENTS = {
    QEvent.Type.Show: 'shown',
    QEvent.Type.Hide: 'hidden',
    QEvent.Type.WindowActivate: 'activated',
    QEvent.Type.WindowDeactivate: 'deactivated',
    QEvent.Type.WindowBlocked: 'blocked by a modal window',
    QEvent.Type.WindowUnblocked: 'unblocked',
}


def level():
    value = os.environ.get(DEBUG_ENV, '').strip()
    if not value or value == '0':
        return 0
    return 2 if value == '2' else 1


def note(text):
    print(f"Debug: [cursor {time.monotonic() - _start:8.3f}] {text}", flush=True)


def _name(widget):
    name = widget.objectName()
    title = widget.windowTitle() if widget.isWindow() else ''
    parts = [type(widget).__name__]
    if name:
        parts.append(f'#{name}')
    if title:
        parts.append(f'"{title}"')
    return ' '.join(parts)


def _shape(cursor):
    return cursor.shape().name if cursor is not None else 'none'


class _CursorWatch(QObject):
    """Notes cursor and window events, and the override cursor and event loop over time."""

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self._override = 'none'
        self._tick = time.monotonic()
        self._stack_dumped = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        app.applicationStateChanged.connect(lambda state: note(f'application state: {state.name}'))
        # The watchdog runs on its own thread, so it sees a main thread that is stuck.
        self._stop = threading.Event()
        threading.Thread(target=self._watchdog, name='cursor-debug', daemon=True).start()

    def stop(self):
        self._stop.set()
        self._timer.stop()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.CursorChange and isinstance(obj, QWidget):
            note(f'cursor of {_name(obj)}: {_shape(obj.cursor())}')
        elif kind in _WINDOW_EVENTS and isinstance(obj, QWidget) and obj.isWindow():
            note(f'window {_name(obj)} {_WINDOW_EVENTS[kind]}')
        return False

    def _poll(self):
        now = time.monotonic()
        gap = now - self._tick
        if gap > STALL_SECONDS:
            note(f'event loop stalled for {gap:.2f}s')
        self._tick = now
        self._stack_dumped = False
        override = _shape(self._app.overrideCursor())
        if override != self._override:
            note(f'override cursor: {self._override} -> {override}')
            self._override = override

    def _watchdog(self):
        while not self._stop.wait(0.2):
            if not self._stack_dumped and time.monotonic() - self._tick > STACK_SECONDS:
                self._stack_dumped = True
                # faulthandler needs a real file; stdout may be the app.log copier.
                frame = sys._current_frames().get(threading.main_thread().ident)
                stack = ''.join(traceback.format_stack(frame)) if frame is not None else '(no frame)\n'
                note(f'event loop stuck for over {STACK_SECONDS:.0f}s; main thread is at:\n{stack}')


def _watch_programs():
    """Note each program the app starts, and from which thread."""
    original = subprocess.Popen.__init__

    def logged_init(self, args, *rest, **kwargs):
        note(f'starting {args!r} on thread {threading.current_thread().name}')
        original(self, args, *rest, **kwargs)

    subprocess.Popen.__init__ = logged_init


def prepare():
    """Before QApplication: with level 2, Qt's Wayland logging, so its start-up is in it too."""
    if level() >= 2:
        rules = [os.environ.get('QT_LOGGING_RULES', ''), WAYLAND_RULES]
        os.environ['QT_LOGGING_RULES'] = ';'.join(rule for rule in rules if rule)


def install(app):
    """Start the debug output when ``TVHPLAYER_DEBUG_CURSOR`` asks for it."""
    global _installed
    if not level() or _installed is not None:
        return
    note(f'debug on, platform {QApplication.platformName()}')
    _watch_programs()
    watch = _CursorWatch(app)
    app.installEventFilter(watch)

    def off():
        # Off before PyQt's exit cleanup, as with the theme's filter.
        app.removeEventFilter(watch)
        watch.stop()

    app.aboutToQuit.connect(off)
    _installed = watch

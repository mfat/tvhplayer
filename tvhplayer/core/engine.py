"""Choose the playback engine before Qt starts. No Qt imports.

libvlc 3 can only draw into an X11 window on Linux, so with it the whole
window runs through XWayland on a Wayland desktop. libmpv draws into an
OpenGL widget, so with it Qt stays on Wayland. The Qt platform is fixed
when ``QApplication`` is created, so one launch uses one engine.
"""

from __future__ import annotations

import os
import sys

ENGINE_VLC = 'vlc'
ENGINE_MPV = 'mpv'
# Set to "vlc" or "mpv" to skip the automatic choice.
ENGINE_ENV = 'TVHPLAYER_ENGINE'


def mpv_missing() -> str:
    """Why libmpv cannot be used here, or an empty string when it can."""
    try:
        import mpv  # noqa: F401  (loads libmpv)
        from PyQt6 import QtOpenGLWidgets  # noqa: F401
    except (ImportError, OSError, AttributeError) as exc:
        return str(exc) or type(exc).__name__
    return ''


def choose_engine(environ=None, platform=None, missing=mpv_missing):
    """Return ``(engine, reason)``."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if not platform.startswith('linux'):
        return ENGINE_VLC, 'libmpv is used only on Linux'
    forced = environ.get(ENGINE_ENV, '').strip().lower()
    if forced == ENGINE_VLC:
        return ENGINE_VLC, f'{ENGINE_ENV}=vlc'
    if forced != ENGINE_MPV:
        if environ.get('QT_QPA_PLATFORM'):
            return ENGINE_VLC, 'QT_QPA_PLATFORM is set'
        if not environ.get('WAYLAND_DISPLAY'):
            return ENGINE_VLC, 'not a Wayland session'
    problem = missing()
    if problem:
        return ENGINE_VLC, f'libmpv is not available: {problem}'
    return ENGINE_MPV, f'{ENGINE_ENV}=mpv' if forced == ENGINE_MPV else 'Wayland session'

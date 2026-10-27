"""Choose the playback engine before Qt starts. No Qt imports.

libvlc 3 can only draw into an X11 window on Linux, so with it the whole
window runs through XWayland on a Wayland desktop. libmpv draws into an
OpenGL widget, so with it Qt stays on Wayland. The Qt platform is fixed
when ``QApplication`` is created, so one launch uses one engine.
"""

from __future__ import annotations

import os
import sys

ENGINE_AUTO = 'auto'
ENGINE_VLC = 'vlc'
ENGINE_MPV = 'mpv'
# The Settings choice: automatic, or one engine on every session.
ENGINE_CHOICES = (ENGINE_AUTO, ENGINE_MPV, ENGINE_VLC)
# Set to "vlc" or "mpv" to override the setting for one launch.
ENGINE_ENV = 'TVHPLAYER_ENGINE'


def mpv_missing() -> str:
    """Why libmpv cannot be used here, or an empty string when it can."""
    try:
        import mpv  # noqa: F401  (loads libmpv)
        from PyQt6 import QtOpenGLWidgets  # noqa: F401
    except (ImportError, OSError, AttributeError) as exc:
        return str(exc) or type(exc).__name__
    return ''


def vlc_missing() -> str:
    """Why libvlc cannot be used here, or an empty string when it can."""
    try:
        import vlc  # noqa: F401  (loads libvlc)
    except Exception as exc:
        return str(exc) or type(exc).__name__
    return ''


def qt_runs_on_wayland(environ) -> bool:
    """True when Qt will pick Wayland unless the app forces X11."""
    platform = environ.get('QT_QPA_PLATFORM', '')
    if platform:
        return platform.split(';')[0].strip().startswith('wayland')
    return bool(environ.get('WAYLAND_DISPLAY'))


def choose_engine(environ=None, platform=None, missing=mpv_missing, preference=ENGINE_AUTO,
                  vlc_missing=vlc_missing):
    """Return ``(engine, reason)``.

    ``preference`` is the Settings choice; the environment variable overrides it.
    Without libvlc, as in the AppImage, mpv plays on X11 too.
    """
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if not platform.startswith('linux'):
        return ENGINE_VLC, 'libmpv is used only on Linux'
    forced = environ.get(ENGINE_ENV, '').strip().lower()
    if forced in (ENGINE_VLC, ENGINE_MPV):
        wanted, why = forced, f'{ENGINE_ENV}={forced}'
    elif preference in (ENGINE_VLC, ENGINE_MPV):
        wanted, why = preference, 'chosen in Settings'
    elif qt_runs_on_wayland(environ):
        wanted, why = ENGINE_MPV, 'Wayland session'
    else:
        wanted, why = ENGINE_VLC, 'X11 session'
    if wanted == ENGINE_VLC:
        problem = vlc_missing()
        if problem and not missing():
            return ENGINE_MPV, f'libvlc is not available: {problem}'
        return ENGINE_VLC, why
    problem = missing()
    if problem:
        return ENGINE_VLC, f'libmpv is not available: {problem}'
    return ENGINE_MPV, why


def startup_platform(engine, environ=None, platform=None):
    """The Qt platform the app starts on with ``engine``: "wayland", "xcb" or
    another ``QT_QPA_PLATFORM`` name, or None outside Linux, where Qt picks.

    ``environ`` is the environment before the app forced X11 for VLC."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if not platform.startswith('linux'):
        return None
    forced = qt_platform_for(engine, environ, platform)
    if forced:
        return forced
    # The first choice, without its arguments: "xcb:display=:1" is xcb.
    value = environ.get('QT_QPA_PLATFORM', '').split(';')[0].split(':')[0].strip()
    if value:
        return value
    return 'wayland' if environ.get('WAYLAND_DISPLAY') else 'xcb'


def qt_platform_for(engine, environ=None, platform=None):
    """The ``QT_QPA_PLATFORM`` to set before ``QApplication``, or None to leave it.

    libvlc 3 embeds only into an X11 window, so it gets X11 even where Qt
    would otherwise pick Wayland. libmpv runs on whatever Qt picks.
    """
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if engine != ENGINE_VLC or not platform.startswith('linux'):
        return None
    if environ.get('QT_QPA_PLATFORM') and not qt_runs_on_wayland(environ):
        return None
    return 'xcb'

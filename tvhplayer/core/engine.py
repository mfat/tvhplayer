"""Require libmpv before Qt starts. No Qt imports.

libmpv draws into a Qt OpenGL widget, so the window stays on whatever
platform Qt picks (Wayland or X11). There is no other playback engine.
"""

from __future__ import annotations


def mpv_missing() -> str:
    """Why libmpv cannot be used here, or an empty string when it can."""
    try:
        import mpv  # noqa: F401  (loads libmpv)
        from PyQt6 import QtOpenGLWidgets  # noqa: F401
    except (ImportError, OSError, AttributeError) as exc:
        return str(exc) or type(exc).__name__
    return ''

"""Starting helper programs such as ffmpeg and ffprobe. No Qt imports."""

import sys

# Windows opens a console window for a console program a windowed app starts.
CREATE_NO_WINDOW = 0x08000000


def no_window_flags(platform=None) -> int:
    """``creationflags`` for ``subprocess``: no console window on Windows."""
    platform = sys.platform if platform is None else platform
    return CREATE_NO_WINDOW if platform == 'win32' else 0

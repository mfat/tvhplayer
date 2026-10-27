"""Libraries and programs a packaged Windows or macOS build carries inside itself.

python-mpv finds libmpv with ctypes.util.find_library, which searches only
the system's places, not the folder PyInstaller unpacks the app into. The
app runs ffmpeg and ffprobe by name, so that folder goes first on PATH.
"""

import ctypes.util
import os
import sys

LIBMPV = {'win32': 'libmpv-2.dll', 'darwin': 'libmpv.2.dylib'}
# What python-mpv asks for: 'mpv' on macOS, the DLL names on Windows.
LIBMPV_NAMES = frozenset({'mpv', 'libmpv-2.dll', 'mpv-2.dll', 'mpv-1.dll'})
FFMPEG = {'win32': 'ffmpeg.exe', 'darwin': 'ffmpeg'}


def prepare():
    """Point lookups at the build's own libmpv and ffmpeg. Call before ``import mpv``."""
    base = getattr(sys, '_MEIPASS', None)
    if not getattr(sys, 'frozen', False) or not base:
        return
    ffmpeg = FFMPEG.get(sys.platform)
    if ffmpeg and os.path.exists(os.path.join(base, ffmpeg)):
        os.environ['PATH'] = os.pathsep.join(filter(None, (base, os.environ.get('PATH'))))
    name = LIBMPV.get(sys.platform)
    path = os.path.join(base, name) if name else None
    if not path or not os.path.exists(path):
        return
    system_find = ctypes.util.find_library

    def find_library(wanted):
        if wanted in LIBMPV_NAMES:
            return path
        return system_find(wanted)

    ctypes.util.find_library = find_library

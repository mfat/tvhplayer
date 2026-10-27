"""Libraries a packaged Windows or macOS build carries inside itself.

python-mpv finds libmpv with ctypes.util.find_library, which searches only
the system's places, not the folder PyInstaller unpacks the app into.
"""

import ctypes.util
import os
import sys

LIBMPV = {'win32': 'libmpv-2.dll', 'darwin': 'libmpv.2.dylib'}
# What python-mpv asks for: 'mpv' on macOS, the DLL names on Windows.
LIBMPV_NAMES = frozenset({'mpv', 'libmpv-2.dll', 'mpv-2.dll', 'mpv-1.dll'})


def prepare():
    """Point library lookups at the build's own libmpv. Call before ``import mpv``."""
    base = getattr(sys, '_MEIPASS', None)
    if not getattr(sys, 'frozen', False) or not base:
        return
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

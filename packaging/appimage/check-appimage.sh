#!/bin/sh
# Check that an AppImage's own Python, Qt, libmpv, ffmpeg and Tvheadend start.
#
#   check-appimage.sh APPIMAGE
#
# Runs without a display (Qt's offscreen platform) and without FUSE.
set -eu

[ $# -eq 1 ] || { echo "usage: $0 APPIMAGE" >&2; exit 2; }
image=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
"$image" --appimage-extract >/dev/null
root=$work/squashfs-root

"$root/usr/bin/tvheadend" --version
"$root/usr/bin/ffmpeg" -hide_banner -version | head -n 1
cd "$root/usr/share/tvhplayer"
QT_QPA_PLATFORM=offscreen PATH="$root/usr/bin:$PATH" "$root/usr/bin/tvhplayer-python3" -s -c '
import sys
from PyQt6 import QtDBus, QtOpenGLWidgets, QtSvg, QtWidgets  # noqa: F401
app = QtWidgets.QApplication([])
import mpv
player = mpv.MPV(vo="null")
print("Python", sys.version.split()[0], "| Qt", app.platformName(), "|", player.mpv_version)
player.terminate()
import psutil, requests, xdg  # noqa: F401
from core.builtin_server import find_bundled_binary
from core.engine import ENGINE_MPV, choose_engine
assert find_bundled_binary().name == "tvheadend", find_bundled_binary()
assert choose_engine({"DISPLAY": ":0"})[0] == ENGINE_MPV
print("AppImage check passed")
'

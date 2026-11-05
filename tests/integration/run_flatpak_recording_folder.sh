#!/bin/bash
# Host-side driver; requires an installed test Flatpak, Xvfb, xdotool and D-Bus.
set -euo pipefail
scripts=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app=${1:-io.github.mfat.tvhplayer.RecordingTest}
mkdir -p "$HOME/.cache"
root=$(mktemp -d "$HOME/.cache/tvhplayer-recording-check.XXXXXX")
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export QT_QPA_PLATFORM=xcb GDK_BACKEND=x11 XDG_CURRENT_DESKTOP=KDE
export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe
unset WAYLAND_DISPLAY
export DISPLAY=${TVHPLAYER_TEST_DISPLAY:-:97}
Xvfb "$DISPLAY" -screen 0 1280x1024x24 -nolisten tcp > "$root/xvfb.log" 2>&1 &
xvfb_pid=$!
trap 'kill "$xvfb_pid" 2>/dev/null || true' EXIT
sleep .5
if ! kill -0 "$xvfb_pid" 2>/dev/null; then
    cat "$root/xvfb.log"
    exit 1
fi
echo "Integration artifacts: $root"
dbus-run-session -- bash "$scripts/flatpak_recording_session.sh" "$root" "$app"

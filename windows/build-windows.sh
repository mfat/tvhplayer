#!/usr/bin/env bash
# Build TVHplayer for Windows (x86_64) with PyInstaller. Runs in Git Bash.
#
#   windows/build-windows.sh VERSION
#
# Plays with mpv: libmpv-2.dll (FFmpeg built in) from the pinned shinchiro
# build that mpv.io links. Writes windows/dist/tvhplayer-VERSION-windows-x86_64.zip.
set -euo pipefail

# Windows paths (D:/a/...): PyInstaller is a Windows program and does not
# understand Git Bash's /d/a/... inside its SOURCE;DEST arguments.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -W)"
HERE="$ROOT/windows"
# shellcheck source=windows/pins.env
. "$HERE/pins.env"
PYTHON="${PYTHON:-python}"
[[ $# -eq 1 ]] || { echo "usage: $0 VERSION" >&2; exit 2; }
VERSION=$1
WORK="$HERE/build"
DIST="$HERE/dist"
rm -rf "$WORK" "$DIST"
mkdir -p "$WORK" "$DIST"

echo "==> libmpv $MPV_DEV_BUILD"
archive="$WORK/mpv-dev.7z"
curl --fail --silent --show-error --location --retry 3 -o "$archive" "$MPV_DEV_URL"
echo "$MPV_DEV_SHA256  $archive" | sha256sum -c --quiet -
7z e -y -o"$WORK" "$archive" libmpv-2.dll >/dev/null
test -f "$WORK/libmpv-2.dll"

echo "==> Python packages"
"$PYTHON" -m pip install --quiet -r "$HERE/requirements-build.txt"

echo "==> PyInstaller"
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name TVHplayer \
  --icon "$ROOT/icons/tvhplayer.png" \
  --paths "$ROOT/tvhplayer" \
  --collect-submodules core \
  --hidden-import resources_rc \
  --add-binary "$WORK/libmpv-2.dll;." \
  --add-data "$ROOT/icons;icons" \
  --distpath "$WORK/dist" \
  --workpath "$WORK/pyinstaller" \
  --specpath "$WORK" \
  "$ROOT/tvhplayer/tvhplayer.py"

app="$WORK/dist/TVHplayer"
test -f "$app/TVHplayer.exe"
test -f "$app/_internal/libmpv-2.dll"

echo "==> Zip"
zip="$DIST/tvhplayer-$VERSION-windows-x86_64.zip"
(cd "$WORK/dist" && 7z a -tzip -mx=7 "$zip" TVHplayer >/dev/null)
echo "==> Built $zip"

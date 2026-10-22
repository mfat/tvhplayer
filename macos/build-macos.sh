#!/usr/bin/env bash
# Build TVHplayer for Intel macOS using locally installed VLC 3.0.24.
# Also used by .github/workflows/build-macos.yml.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: This build targets Intel macOS (x86_64) only." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MACOS_DIR="$ROOT/macos"
VLC_APP="${VLC_APP:-/Applications/VLC.app}"
PYTHON="${PYTHON:-python3}"
APP_NAME="${TVHPLAYER_APP_NAME:-TVHplayer-MacOS-Intel}"

if [[ ! "$APP_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: TVHPLAYER_APP_NAME must contain only letters, digits, dots, dashes or underscores." >&2
  exit 1
fi

if [[ ! -f "$VLC_APP/Contents/MacOS/lib/libvlc.dylib" || ! -f "$VLC_APP/Contents/MacOS/lib/libvlccore.dylib" ]]; then
  echo "ERROR: VLC native libraries were not found in $VLC_APP" >&2
  exit 1
fi

VLC_PLUGINS=""
for candidate in "$VLC_APP/Contents/MacOS/plugins" "$VLC_APP/Contents/Frameworks/plugins"; do
  if [[ -d "$candidate" ]]; then
    VLC_PLUGINS="$candidate"
    break
  fi
done
if [[ -z "$VLC_PLUGINS" ]]; then
  echo "ERROR: VLC plugins directory was not found in $VLC_APP" >&2
  exit 1
fi

"$PYTHON" -c 'import PyInstaller; import PyQt6; import vlc; import requests'

# plugins.dat is tied to the original plugins' sizes and modification times.
# Copy plugins without it, so PyInstaller cannot package a stale cache.
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/tvhplayer-plugins.XXXXXX")"
trap 'rm -rf -- "$STAGING"' EXIT
mkdir -p "$STAGING/plugins"
rsync -a --exclude='plugins.dat' "$VLC_PLUGINS/" "$STAGING/plugins/"

if [[ -e "$STAGING/plugins/plugins.dat" ]] || \
   ! find "$STAGING/plugins" -type f -name '*_plugin.dylib' -print -quit | grep -q .; then
  echo 'ERROR: VLC plugin staging failed or retained a stale cache.' >&2
  exit 1
fi

printf 'Building %s (Python: %s)\n' "$APP_NAME" "$("$PYTHON" --version 2>&1)"
printf 'VLC plugins from: %s (plugins.dat excluded)\n' "$VLC_PLUGINS"

"$PYTHON" -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name "$APP_NAME" \
  --target-arch x86_64 \
  --osx-bundle-identifier io.github.mfat.tvhplayer.localbuild \
  --icon "$MACOS_DIR/icons/tvhplayer.png" \
  --paths "$ROOT/tvhplayer" \
  --hidden-import resources_rc \
  --hidden-import core \
  --hidden-import core.backend \
  --hidden-import core.config \
  --hidden-import core.errors \
  --hidden-import core.htsmsg \
  --hidden-import core.htsp_backend \
  --hidden-import core.htsp_connection \
  --hidden-import core.http_backend \
  --hidden-import core.models \
  --hidden-import core.recorder \
  --hidden-import core.urls \
  --add-data "$MACOS_DIR/icons:icons" \
  --add-data "$STAGING/plugins:vlc/plugins" \
  --distpath "$MACOS_DIR/dist" \
  --workpath "$MACOS_DIR/build" \
  --specpath "$MACOS_DIR/build" \
  "$ROOT/tvhplayer/tvhplayer.py"

BUNDLE="$MACOS_DIR/dist/$APP_NAME.app"
BUNDLED_PLUGINS="$BUNDLE/Contents/Frameworks/vlc/plugins"
if [[ ! -x "$BUNDLE/Contents/MacOS/$APP_NAME" || \
      ! -d "$BUNDLED_PLUGINS" || \
      -e "$BUNDLED_PLUGINS/plugins.dat" ]]; then
  echo 'ERROR: Incomplete bundle, or an invalid VLC plugins.dat was included.' >&2
  exit 1
fi

printf 'BUILD OK: %s\n' "$BUNDLE"
printf 'VLC plugin cache: absent (as intended)\n'
printf 'Runtime requirement: VLC 3.0.24 for Intel macOS installed at /Applications/VLC.app\n'

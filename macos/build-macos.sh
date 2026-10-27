#!/usr/bin/env bash
# Build TVHplayer for macOS (Intel or Apple Silicon, whichever this Mac is).
# Also used by .github/workflows/build-macos.yml.
#
# Plays with mpv: Homebrew's libmpv (brew install mpv), and its ffmpeg and
# ffprobe for recording, go into the app with every library they need, so the
# app runs on Macs without Homebrew. Homebrew's
# libraries are built for the macOS version they were installed on, which is
# therefore the oldest macOS the app runs on.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: Build on macOS." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MACOS_DIR="$ROOT/macos"
PYTHON="${PYTHON:-python3}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) DEFAULT_NAME=TVHplayer-MacOS-Intel ;;
  arm64) DEFAULT_NAME=TVHplayer-MacOS-AppleSilicon ;;
  *) echo "ERROR: Unknown architecture $ARCH" >&2; exit 1 ;;
esac
APP_NAME="${TVHPLAYER_APP_NAME:-$DEFAULT_NAME}"

if [[ ! "$APP_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: TVHPLAYER_APP_NAME must contain only letters, digits, dots, dashes or underscores." >&2
  exit 1
fi

BREW_MPV="$(brew --prefix mpv 2>/dev/null || true)"
LIBMPV="$BREW_MPV/lib/libmpv.2.dylib"
if [[ ! -f "$LIBMPV" ]]; then
  echo "ERROR: libmpv not found. Install it with: brew install mpv" >&2
  exit 1
fi

BREW_FFMPEG="$(brew --prefix ffmpeg 2>/dev/null || true)"
for program in ffmpeg ffprobe; do
  if [[ ! -x "$BREW_FFMPEG/bin/$program" ]]; then
    echo "ERROR: $program not found. Install it with: brew install ffmpeg" >&2
    exit 1
  fi
done

# python-mpv searches only the default library paths, and Apple Silicon's
# Homebrew lives in /opt/homebrew.
DYLD_FALLBACK_LIBRARY_PATH="$BREW_MPV/lib" "$PYTHON" -c 'import PyInstaller, PyQt6, mpv, requests'

printf 'Building %s for %s (Python: %s, libmpv: %s)\n' \
  "$APP_NAME" "$ARCH" "$("$PYTHON" --version 2>&1)" "$(brew list --versions mpv)"

# PyInstaller collects the libraries libmpv links and rewrites their paths.
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name "$APP_NAME" \
  --target-arch "$ARCH" \
  --osx-bundle-identifier io.github.mfat.tvhplayer \
  --icon "$MACOS_DIR/icons/tvhplayer.png" \
  --paths "$ROOT/tvhplayer" \
  --collect-submodules core \
  --hidden-import resources_rc \
  --add-binary "$LIBMPV:." \
  --add-binary "$BREW_FFMPEG/bin/ffmpeg:." \
  --add-binary "$BREW_FFMPEG/bin/ffprobe:." \
  --add-data "$ROOT/icons:icons" \
  --distpath "$MACOS_DIR/dist" \
  --workpath "$MACOS_DIR/build" \
  --specpath "$MACOS_DIR/build" \
  "$ROOT/tvhplayer/tvhplayer.py"

BUNDLE="$MACOS_DIR/dist/$APP_NAME.app"
if [[ ! -x "$BUNDLE/Contents/MacOS/$APP_NAME" || ! -f "$BUNDLE/Contents/Frameworks/libmpv.2.dylib" ||
      ! -x "$BUNDLE/Contents/Frameworks/ffmpeg" || ! -x "$BUNDLE/Contents/Frameworks/ffprobe" ]]; then
  echo 'ERROR: Incomplete bundle: the program, libmpv, ffmpeg or ffprobe is missing.' >&2
  exit 1
fi

# Every library must come from the bundle or macOS itself, never from Homebrew.
leaks="$(find "$BUNDLE/Contents" -type f \( -name '*.dylib' -o -name '*.so' -o -perm -u+x \) -print0 |
  xargs -0 otool -L 2>/dev/null | grep -E '^\s+(/opt/homebrew|/usr/local)/' | sort -u || true)"
if [[ -n "$leaks" ]]; then
  echo 'ERROR: The bundle still links libraries outside it:' >&2
  echo "$leaks" >&2
  exit 1
fi

printf 'BUILD OK: %s\n' "$BUNDLE"

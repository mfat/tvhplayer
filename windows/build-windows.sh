#!/usr/bin/env bash
# Build TVHplayer for Windows (x86_64) with PyInstaller. Runs in Git Bash.
#
#   windows/build-windows.sh VERSION
#
# VERSION is a release tag (v4.0.2) or a test build label (ci12). Needs Inno
# Setup 6 for the installer (choco install innosetup).
#
# Plays with mpv: libmpv-2.dll (FFmpeg built in) from the pinned shinchiro
# build that mpv.io links, and ffmpeg and ffprobe from BtbN's FFmpeg build.
# Writes windows/dist/tvhplayer-VERSION-windows-x86_64-setup.exe, the
# installer, and windows/dist/tvhplayer-VERSION-windows-x86_64.zip, the same
# app to unpack and run.
set -euo pipefail

# Windows paths (D:/a/...): PyInstaller is a Windows program and does not
# understand Git Bash's /d/a/... inside its SOURCE;DEST arguments.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -W)"
HERE="$ROOT/windows"
# shellcheck source=windows/pins.env
. "$HERE/pins.env"
PYTHON="${PYTHON:-python}"
CURL="${CURL:-curl}"
[[ $# -eq 1 ]] || { echo "usage: $0 VERSION" >&2; exit 2; }
VERSION=$1
WORK="$HERE/build"
DIST="$HERE/dist"
if [[ -n "${TVHPLAYER_BUILD_LABEL:-}" ]]; then
  [[ "$TVHPLAYER_BUILD_LABEL" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Invalid build label" >&2; exit 2; }
  WORK="$HERE/build-$TVHPLAYER_BUILD_LABEL"
  DIST="$HERE/dist-$TVHPLAYER_BUILD_LABEL"
fi
# Resolve junctions/symlinks before recursively replacing generated output.
"$PYTHON" -c 'import sys; from pathlib import Path; repo=Path(sys.argv[1]).resolve(); base=(repo/"windows").resolve(); assert base.parent == repo; assert all(Path(p).resolve().parent == base for p in sys.argv[2:]), "Build output escaped the Windows packaging directory"' "$ROOT" "$WORK" "$DIST"
rm -rf "$WORK" "$DIST"
mkdir -p "$WORK" "$DIST"
CACHE="$HERE/downloads"
mkdir -p "$CACHE"
fetch() {
  local url=$1 output=$2 digest=$3 cached="$CACHE/$3"
  if [[ ! -f "$cached" ]] || ! echo "$digest  $cached" | sha256sum -c --quiet -; then
    "$CURL" --fail --silent --show-error --location --connect-timeout 20 --max-time 600 --retry 3 -o "$cached.part" "$url"
    echo "$digest  $cached.part" | sha256sum -c --quiet -
    mv "$cached.part" "$cached"
  fi
  cp "$cached" "$output"
}

echo "==> libmpv $MPV_DEV_BUILD"
archive="$WORK/mpv-dev.7z"
fetch "$MPV_DEV_URL" "$archive" "$MPV_DEV_SHA256"
echo "$MPV_DEV_SHA256  $archive" | sha256sum -c --quiet -
7z e -y -o"$WORK" "$archive" libmpv-2.dll >/dev/null
test -f "$WORK/libmpv-2.dll"

echo "==> Vulkan loader $VULKAN_RT_VERSION"
vulkan="$WORK/vulkan-runtime.zip"
fetch "$VULKAN_RT_URL" "$vulkan" "$VULKAN_RT_SHA256"
echo "$VULKAN_RT_SHA256  $vulkan" | sha256sum -c --quiet -
7z e -y -o"$WORK/vulkan" "$vulkan" "*/x64/vulkan-1.dll" "*/VulkanRT-License.txt" >/dev/null
test -f "$WORK/vulkan/vulkan-1.dll"

echo "==> FFmpeg $FFMPEG_BUILD"
ffmpeg="$WORK/ffmpeg.zip"
fetch "$FFMPEG_URL" "$ffmpeg" "$FFMPEG_SHA256"
echo "$FFMPEG_SHA256  $ffmpeg" | sha256sum -c --quiet -
7z e -y -o"$WORK/ffmpeg" "$ffmpeg" "*/bin/ffmpeg.exe" "*/bin/ffprobe.exe" "*/LICENSE.txt" >/dev/null
test -f "$WORK/ffmpeg/ffmpeg.exe" && test -f "$WORK/ffmpeg/ffprobe.exe"

echo "==> Python packages"
"$PYTHON" -m pip install --quiet -r "$HERE/requirements-build.txt"

echo "==> Icon"
icon="$WORK/tvhplayer.ico"
"$PYTHON" "$ROOT/packaging/render_icon.py" "$icon"

echo "==> PyInstaller"
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name TVHplayer \
  --icon "$icon" \
  --paths "$ROOT/tvhplayer" \
  --collect-submodules core \
  --collect-all pychromecast \
  --collect-all zeroconf \
  --hidden-import resources_rc \
  --hidden-import casttube \
  --hidden-import google.protobuf \
  --add-binary "$WORK/libmpv-2.dll;." \
  --add-binary "$WORK/vulkan/vulkan-1.dll;." \
  --add-data "$WORK/vulkan/VulkanRT-License.txt;licenses" \
  --add-binary "$WORK/ffmpeg/ffmpeg.exe;." \
  --add-binary "$WORK/ffmpeg/ffprobe.exe;." \
  --add-data "$WORK/ffmpeg/LICENSE.txt;licenses/ffmpeg" \
  --add-data "$ROOT/icons;icons" \
  --distpath "$WORK/dist" \
  --workpath "$WORK/pyinstaller" \
  --specpath "$WORK" \
  "$ROOT/tvhplayer/tvhplayer.py"

app="$WORK/dist/TVHplayer"
test -f "$app/TVHplayer.exe"
# Optional offline backend artifact. Kept next to the EXE across installer/ZIP builds.
# Public builds remain gated until Windows-host acceptance tests pass.
if [[ -n "${TVHPLAYER_BACKEND_BUNDLE:-}" ]]; then
  "$PYTHON" "$HERE/backend/verify-bundle.py" "$TVHPLAYER_BACKEND_BUNDLE"
  mkdir -p "$app/backend"
  for name in tvheadend.tar manifest.json sbom.spdx.json licenses.tar.gz TVHplayer-LICENSE.txt tvheadend-source.md; do
    cp "$TVHPLAYER_BACKEND_BUNDLE/$name" "$app/backend/"
  done
  cp "$TVHPLAYER_BACKEND_BUNDLE/corresponding-source.tar.gz" "$DIST/tvhplayer-$VERSION-backend-source.tar.gz"
fi
test -f "$app/_internal/libmpv-2.dll"
test -f "$app/_internal/vulkan-1.dll"
# Cast is imported optionally at runtime; fail the build if PyInstaller omitted it.
test -d "$app/_internal/pychromecast"
test -d "$app/_internal/zeroconf"
"$app/_internal/ffmpeg.exe" -hide_banner -version | head -n 1

echo "==> Installer"
# A test build has no release number; it takes the app's own.
case "$VERSION" in
  v[0-9]*) app_version=${VERSION#v} ;;
  *) app_version=$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' "$ROOT/tvhplayer/tvhplayer.py") ;;
esac
if [[ "${TVHPLAYER_PORTABLE_ONLY:-0}" != 1 ]]; then
  iscc="${ISCC:-C:/Program Files (x86)/Inno Setup 6/ISCC.exe}"
  "$iscc" -Q \
    "-DAppVersion=$app_version" "-DVersionLabel=$VERSION" \
    "-DRepoRoot=$ROOT" "-DBundleDir=$app" "-DOutputDir=$DIST" "-DIconFile=$icon" \
    "$HERE/tvhplayer.iss"
  test -f "$DIST/tvhplayer-$VERSION-windows-x86_64-setup.exe"
fi

echo "==> Zip"
zip="$DIST/tvhplayer-$VERSION-windows-x86_64.zip"
(cd "$WORK/dist" && 7z a -tzip -mx=7 "$zip" TVHplayer >/dev/null)
echo "==> Built $zip"

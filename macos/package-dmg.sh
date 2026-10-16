#!/usr/bin/env bash
# Create a drag-and-drop macOS DMG from the built TVHplayer application.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: Disk images must be created on macOS." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
APP_NAME="${TVHPLAYER_APP_NAME:-TVHplayer-MacOS-Intel}"
APP="$ROOT/dist/$APP_NAME.app"
OUTPUT="$ROOT/dist/$APP_NAME.dmg"

if [[ ! -d "$APP" ]]; then
  echo "ERROR: Build the application before packaging: $APP" >&2
  exit 1
fi
codesign --verify --deep "$APP"

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/tvhplayer-dmg.XXXXXX")"
MOUNT="$(mktemp -d "${TMPDIR:-/tmp}/tvhplayer-dmg-mount.XXXXXX")"
mounted=0
cleanup() {
  if [[ "$mounted" == 1 ]]; then hdiutil detach "$MOUNT" >/dev/null 2>&1 || true; fi
  rm -rf -- "$STAGE" "$MOUNT"
}
trap cleanup EXIT

ditto "$APP" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/INSTALL.txt" <<'INSTRUCTIONS'
TVHplayer — Intel macOS development build

1. Install VLC 3.0.24 for Intel macOS into /Applications/VLC.app first.
   TVHplayer requires VLC's native playback libraries.
2. Drag TVHplayer-MacOS-Intel.app onto the Applications shortcut.
3. Launch the installed app from /Applications.

The application is ad-hoc signed but not notarized by Apple.
macOS may request approval via System Settings > Privacy & Security.

Do not upload application log files that contain private server information.
INSTRUCTIONS

rm -f "$OUTPUT"
hdiutil create -volname 'TVHplayer Intel' \
  -srcfolder "$STAGE" -format UDZO -ov "$OUTPUT" >/dev/null

hdiutil verify "$OUTPUT" >/dev/null
hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT" "$OUTPUT" >/dev/null
mounted=1
test -d "$MOUNT/$APP_NAME.app"
test -L "$MOUNT/Applications"
test "$(readlink "$MOUNT/Applications")" = '/Applications'
test -f "$MOUNT/INSTALL.txt"
codesign --verify --deep "$MOUNT/$APP_NAME.app"
hdiutil detach "$MOUNT" >/dev/null
mounted=0

(cd "$ROOT/dist" && shasum -a 256 "$APP_NAME.dmg" > "$APP_NAME.dmg.sha256")
echo "DMG OK: $OUTPUT"

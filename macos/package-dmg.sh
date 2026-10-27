#!/usr/bin/env bash
# Create a drag-and-drop macOS DMG from the built TVHplayer application.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: Disk images must be created on macOS." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
case "$(uname -m)" in
  arm64) DEFAULT_NAME=TVHplayer-MacOS-AppleSilicon; VOLUME='TVHplayer Apple Silicon' ;;
  *) DEFAULT_NAME=TVHplayer-MacOS-Intel; VOLUME='TVHplayer Intel' ;;
esac
APP_NAME="${TVHPLAYER_APP_NAME:-$DEFAULT_NAME}"
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
cat > "$STAGE/INSTALL.txt" <<INSTRUCTIONS
TVHplayer for macOS

1. Drag $APP_NAME.app onto the Applications shortcut.
2. Launch the installed app from /Applications.

It plays with mpv, which is inside the app; nothing else needs installing.

The application is ad-hoc signed but not notarized by Apple.
macOS may request approval via System Settings > Privacy & Security.

Do not upload application log files that contain private server information.
INSTRUCTIONS

rm -f "$OUTPUT"
hdiutil create -volname "$VOLUME" \
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

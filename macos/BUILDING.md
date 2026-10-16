# Building TVHplayer for Intel macOS

This is a reproducible development build for **Intel (x86_64) macOS**, using Python **3.15.0**, PyInstaller **6.22.3**, and VLC **3.0.24**. Homebrew is not required.

## Build locally

Install [Python 3.15.0](https://www.python.org/downloads/release/python-3150/) and [VLC 3.0.24 for Intel macOS](https://get.videolan.org/vlc/3.0.24/macosx/vlc-3.0.24-intel64.dmg). VLC must be installed in `/Applications/VLC.app`.

From the repository root:

```bash
/Library/Frameworks/Python.framework/Versions/3.15/bin/python3.15 -m venv macos/.venv315
source macos/.venv315/bin/activate
python -m pip install -r macos/requirements-build.txt
bash macos/build-macos.sh
```

The output is `macos/dist/TVHplayer-MacOS-Intel.app`. To create an installable drag-and-drop disk image:

```bash
bash macos/package-dmg.sh
```

The resulting `macos/dist/TVHplayer-MacOS-Intel.dmg` includes the app, an Applications shortcut, and installation instructions. A separate `.dmg.sha256` file permits checksum verification.

**Runtime dependency:** The generated `.app` bundles Python/Qt and VLC plugins, but does **not** bundle the native `libvlc.dylib` and `libvlccore.dylib`. VLC 3.0.24 must therefore remain installed at `/Applications/VLC.app` on the destination Mac. This is a development application bundle, not a self-contained VLC distribution.

Start it from Terminal to see diagnostic output:

```bash
./macos/dist/TVHplayer-MacOS-Intel.app/Contents/MacOS/TVHplayer-MacOS-Intel
```

## VLC plugin cache correction

VLC's `plugins.dat` cache records plugin file metadata. PyInstaller copies/signs plugins, changing file metadata. Including the source cache produces many `stale plugins cache: modified ...` startup messages.

`macos/build-macos.sh` stages the VLC plugins into a temporary folder using `rsync --exclude=plugins.dat`, then packages that folder. The script checks that no `plugins.dat` exists in the completed application. LibVLC discovers the bundled plugins at runtime.

Do not copy an existing `plugins.dat` into the completed bundle. The VLC installation itself is never modified by the local build.

## Build from GitHub Actions

The dedicated [Build TVHplayer (macOS Intel)](../.github/workflows/build-macos.yml) workflow runs on `macos-15-intel`. Because the Python 3.15 stable package may not be available through `actions/setup-python` yet, the workflow instead downloads and verifies the official Python 3.15.0 macOS installer. It also downloads and SHA-256-verifies the official VLC 3.0.24 Intel DMG.

After building and checking the bundle, GitHub Actions uploads `TVHplayer-MacOS-Intel.dmg`, its `.sha256` manifest and `TVHplayer-MacOS-Intel.zip` as downloadable workflow artifacts. The `.dmg` is the drag-and-drop installer; the ZIP preserves the `.app` structure. The workflow runs on pushes to the packaging branch and matching pull requests. Once the workflow is on the default branch, it can also be launched manually from GitHub's **Actions** tab.

Builds use ad-hoc signing, not Apple Developer ID signing/notarization. The CI runner uses macOS 15. The previous GitHub-built ZIP launched successfully on Intel macOS Ventura 13.7.8; the new DMG must still be tested after downloading.

The workflow packages the **exact branch/commit it runs on**. Building `main` before PRs #32 and #33 are merged does not include those application fixes. For integration testing, apply the packaging changes on a local test branch that already contains those fixes.

## Notes

- The original multi-platform tag-release workflow retains its build commands. The packaging PR also removes invalid `env` references from its matrix artifact names; its retired runners and unrelated platform builds remain outside this change.
- Local output is confined to `macos/build/` and `macos/dist/`; the installed VLC and TVHplayer applications are not overwritten.
- Application runtime logs may contain TVHeadend credentials. Never attach unredacted logs or `~/.tvhplayer.conf` to a public GitHub issue or PR.

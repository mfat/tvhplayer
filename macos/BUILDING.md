# Building TVHplayer for macOS

The build makes an app for the Mac it runs on: **Intel (x86_64)** or **Apple Silicon (arm64)**. It uses Python **3.15.0**, PyInstaller **6.22.3**, and **mpv** from Homebrew. libmpv and every library it needs go inside the app, so the finished app runs on Macs without Homebrew.

Homebrew's libraries are built for the macOS version they were installed on. That version is the oldest macOS the app runs on.

## Build locally

Install [Python 3.15.0](https://www.python.org/downloads/release/python-3150/) and mpv:

```bash
brew install mpv
```

From the repository root:

```bash
/Library/Frameworks/Python.framework/Versions/3.15/bin/python3.15 -m venv macos/.venv315
source macos/.venv315/bin/activate
python -m pip install -r macos/requirements-build.txt
bash macos/build-macos.sh
```

The output is `macos/dist/TVHplayer-MacOS-Intel.app` or `macos/dist/TVHplayer-MacOS-AppleSilicon.app`. The build stops if anything in the app still links a library from Homebrew's folders. To create the drag-and-drop disk image:

```bash
bash macos/package-dmg.sh
```

The `.dmg` holds the app, an Applications shortcut, and installation instructions; a `.dmg.sha256` file sits next to it.

Start the app from Terminal to see diagnostic output:

```bash
./macos/dist/TVHplayer-MacOS-AppleSilicon.app/Contents/MacOS/TVHplayer-MacOS-AppleSilicon
```

The log is in `~/Library/Logs/TVHplayer/app.log`.

## Playback engine

The app plays with mpv. When an installed VLC is present at `/Applications/VLC.app`, it can be chosen in Settings > Playback instead, and the app uses it if libmpv cannot be loaded.

## GitHub Actions

[macOS build](../.github/workflows/build-macos.yml) builds both apps: Intel on `macos-15-intel` (so it needs macOS 15 or newer) and Apple Silicon on `macos-14` (macOS 14 or newer). It installs the verified official Python 3.15.0 package, builds, uninstalls Homebrew's mpv, and starts the app without a screen to check that it plays with its own libmpv. On a release tag it attaches `tvhplayer-VERSION-macos-x86_64.dmg` and `tvhplayer-VERSION-macos-arm64.dmg` to the release.

Builds use ad-hoc signing, not Apple Developer ID signing and notarization.

Application logs may contain Tvheadend credentials. Never attach unredacted logs or the configuration file to a public issue.

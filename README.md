<a href='https://flathub.org/apps/io.github.mfat.tvhplayer'>
    <img width='240' alt='Get it on Flathub' src='https://flathub.org/api/badge?locale=en'/>
  </a>



# TVHplayer
Watch live TV and record your favorite shows right on your PC or laptop. Supports IPTV, HDHomerun and more. 




https://github.com/user-attachments/assets/81b82de6-d414-4de1-824e-5ae826cfe540




## About
TVHplayer is a cross-platform desktop app for watching and recording live TV using [Tvheadend](https://tvheadend.org/), a mature and feature-rich streaming server and recorder for Linux. It supports IPTV, satellite receivers, USB tuners and HDHomerun. This application is a client for Tvheadend.

<img width="1965" height="1055" alt="image" src="https://github.com/user-attachments/assets/fe5fae0a-90df-45f0-9bcd-a272cefd76ba" />


## Do I need a Tvheadend server to use this?
No, TVHplayer comes with its own built-in server and works out of the box. But it can also connect to your existing Tvheadend servers too. You can add as many servers as you want.

## Features

**Watch**
- Live TV and radio from one or more Tvheadend servers
- Cast live channels to Chromecast and Cast-enabled televisions from the player bar
- Timeshif

**Built-in server (Linux and Windows)**
- Optional bundled Tvheadend; existing remote servers remain available
- Native Linux backend, or WSL Containers on Windows (no Docker or separate Ubuntu installation)
- Windows does not provide USB tuner passthrough; use supported network tuners or a remote server

**TV guide**
- Browse EPG
- Fetch missing program guides from online sources
- Pause, rewind, and replay live TV in real time (timeshift)

**Record**
- Instant and scheduled recordings
- Record directly on local computer
- Convert recordings into edit-friendly MP4 files

## Download
- **Flatpak:** [Flathub](https://flathub.org/apps/io.github.mfat.tvhplayer)
- **AppImage:** [x86_64](https://mfat.github.io/tvhplayer/download.html?format=appimage-x86_64)
- **deb** (Ubuntu 24.04, Debian 13): [x86_64](https://mfat.github.io/tvhplayer/download.html?format=deb-amd64) · [arm64](https://mfat.github.io/tvhplayer/download.html?format=deb-arm64)
- **rpm** (Fedora 44): [x86_64](https://mfat.github.io/tvhplayer/download.html?format=rpm-x86_64) · [arm64](https://mfat.github.io/tvhplayer/download.html?format=rpm-aarch64)
- **macOS:** [Apple silicon](https://mfat.github.io/tvhplayer/download.html?format=macos-arm64) · [Intel](https://mfat.github.io/tvhplayer/download.html?format=macos-x86_64)
- **Windows:** [installer](https://mfat.github.io/tvhplayer/download.html?format=windows-setup) · [portable zip](https://mfat.github.io/tvhplayer/download.html?format=windows-zip)

The download links automatically get the latest version. The Flatpak, AppImage, deb and rpm include the built-in server, mpv and ffmpeg, or pull them in as dependencies. Complete Windows installer and ZIP packages include the optional offline WSL Containers backend. macOS connects to an existing Tvheadend server.

Python requirements depend on the package format:

| Package | Python requirement |
| --- | --- |
| deb | System Python **3.11 or newer**. One package per architecture is built on Ubuntu 24.04 and tested on Ubuntu 24.04 and Debian 13. The C decoder uses Python's stable ABI. |
| rpm | Built for **Fedora 44** and its system Python and libraries. Rebuild for a different Fedora release; newer Fedora versions are not automatically compatible. |
| AppImage, Windows installer/ZIP, macOS app | Python and the matching C decoder are bundled. No separate Python installation is needed. |
| Flatpak | Python and the matching C decoder run inside the KDE runtime. No system Python requirement. |

The deb's Python 3.11 minimum does not make it compatible with every older
Linux distribution: its system libraries must also satisfy the package's
dependencies. Ubuntu 24.04 and Debian 13 are the build/test targets.

You can also [browse all releases](https://github.com/mfat/tvhplayer/releases).

See the [User Guide](https://github.com/mfat/tvhplayer/wiki/User-Guide) (Help → User Guide) for everything else.

## Help and support
- [Open a bug report](https://github.com/mfat/tvhplayer/issues/new)
- Help → Open Log Folder shows the app's log (`app.log`) and the built-in server's log (`tvheadend.log`). Please attach them to bug reports.

## Run from source
The source package declares Python **3.9 or newer** in `setup.py`. You also
need libmpv, ffmpeg and the Python dependencies in `requirements.txt`.
Python 3.9/3.10 use PyChromecast 13; Python 3.11 and newer use PyChromecast 14
or newer, as selected by the dependency markers. This source minimum is
separate from the deb's Python 3.11 minimum.

```bash
git clone https://github.com/mfat/tvhplayer.git
cd tvhplayer
python3 -m pip install -r requirements.txt
python3 tvhplayer/tvhplayer.py
```

For large channel lists, also build the C decoder for server messages (it needs a C compiler and the Python headers, such as `python3-dev`); without it the app reads them in Python, several times slower:

```bash
python3 packaging/build-native.py
```

The default decoder build targets the Python interpreter used to build it;
rebuild it after changing Python minor versions. The deb build instead uses
`python3 packaging/build-native.py --abi3`, which requires Python 3.11 or newer
and produces a decoder that also loads on newer Python minor versions.

To use the built-in server from a checkout, build Tvheadend in a checkout next to this one, so the binary is at `../tvheadend/build.linux/tvheadend`, or copy it to `build/tvheadend`. See [docs/tvheadend-source.md](docs/tvheadend-source.md) for the Tvheadend version the packages use.

Run the tests with `python3 -m pytest tests`.

### Debug switches
Set these when starting the app; their output goes to the terminal and `app.log`. They are off by default.

- `TVHPLAYER_DEBUG_SPINNER=1` reports what holds up the spinner shown while a channel starts. Each tick that comes over 50 ms late is printed with how late it was and what every thread was doing meanwhile: the main thread's stack in full, and the other threads marked RUNNING (running Python, so holding the GIL) or waiting. A Python-level dump of all threads, which `faulthandler` takes without the GIL, follows when a tick is over 60 ms late. Each start ends with a line such as `spinner stopped after 8.2 s: 412 ticks, 9 late, worst 180 ms`.
- `TVHPLAYER_DEBUG_CURSOR=1` reports cursor and window changes, programs the app starts, and event loop stalls over 250 ms, with the main thread's stack when one lasts over a second. `2` adds Qt's Wayland logging.

```bash
TVHPLAYER_DEBUG_SPINNER=1 python3 tvhplayer/tvhplayer.py
```

## Technical information
- Talks to Tvheadend over HTSP or its HTTP JSON API
- Plays with libmpv (OpenGL into the window on Wayland and X11)
- Records and converts with ffmpeg
- Built with PyQt6

## Support development
Bitcoin: `bc1qqtsyf0ft85zshsnw25jgsxnqy45rfa867zqk4t`

Doge:  `DRzNb8DycFD65H6oHNLuzyTzY1S5avPHHx`

## Windows built-in server

Windows packages can include an offline WSL Containers backend with native UI,
automatic credentials and HDHomeRun discovery. Build/setup instructions and
release qualification notes are in [windows/backend/README.md](windows/backend/README.md).

On first use, TVHplayer checks WSL, Virtual Machine Platform, and hardware
virtualization before starting the Windows built-in server. Setup offers the
required installation or repair with administrator permission. After installing
WSL or enabling Virtual Machine Platform, restart **Windows**, even if Windows
does not display a reboot prompt. Reopen TVHplayer to resume setup automatically.
Playlist import into the built-in server becomes available once it is ready;
import into an existing remote server does not require local WSL setup.
If hardware virtualization is disabled or unavailable, TVHplayer disables the
built-in server and its automatic setup checks, including after relaunch.
Remote servers remain usable. After enabling virtualization in BIOS/UEFI, use
the gear button, select Built-in Server, and choose **Enable and check…** to retry.

The installer and ZIP use the same in-app setup. Extract the entire ZIP before
opening TVHplayer. The app requests administrator permission only when you choose
to install/update WSL or enable a required Windows feature. BIOS/UEFI virtualization
must be enabled manually. Settings and restart progress are stored in AppData,
including for the ZIP version. Installing ordinary WSL does not by itself confirm
that WSL Containers can start on your Windows version.

After the built-in server starts with no channels, Set Up Channels offers a tuner
or an IPTV playlist. Closing it lets it appear again next launch; select
**Don’t open setup automatically** to stop automatic offers. It remains available
from File > Set Up Channels. Setup is complete when the server actually has channels.

Startup shows separate stages for checking Windows support, verifying/importing
the server image, preparing settings and storage, and testing the server connection.
When startup fails, the checklist shows what needs attention. Expand **Technical
details** or choose **Copy details** when reporting an unexpected error.

See [first-run validation](windows/backend/VALIDATION.md) for automated checks and
the fresh-Windows/UAC/reboot scenarios that still require an isolated test machine.

<a href='https://flathub.org/apps/io.github.mfat.tvhplayer'>
    <img width='240' alt='Get it on Flathub' src='https://flathub.org/api/badge?locale=en'/>
  </a>



# TVHplayer
Watch and record your favorite shows right on your PC or laptop. Supports IPTV, HDHomerun and more. 

<img width="1418" height="894" alt="main" src="https://github.com/user-attachments/assets/95471032-de4f-4778-a984-722bd2d10dbf" />


## About
TVHplayer is a cross-platform desktop app for watching and recording live TV using [Tvheadend](https://tvheadend.org/), a mature and feature-rich streaming server and recorder for Linux. It supports IPTV, satellite receivers, USB tuners and HDHomerun. This application is a client for Tvheadend.

<img width="1965" height="1055" alt="image" src="https://github.com/user-attachments/assets/fe5fae0a-90df-45f0-9bcd-a272cefd76ba" />


## Who is this for
Use TVHplayer to connect to an existing Tvheadend server, or with its built-in server. You don't need your own server to use the app. 

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
- **deb** (Debian, Ubuntu): [x86_64](https://mfat.github.io/tvhplayer/download.html?format=deb-amd64) · [arm64](https://mfat.github.io/tvhplayer/download.html?format=deb-arm64)
- **rpm** (Fedora): [x86_64](https://mfat.github.io/tvhplayer/download.html?format=rpm-x86_64) · [arm64](https://mfat.github.io/tvhplayer/download.html?format=rpm-aarch64)
- **macOS:** [Apple silicon](https://mfat.github.io/tvhplayer/download.html?format=macos-arm64) · [Intel](https://mfat.github.io/tvhplayer/download.html?format=macos-x86_64)
- **Windows:** [installer](https://mfat.github.io/tvhplayer/download.html?format=windows-setup) · [portable zip](https://mfat.github.io/tvhplayer/download.html?format=windows-zip)

The download links automatically get the latest version. The Flatpak, AppImage, deb and rpm include the built-in server, mpv and ffmpeg, or pull them in as dependencies. Complete Windows installer and ZIP packages include the optional offline WSL Containers backend. macOS connects to an existing Tvheadend server.

You can also [browse all releases](https://github.com/mfat/tvhplayer/releases).

See the [User Guide](https://github.com/mfat/tvhplayer/wiki/User-Guide) (Help → User Guide) for everything else.

## Help and support
- [Open a bug report](https://github.com/mfat/tvhplayer/issues/new)
- Help → Open Log Folder shows the app's log (`app.log`) and the built-in server's log (`tvheadend.log`). Please attach them to bug reports.

## Run from source
You need Python 3, libmpv and ffmpeg.

```bash
git clone https://github.com/mfat/tvhplayer.git
cd tvhplayer
python3 -m pip install -r requirements.txt
python3 tvhplayer/tvhplayer.py
```

To use the built-in server from a checkout, build Tvheadend in a checkout next to this one, so the binary is at `../tvheadend/build.linux/tvheadend`, or copy it to `build/tvheadend`. See [docs/tvheadend-source.md](docs/tvheadend-source.md) for the Tvheadend version the packages use.

Run the tests with `python3 -m pytest tests`.

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

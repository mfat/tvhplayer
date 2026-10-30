<a href='https://flathub.org/apps/io.github.mfat.tvhplayer'>
    <img width='240' alt='Get it on Flathub' src='https://flathub.org/api/badge?locale=en'/>
  </a>

# TVHplayer
Watch and record your favorite shows right on your PC or laptop. Supports IPTV, HDHomerun, USB TV tuners and more. 

<img width="1418" height="894" alt="main" src="https://github.com/user-attachments/assets/95471032-de4f-4778-a984-722bd2d10dbf" />


## About
TVHplayer is a cross-platform desktop app for watching and recording live TV using [Tvheadend](https://tvheadend.org/), a mature and feature-rich streaming server and recorder for Linux. It supports IPTV, satellite receivers, USB tuners and HDHomerun. This application is a client for Tvheadend.

## Who is this for
This is for people who already have a Tvheadend server.

But if you use linux, you can use this as a normal TV and PVR app, even without a server. You just need an IPTV playlist, or a TV tuner. 

## Features

**Watch**
- Live TV and radio from one or more Tvheadend servers
- Cast live channels to Chromecast and Cast-enabled televisions from the player bar

**Built-in server (Linux only)**
- Comes with its own optional Tvheadend out of the box (optional, you can use any server), no need to set up a server to watch IPTV or use a USB tuner

**TV guide**
- Browse EPG
- Fetch missing program guides from online sources

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

The download links automatically get the latest version. The Flatpak, AppImage, deb and rpm include the built-in server, mpv and ffmpeg, or pull them in as dependencies. The macOS and Windows builds connect to an existing Tvheadend server; the built-in server is a Linux-only feature.

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

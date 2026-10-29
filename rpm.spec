# The built-in server. These pins match packaging/tvheadend/pins.env;
# tests/test_packaging_pins.py fails when they disagree.
%global tvh_repo https://github.com/mfat/tvheadend
%global tvh_commit 40e88d4cef2c81e44474e75fd2f1edb232575ceb
%global tvh_version 4.3^2904.g40e88d4ce
%global scan_commit 31d6fb8f8b86e204518ada99bfb8cf6807c717e5
%global dvbcsa_version 1.1.0
%global hdhomerun_version 20250815
# Fedora does not package python-mpv; it ships only libmpv (mpv-libs).
%global mpv_wheel mpv-1.0.8-py3-none-any.whl
%global mpv_wheel_sha256 dcf77f612e3f5ce49bd89393f37d286de7ac290db6b0800f1fdcfe0aeb5ba9b8

Name:           tvhplayer
Version:        4.4.1
Release:        1%{?dist}
Summary:        Tvheadend desktop client with a built-in server

# tvhplayer and Tvheadend: GPL-3.0-or-later. Scan tables: GPL-2.0-only and LGPL-2.1-or-later.
# libdvbcsa: GPL-2.0-or-later. libhdhomerun: LGPL-2.1-or-later.
# python-mpv: GPL-2.0-or-later OR LGPL-2.1-or-later.
License:        GPL-3.0-or-later AND GPL-2.0-only AND GPL-2.0-or-later AND LGPL-2.1-or-later
URL:            https://github.com/mfat/tvhplayer
Source0:        %{name}-%{version}.tar.gz
Source1:        %{tvh_repo}/archive/%{tvh_commit}/tvheadend-%{tvh_commit}.tar.gz
Source2:        https://github.com/tvheadend/dtv-scan-tables/archive/%{scan_commit}/dtv-scan-tables-%{scan_commit}.tar.gz
Source3:        https://download.videolan.org/pub/videolan/libdvbcsa/%{dvbcsa_version}/libdvbcsa-%{dvbcsa_version}.tar.gz
Source4:        https://download.silicondust.com/hdhomerun/libhdhomerun_%{hdhomerun_version}.tgz
Source5:        https://files.pythonhosted.org/packages/f4/cf/0d5f52753366ecf2c3d763e331dcda54b0f20a1a8e52b175feb9c625399d/%{mpv_wheel}

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  pkgconf-pkg-config
BuildRequires:  python3
BuildRequires:  python3-devel
BuildRequires:  gettext
BuildRequires:  bzip2
BuildRequires:  pkgconfig(openssl)
BuildRequires:  pkgconfig(zlib)
BuildRequires:  pkgconfig(libpcre2-8)
BuildRequires:  pkgconfig(dbus-1)
BuildRequires:  desktop-file-utils
# Tvheadend's configure finds its tools with which.
BuildRequires:  which
# Current config.guess and config.sub for libdvbcsa, whose own predate aarch64.
BuildRequires:  redhat-rpm-config

Requires:       python3
Requires:       python3-pyqt6
Requires:       python3-requests
Requires:       python3-psutil
Requires:       python3-chromecast
Requires:       qt6-qtsvg
Requires:       /usr/bin/ffmpeg
Requires:       mpv-libs

Provides:       bundled(tvheadend) = %{tvh_version}
Provides:       bundled(libdvbcsa) = %{dvbcsa_version}
Provides:       bundled(libhdhomerun) = %{hdhomerun_version}
Provides:       bundled(python3dist(mpv)) = 1.0.8

%description
A desktop client for Tvheadend for live TV playback and recording, with
an EPG, recording on the server or locally, and support for several
Tvheadend servers.

It includes a built-in Tvheadend that starts and stops with the app. It
lives in /usr/libexec/tvhplayer and never touches a Tvheadend installed on
the system.

%prep
%autosetup
echo "%{mpv_wheel_sha256}  %{SOURCE5}" | sha256sum -c -
# build-tvheadend.sh reads its archives from one folder.
mkdir tvheadend-sources
cp -p %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} tvheadend-sources/

%build
packaging/tvheadend/build-tvheadend.sh build tvheadend-sources tvheadend-build --bundle-dvbcsa

%install
packaging/tvheadend/build-tvheadend.sh install tvheadend-build %{buildroot}

# Same layout as the Flatpak: the app reads icons/ next to its own code.
mkdir -p %{buildroot}%{_datadir}/%{name}
cp -a tvhplayer/. %{buildroot}%{_datadir}/%{name}/
cp -a icons %{buildroot}%{_datadir}/%{name}/icons
chmod 644 %{buildroot}%{_datadir}/%{name}/icons/*
find %{buildroot}%{_datadir}/%{name} -type d -name __pycache__ -prune -exec rm -rf {} +
# python-mpv is one module; tvhplayer.py imports it from its own folder.
%{python3} -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("mpv.py", sys.argv[2])' \
    %{SOURCE5} %{buildroot}%{_datadir}/%{name}
sed -i '1{/^#!/d}' %{buildroot}%{_datadir}/%{name}/mpv.py

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{name} << 'EOF'
#!/bin/sh
exec %{python3} %{_datadir}/%{name}/tvhplayer.py "$@"
EOF
chmod 755 %{buildroot}%{_bindir}/%{name}

# Desktop entry basename matches QGuiApplication.setDesktopFileName.
install -p -D -m 644 io.github.mfat.tvhplayer.desktop %{buildroot}%{_datadir}/applications/io.github.mfat.tvhplayer.desktop
install -p -D -m 644 icons/tvhplayer.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.mfat.tvhplayer.svg
install -p -D -m 644 io.github.mfat.tvhplayer.metainfo.xml %{buildroot}%{_metainfodir}/io.github.mfat.tvhplayer.metainfo.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.mfat.tvhplayer.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{_libexecdir}/%{name}/
%{_datadir}/%{name}/
%{_datadir}/applications/io.github.mfat.tvhplayer.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.mfat.tvhplayer.svg
%{_metainfodir}/io.github.mfat.tvhplayer.metainfo.xml

%changelog
* Thu Oct 29 2026 mFat <newmfat@gmail.com> - 4.4.1-1
- Record local footage from the timeshift position
- Fix pause and resume without a seekable buffer
- Keep batched live read-ahead from moving the timeshift bar

* Thu Oct 29 2026 mFat <newmfat@gmail.com> - 4.4.0-1
- Add pause, skip, a seek bar and an opt-in disk timeshift buffer
- Add previous and next channel controls with Ctrl+PgUp/PgDown
- Add a Start channels faster setting that shortens mpv's stream probe
- Replace the blinking REC label with a Recording pill that opens Tasks
- Show the player bar's recording state for the active channel only
- Mark the playing channel with a play icon instead of an accent bar, and hide Status by default
- Put Play first in the player bar and add channel buttons to the tab order
- Switch to Material Symbols Outlined icons with an outlined play button
- Make the status bar taller and pad its contents

* Thu Oct 29 2026 mFat <newmfat@gmail.com> - 4.3.0-1
- Add an Organic look in Settings > Appearance, beside TVHplayer and the Qt styles
- Add Accent color and Window color settings, with GNOME blue as the default accent
- Add channel list row sizes and row styles; row dividers are off by default
- Let channel list columns be resized and remember their widths
- Hide the channel number column by default
- Switch the stream profile from the playback menus; playback restarts on the new profile
- Check for updates and offer a Download button for new releases
- Show the Cast button in blue while casting
- Show the volume level on the mute button and use sharper fullscreen and SVG icons
- Put play, volume and recording shortcuts in the Playback menu
- Let Tab leave the channel list and other tables
- Keep player bar controls from taking focus on click
- Fix the ambiguous Ctrl+- shortcut for shorter channel rows
- Use macOS keys for quit, fullscreen and help, and in key names in text

* Thu Oct 29 2026 mFat <newmfat@gmail.com> - 4.2.2-1
- Add File → Manage Servers to add, edit and test servers in one place
- Check saved remote servers in the background and update their status dots automatically
- Add an Apply button to the connection dialog
- Verify the HTTP playback endpoint when testing HTSP servers
- Normalize server addresses to http:// and keep the right default port for port-less addresses
- Don't discard the config when a saved server address can't be parsed
- Add a Live resize setting; panes resize only on release by default before Qt 6.11
- Update the built-in log viewer live and keep log viewers in front of Server Management
- Rename File → Playlists to Manage Playlists

* Thu Oct 29 2026 mFat <newmfat@gmail.com> - 4.2.1-1
- Add provider-aware IPTV imports
- Let IPTV source settings update credentials without duplicating playlists
- Fix MPV render shutdown race
- Fetch fresh Now/Next via lightweight mode=now grid instead of full channel sync
- Match live EPG grid results by channel UUID, not stale HTSP event IDs
- Only show No EPG after a successful programme query
- Do not label locally expired EPG programmes as missing
- Stop publishing SHA sidecars and the Fedora source RPM

* Wed Oct 28 2026 mFat <newmfat@gmail.com> - 4.2.0-1
- Play with libmpv only on every platform; VLC is gone
- Cast live channels to Chromecast from the player bar
- Ship Chromecast with every packaged build
- Show channel logos when the TVHeadend server has none
- Show which Chromecast is playing under the player logo
- Flatpak title-bar button order follows Plasma without reading the host's kwinrc
- Use the TVHplayer app bundle name on macOS

* Thu Oct 29 2026 mFat <newmfat@gmail.com> - 4.1-1
- Plays with mpv only; VLC is no longer a playback engine or package dependency
- New AppImage for Linux: one file that runs on Ubuntu 24.04, Debian 13, Fedora 40 and newer
- New Windows installer, and Windows plays with mpv without VLC or anything else to install
- macOS builds for Apple Silicon and Intel play with mpv, without VLC or Homebrew
- Recording to this computer works on Windows and macOS, with no console window on Windows and MP4 files that play after stopping
- The app starts with mpv on Ubuntu 24.04, where Auto deinterlacing stopped it
- Without VLC, the app plays with mpv on Linux X11 desktops too
- The window shows the TVHplayer icon on Windows and macOS, and the app icons are sharp at every size
- The Flatpak builds on ARM and no longer asks for access to the notification service

* Tue Oct 27 2026 mFat <newmfat@gmail.com> - 4.0.1-1
- Release 4.0.1

* Tue Oct 27 2026 mFat <newmfat@gmail.com> - 4.0-1
- Release 4.0

* Fri Oct 23 2026 mFat <newmfat@gmail.com> - 3.5.5-1
- Package the built-in Tvheadend server

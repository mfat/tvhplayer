# The built-in server. These pins match packaging/tvheadend/pins.env;
# tests/test_packaging_pins.py fails when they disagree.
%global tvh_commit 51ec612fa22c4c78b4697e4c262c943da9cbd6cc
%global tvh_version 4.3^2899.g51ec612fa
%global scan_commit 31d6fb8f8b86e204518ada99bfb8cf6807c717e5
%global dvbcsa_version 1.1.0
%global hdhomerun_version 20250815
# Fedora does not package python-vlc. The Flatpak pins the same wheel.
%global vlc_wheel python_vlc-3.0.21203-py3-none-any.whl
%global vlc_wheel_sha256 1613451a31b692ec276296ceeae0c0ba82bfc2d094dabf9aceb70f58944a6320

Name:           tvhplayer
Version:        3.5.5
Release:        1%{?dist}
Summary:        Tvheadend desktop client with a built-in server

# tvhplayer and Tvheadend: GPL-3.0-or-later. Scan tables: GPL-2.0-only and LGPL-2.1-or-later.
# libdvbcsa: GPL-2.0-or-later. libhdhomerun and python-vlc: LGPL-2.1-or-later.
License:        GPL-3.0-or-later AND GPL-2.0-only AND GPL-2.0-or-later AND LGPL-2.1-or-later
URL:            https://github.com/mfat/tvhplayer
Source0:        %{name}-%{version}.tar.gz
Source1:        https://github.com/tvheadend/tvheadend/archive/%{tvh_commit}/tvheadend-%{tvh_commit}.tar.gz
Source2:        https://github.com/tvheadend/dtv-scan-tables/archive/%{scan_commit}/dtv-scan-tables-%{scan_commit}.tar.gz
Source3:        https://download.videolan.org/pub/videolan/libdvbcsa/%{dvbcsa_version}/libdvbcsa-%{dvbcsa_version}.tar.gz
Source4:        https://files.pythonhosted.org/packages/5b/ee/7d76eb3b50ccb1397621f32ede0fb4d17aa55a9aa2251bc34e6b9929fdce/%{vlc_wheel}
Source5:        https://download.silicondust.com/hdhomerun/libhdhomerun_%{hdhomerun_version}.tgz

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

Requires:       python3
Requires:       python3-pyqt6
Requires:       python3-requests
Requires:       python3-psutil
Requires:       qt6-qtsvg
Requires:       vlc-libs
Requires:       vlc-plugins-base
Requires:       /usr/bin/ffmpeg

Provides:       bundled(tvheadend) = %{tvh_version}
Provides:       bundled(libdvbcsa) = %{dvbcsa_version}
Provides:       bundled(libhdhomerun) = %{hdhomerun_version}
Provides:       bundled(python3dist(python-vlc)) = 3.0.21203

%description
A desktop client for Tvheadend for live TV playback and recording, with
an EPG, recording on the server or locally, and support for several
Tvheadend servers.

It includes a built-in Tvheadend that starts and stops with the app. It
lives in /usr/libexec/tvhplayer and never touches a Tvheadend installed on
the system.

%prep
%autosetup
echo "%{vlc_wheel_sha256}  %{SOURCE4}" | sha256sum -c -
# build-tvheadend.sh reads its archives from one folder.
mkdir tvheadend-sources
cp -p %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE5} tvheadend-sources/

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
# python-vlc is one module; tvhplayer.py imports it from its own folder.
%{python3} -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("vlc.py", sys.argv[2])' \
    %{SOURCE4} %{buildroot}%{_datadir}/%{name}
sed -i '1{/^#!/d}' %{buildroot}%{_datadir}/%{name}/vlc.py

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
* Fri Oct 23 2026 mFat <newmfat@gmail.com> - 3.5.5-1
- Package the built-in Tvheadend server

#!/bin/sh
# Build the TVHplayer AppImage on Ubuntu 24.04 (x86_64).
#
#   build-appimage.sh VERSION OUTDIR
#
# Writes OUTDIR/tvhplayer-VERSION-x86_64.AppImage.
# It carries Python, PyQt6, libmpv with FFmpeg, the ffmpeg command, and the
# built-in Tvheadend. It has no libvlc: the app plays with mpv everywhere.
# Needs the packages that install-deps.sh installs, and network access for the
# Tvheadend sources, the Python packages and appimagetool.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
# shellcheck source=SCRIPTDIR/pins.env
. "$HERE/pins.env"

die() {
    echo "build-appimage.sh: $*" >&2
    exit 1
}

[ $# -eq 2 ] || die "usage: $0 VERSION OUTDIR"
version=$1
outdir=$(mkdir -p "$2" && cd "$2" && pwd)
[ "$(uname -m)" = x86_64 ] || die "builds on x86_64 only"

work=${WORK:-$ROOT/build/appimage}
APPDIR=$work/AppDir
export APPDIR
python=python3.12
pyver=3.12

fetch() {
    url=$1
    file=$2
    sum=$3
    if [ ! -f "$file" ]; then
        curl --fail --silent --show-error --location --retry 3 --retry-delay 2 -o "$file.part" "$url"
        mv "$file.part" "$file"
    fi
    echo "$sum  $file" | sha256sum -c --quiet - || die "checksum mismatch: $file"
}

rm -rf "$APPDIR"
mkdir -p "$work/downloads" "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share"
downloads=$work/downloads

fetch "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage" \
    "$downloads/appimagetool-$APPIMAGETOOL_VERSION.AppImage" "$APPIMAGETOOL_SHA256"
chmod +x "$downloads/appimagetool-$APPIMAGETOOL_VERSION.AppImage"
fetch "https://raw.githubusercontent.com/AppImageCommunity/pkg2appimage/$EXCLUDELIST_COMMIT/excludelist" \
    "$downloads/excludelist" "$EXCLUDELIST_SHA256"
# libmpv and ffmpeg link libjack, which many desktops do not install.
# The app never talks to a JACK server, so carrying the library is harmless.
excludelist=$work/excludelist
grep -v '^libjack\.so\.0' "$downloads/excludelist" > "$excludelist"

echo "==> Built-in Tvheadend"
"$ROOT/packaging/tvheadend/build-tvheadend.sh" fetch "$downloads/tvheadend"
"$ROOT/packaging/tvheadend/build-tvheadend.sh" build "$downloads/tvheadend" "$work/tvheadend" \
    --bundle-dvbcsa --relocatable
install -m755 "$work/tvheadend/tvheadend/build.linux/tvheadend" "$APPDIR/usr/bin/tvheadend"

echo "==> Python $pyver"
# Python finds its library from its own place: bin/../lib/python3.12.
install -m755 "/usr/bin/$python" "$APPDIR/usr/bin/tvhplayer-python3"
cp -a "/usr/lib/python$pyver" "$APPDIR/usr/lib/python$pyver"
(
    cd "$APPDIR/usr/lib/python$pyver"
    rm -rf test idlelib tkinter turtledemo lib2to3 ensurepip venv config-* \
        lib-dynload/_tkinter.* site-packages dist-packages
    find . -name __pycache__ -type d -prune -exec rm -rf {} +
)
site=$APPDIR/usr/lib/python3/dist-packages
mkdir -p "$site"
"$python" -m pip install --no-cache-dir --no-compile --only-binary=:all: \
    --target "$site" --requirement "$HERE/requirements.txt"
rm -rf "${site:?}/bin"

# The app uses Qt's widgets, OpenGL, D-Bus and SVG. The rest of PyQt6's Qt
# (QML, Quick, 3D, Multimedia with its own FFmpeg, PDF, ...) only adds size.
(
    cd "$site/PyQt6"
    for module in Qt*.abi3.so; do
        case "$module" in
            QtCore.*|QtGui.*|QtWidgets.*|QtDBus.*|QtOpenGL.*|QtOpenGLWidgets.*|QtSvg.*|QtSvgWidgets.*|QtNetwork.*|QtXml.*) ;;
            *) rm -f "$module" "${module%%.*}.pyi" ;;
        esac
    done
    cd Qt6
    rm -rf qml qsci
    for lib in lib/libQt6*; do
        case "${lib#lib/libQt6}" in
            Core.*|Gui.*|Widgets.*|DBus.*|OpenGL.*|OpenGLWidgets.*|Svg.*|SvgWidgets.*|Network.*|Xml.*|WaylandClient.*|WaylandEglClientHwIntegration.*|WlShellIntegration.*|XcbQpa.*) ;;
            *) rm -f "$lib" ;;
        esac
    done
    # Qt Multimedia's own FFmpeg.
    rm -f lib/libavcodec.so.* lib/libavformat.so.* lib/libavutil.so.* lib/libswresample.so.* lib/libswscale.so.*
    cd plugins
    for dir in *; do
        case "$dir" in
            platforms|platformthemes|platforminputcontexts|xcbglintegrations|wayland-*|imageformats|iconengines|tls|networkinformation) ;;
            *) rm -rf "$dir" ;;
        esac
    done
    # Desktop sessions only; the GTK theme plugin would need GTK 3.
    rm -f platforms/libqeglfs.so platforms/libqlinuxfb.so platforms/libqvnc.so \
        platforms/libqvkkhrdisplay.so platforms/libqminimalegl.so platformthemes/libqgtk3.so \
        imageformats/libqpdf.so
)
# python-mpv asks ctypes.util.find_library, which searches only the system's paths.
cat > "$site/sitecustomize.py" <<'EOF'
# The AppImage's libmpv: python-mpv looks it up with ctypes.util.find_library,
# which searches only the system's library paths.
import ctypes.util
import os

_LIBMPV = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'libmpv.so.2'))
_find_library = ctypes.util.find_library


def _find_bundled(name):
    if name == 'mpv' and os.path.exists(_LIBMPV):
        return _LIBMPV
    return _find_library(name)


ctypes.util.find_library = _find_bundled
EOF

echo "==> libmpv and ffmpeg"
cp -L /usr/lib/x86_64-linux-gnu/libmpv.so.2 "$APPDIR/usr/lib/libmpv.so.2"
install -m755 /usr/bin/ffmpeg "$APPDIR/usr/bin/ffmpeg"
install -m755 /usr/bin/ffprobe "$APPDIR/usr/bin/ffprobe"

echo "==> TVHplayer"
app=$APPDIR/usr/share/tvhplayer
mkdir -p "$app"
cp -a "$ROOT/tvhplayer/." "$app/"
cp -a "$ROOT/icons" "$app/icons"
find "$app" -name __pycache__ -type d -prune -exec rm -rf {} +
install -Dm644 "$ROOT/io.github.mfat.tvhplayer.desktop" "$APPDIR/usr/share/applications/io.github.mfat.tvhplayer.desktop"
install -Dm644 "$ROOT/io.github.mfat.tvhplayer.metainfo.xml" "$APPDIR/usr/share/metainfo/io.github.mfat.tvhplayer.appdata.xml"
install -Dm644 "$ROOT/icons/tvhplayer.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/io.github.mfat.tvhplayer.svg"
cp "$ROOT/io.github.mfat.tvhplayer.desktop" "$APPDIR/io.github.mfat.tvhplayer.desktop"
cp "$ROOT/icons/tvhplayer.svg" "$APPDIR/io.github.mfat.tvhplayer.svg"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
# The app finds ffmpeg and ffprobe on PATH.
PATH="$HERE/usr/bin:$PATH"
export PATH
cd "$HERE/usr/share/tvhplayer" || exit 1
exec "$HERE/usr/bin/tvhplayer-python3" -s tvhplayer.py "$@"
EOF
chmod 755 "$APPDIR/AppRun"

echo "==> Libraries"
# Programs, libmpv and Python's own modules take their libraries from usr/lib.
find "$APPDIR/usr/bin" "$APPDIR/usr/lib/libmpv.so.2" "$APPDIR/usr/lib/python$pyver/lib-dynload" \
    "$site" -path "$site/PyQt6" -prune -o -type f \( -perm -u+x -o -name '*.so*' \) -print |
    while read -r elf; do
        file -b "$elf" | grep -q '^ELF' && echo "$elf"
    done > "$work/elf-files"
# shellcheck disable=SC2046 # one file per line, no spaces in the AppDir paths
python3 "$HERE/bundle_libs.py" "$excludelist" "$APPDIR/usr/lib" --link $(cat "$work/elf-files")
# PyQt6's Qt already looks in Qt6/lib: give its plugins what the host may lack there.
qt=$site/PyQt6/Qt6
# shellcheck disable=SC2046
python3 "$HERE/bundle_libs.py" "$excludelist" "$qt/lib" \
    $(find "$qt/lib" "$qt/plugins" "$site/PyQt6" -maxdepth 3 -type f -name '*.so*')

echo "==> AppImage"
output=$outdir/tvhplayer-$version-x86_64.AppImage
ARCH=x86_64 VERSION=$version APPIMAGE_EXTRACT_AND_RUN=1 \
    "$downloads/appimagetool-$APPIMAGETOOL_VERSION.AppImage" --no-appstream "$APPDIR" "$output"
echo "==> Built $output"

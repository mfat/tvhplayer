#!/bin/sh
# Build the built-in Tvheadend for the deb, rpm and AppImage packages.
#
#   build-tvheadend.sh fetch SOURCES            download the pinned archives (network)
#   build-tvheadend.sh build SOURCES WORK [--bundle-dvbcsa] [--relocatable]
#                                               verify, unpack, and compile (offline)
#   build-tvheadend.sh install WORK DESTDIR     install into a package root
#
# The result lands in /usr/libexec/tvhplayer/tvheadend, with its data in
# /usr/share/tvhplayer/tvheadend, away from a distro tvheadend package.
# --bundle-dvbcsa links libdvbcsa statically, for distros that do not ship it.
# --relocatable builds the web UI and data into the binary, which then runs
# from any folder: the AppImage mounts at a different path on every start.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/pins.env
. "$HERE/pins.env"

TVH_ARCHIVE="tvheadend-$TVHEADEND_COMMIT.tar.gz"
SCAN_ARCHIVE="dtv-scan-tables-$DTV_SCAN_TABLES_COMMIT.tar.gz"
DVBCSA_ARCHIVE="libdvbcsa-$LIBDVBCSA_VERSION.tar.gz"
HDHOMERUN_ARCHIVE="libhdhomerun_$LIBHDHOMERUN_VERSION.tgz"

die() {
    echo "build-tvheadend.sh: $*" >&2
    exit 1
}

verify() {
    file=$1
    sum=$2
    [ -f "$file" ] || die "missing $file (run: $0 fetch $(dirname "$file"))"
    echo "$sum  $file" | sha256sum -c --quiet - || die "checksum mismatch: $file"
}

fetch_one() {
    url=$1
    file=$2
    sum=$3
    if [ ! -f "$file" ]; then
        curl --fail --silent --show-error --location --retry 3 --retry-delay 2 -o "$file.part" "$url"
        mv "$file.part" "$file"
    fi
    verify "$file" "$sum"
}

cmd_fetch() {
    sources=$1
    mkdir -p "$sources"
    fetch_one "$TVHEADEND_REPO/archive/$TVHEADEND_COMMIT.tar.gz" \
        "$sources/$TVH_ARCHIVE" "$TVHEADEND_SHA256"
    fetch_one "https://github.com/tvheadend/dtv-scan-tables/archive/$DTV_SCAN_TABLES_COMMIT.tar.gz" \
        "$sources/$SCAN_ARCHIVE" "$DTV_SCAN_TABLES_SHA256"
    fetch_one "https://download.videolan.org/pub/videolan/libdvbcsa/$LIBDVBCSA_VERSION/$DVBCSA_ARCHIVE" \
        "$sources/$DVBCSA_ARCHIVE" "$LIBDVBCSA_SHA256"
    fetch_one "https://download.silicondust.com/hdhomerun/$HDHOMERUN_ARCHIVE" \
        "$sources/$HDHOMERUN_ARCHIVE" "$LIBHDHOMERUN_SHA256"
}

cmd_build() {
    sources=$(cd "$1" && pwd)
    work=$2
    bundle_dvbcsa=$3
    relocatable=$4
    verify "$sources/$TVH_ARCHIVE" "$TVHEADEND_SHA256"
    verify "$sources/$SCAN_ARCHIVE" "$DTV_SCAN_TABLES_SHA256"
    verify "$sources/$HDHOMERUN_ARCHIVE" "$LIBHDHOMERUN_SHA256"
    rm -rf "$work"
    mkdir -p "$work/tvheadend"
    work=$(cd "$work" && pwd)
    jobs=${JOBS:-$(nproc)}

    tar -xzf "$sources/$TVH_ARCHIVE" -C "$work/tvheadend" --strip-components=1
    # support/version reads rpm/version when there is no .git.
    echo "$TVHEADEND_VERSION" > "$work/tvheadend/rpm/version"
    mkdir -p "$work/tvheadend/data/dvb-scan"
    tar -xzf "$sources/$SCAN_ARCHIVE" -C "$work/tvheadend/data/dvb-scan" --strip-components=1
    # Without the stamp, the Makefile empties data/dvb-scan and tries to git clone it.
    touch "$work/tvheadend/data/dvb-scan/.stamp"

    if [ "$bundle_dvbcsa" = yes ]; then
        verify "$sources/$DVBCSA_ARCHIVE" "$LIBDVBCSA_SHA256"
        mkdir -p "$work/libdvbcsa"
        tar -xzf "$sources/$DVBCSA_ARCHIVE" -C "$work/libdvbcsa" --strip-components=1
        (
            cd "$work/libdvbcsa"
            # Its config.guess (2009) predates aarch64; use the system's.
            for f in config.guess config.sub; do
                for d in /usr/share/misc /usr/lib/rpm/redhat; do
                    [ -f "$d/$f" ] && { cp "$d/$f" "$f"; break; }
                done
            done
            ./configure --prefix="$work/dvbcsa" --disable-shared --enable-static --with-pic
            make -j"$jobs"
            make install
        )
        CFLAGS="${CFLAGS:-} -I$work/dvbcsa/include"
        LDFLAGS="${LDFLAGS:-} -L$work/dvbcsa/lib"
        export CFLAGS LDFLAGS
    fi

    # HDHomeRun tuners: Tvheadend links the static library built here.
    mkdir -p "$work/libhdhomerun-src"
    tar -xzf "$sources/$HDHOMERUN_ARCHIVE" -C "$work/libhdhomerun-src" --strip-components=1
    "$HERE/build-libhdhomerun.sh" "$work/libhdhomerun-src" "$work/hdhomerun"
    CFLAGS="${CFLAGS:-} -I$work/hdhomerun/include"
    LDFLAGS="${LDFLAGS:-} -L$work/hdhomerun/lib"
    export CFLAGS LDFLAGS

    cd "$work/tvheadend"
    # configure defaults to "python", which Debian and Fedora do not provide.
    PYTHON=${PYTHON:-python3}
    export PYTHON
    bundle_flag=--disable-bundle
    [ "$relocatable" = yes ] && bundle_flag=--enable-bundle
    # shellcheck disable=SC2086 # the flags are a word list
    ./configure \
        --prefix=/usr \
        --bindir=/usr/libexec/tvhplayer \
        --datadir=/usr/share/tvhplayer \
        "$bundle_flag" \
        $TVHEADEND_CONFIGURE_FLAGS
    # configure quietly leaves a feature out when its library is missing.
    grep -q '^CONFIG_HDHOMERUN_CLIENT = yes' .config.mk || die "Tvheadend was configured without HDHomeRun"
    # Distro build flags define _FORTIFY_SOURCE too; Tvheadend's own copy would fail under -Werror.
    make -j"$jobs" CFLAGS_NO_WERROR=yes
}

cmd_install() {
    work=$1
    destdir=$(mkdir -p "$2" && cd "$2" && pwd)
    make -C "$work/tvheadend" install DESTDIR="$destdir" CFLAGS_NO_WERROR=yes
    # Only the server is needed. Man pages land under datadir; the metadata helpers
    # want extra Python modules.
    rm -rf "$destdir/usr/share/tvhplayer/man"
    rm -f "$destdir/usr/libexec/tvhplayer/tvhmeta" \
        "$destdir/usr/libexec/tvhplayer/tv_meta_tmdb.py" \
        "$destdir/usr/libexec/tvhplayer/tv_meta_tvdb.py"
}

[ $# -ge 1 ] || die "usage: $0 fetch SOURCES | build SOURCES WORK [--bundle-dvbcsa] [--relocatable] | install WORK DESTDIR"
command=$1
shift
case "$command" in
    fetch)
        [ $# -eq 1 ] || die "usage: $0 fetch SOURCES"
        cmd_fetch "$1"
        ;;
    build)
        [ $# -ge 2 ] || die "usage: $0 build SOURCES WORK [--bundle-dvbcsa] [--relocatable]"
        sources=$1
        work=$2
        shift 2
        bundle=no
        relocatable=no
        for option in "$@"; do
            case "$option" in
                --bundle-dvbcsa) bundle=yes ;;
                --relocatable) relocatable=yes ;;
                *) die "unknown build option: $option" ;;
            esac
        done
        cmd_build "$sources" "$work" "$bundle" "$relocatable"
        ;;
    install)
        [ $# -eq 2 ] || die "usage: $0 install WORK DESTDIR"
        cmd_install "$1" "$2"
        ;;
    *)
        die "unknown command: $command"
        ;;
esac

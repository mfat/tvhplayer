#!/bin/sh
# Build libhdhomerun as a static library for the built-in Tvheadend.
#
#   build-libhdhomerun.sh SOURCE PREFIX
#
# SOURCE is the unpacked libhdhomerun archive. The library lands in
# PREFIX/lib/libhdhomerun.a and its headers in PREFIX/include/libhdhomerun,
# where Tvheadend's configure looks for <libhdhomerun/hdhomerun.h>.
# Tvheadend's own --enable-hdhomerun_static would download the archive
# during the build; the deb, rpm, and Flatpak builds are offline.
set -eu

[ $# -eq 2 ] || { echo "usage: $0 SOURCE PREFIX" >&2; exit 1; }
source=$(cd "$1" && pwd)
prefix=$2
CC=${CC:-cc}
AR=${AR:-ar}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# The library's Makefile names its sources; on Linux the interface code is netlink.
case "$(uname -s)" in
    Linux) if_detect=netlink ;;
    *) if_detect=getifaddrs ;;
esac
sources=$(sed -n 's/^LIBSRCS += //p' "$source/Makefile" | sed "s/\$(IF_DETECT)/$if_detect/")
[ -n "$sources" ] || { echo "$0: no LIBSRCS in $source/Makefile" >&2; exit 1; }

for file in $sources; do
    # shellcheck disable=SC2086 # CFLAGS is a word list
    "$CC" ${CFLAGS:-} -O2 -fPIC -c "$source/$file" -o "$work/${file%.c}.o"
done
mkdir -p "$prefix/lib" "$prefix/include/libhdhomerun"
rm -f "$prefix/lib/libhdhomerun.a"
"$AR" rcs "$prefix/lib/libhdhomerun.a" "$work"/*.o
cp "$source"/*.h "$prefix/include/libhdhomerun/"

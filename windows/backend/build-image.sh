#!/bin/sh
# Requires Docker on the build host only. The Python builder also supports WSLc.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${PYTHON:-python3}" "$HERE/build-bundle.py" --engine "${ENGINE:-docker}" --output "${1:-$HERE/dist}"

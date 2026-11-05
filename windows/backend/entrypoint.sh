#!/bin/sh
set -eu
# Credentials must be provisioned by Windows before starting. Never use --noacl.
test -s /config/superuser || { echo 'Missing TVHplayer superuser credentials' >&2; exit 1; }
exec /usr/libexec/tvhplayer/tvheadend -c /config -B --bindaddr 0.0.0.0 \
    --http_port 9981 --htsp_port 9982

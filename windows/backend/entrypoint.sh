#!/bin/sh
set -eu
# Credentials must be provisioned by Windows before starting. Never use --noacl.
# The app mounts its settings volume at /config and keeps live settings in data/.
test -s /config/data/superuser || { echo 'Missing TVHplayer superuser credentials' >&2; exit 1; }
exec /usr/libexec/tvhplayer/tvheadend -c /config/data -B --bindaddr 0.0.0.0 \
    --http_port 9981 --htsp_port 9982

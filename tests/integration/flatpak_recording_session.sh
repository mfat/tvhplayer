#!/bin/bash
set -euo pipefail
root=$1
app=$2
mkdir "$root/host-first" "$root/host-second" "$root/host-recovered"
gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop --method org.freedesktop.DBus.Properties.Get org.freedesktop.portal.FileChooser version > "$root/portal-version.log"

run_phase() {
    local phase=$1 marker=$2
    shift 2
    if ! timeout 100 flatpak run --command=python3 --env=QT_STYLE_OVERRIDE=Fusion --env=XDG_CURRENT_DESKTOP=KDE "$app" /app/src/flatpak_recording_folder.py "$phase" --marker "$marker" "$@" > "$root/$marker.log" 2>&1; then
        cat "$root/$marker.log"
        return 1
    fi
    sed -n '/^RESULT /p' "$root/$marker.log"
}

choose() {
    local folder=$1 marker=$2
    shift 2
    run_phase choose "$marker" "$@" &
    local phase_pid=$!
    local chooser=''
    for _ in $(seq 1 60); do
        chooser=$(xdotool search --onlyvisible --name '^Recordings Folder$' 2>/dev/null | tail -1 || true)
        if [ -n "$chooser" ]; then break; fi
        if ! kill -0 "$phase_pid" 2>/dev/null; then
            wait "$phase_pid"
            return 1
        fi
        sleep .5
    done
    test -n "$chooser"
    xdotool windowfocus --sync "$chooser"
    xdotool key --clearmodifiers ctrl+l
    xdotool type --clearmodifiers --delay 1 "$folder"
    xdotool key Return
    sleep 1
    if kill -0 "$phase_pid" 2>/dev/null; then xdotool key alt+s; fi
    wait "$phase_pid"
    test -f "$folder/$marker"
}

choose "$root/host-first" first.txt
run_phase check restart-first.txt
test -f "$root/host-first/restart-first.txt"
choose "$root/host-second" second.txt
run_phase check restart-second.txt
test -f "$root/host-second/restart-second.txt"
test ! -f "$root/host-first/second.txt"
mv "$root/host-second" "$root/host-moved"
run_phase stale renamed.txt
choose "$root/host-recovered" recovered.txt
run_phase check restart-recovered.txt
test -f "$root/host-recovered/restart-recovered.txt"
chmod 555 "$root/host-recovered"
run_phase stale read-only.txt
chmod 755 "$root/host-recovered"
run_phase check permissions-restored.txt
flatpak document-unexport "$root/host-recovered"
run_phase stale grant-revoked.txt
choose "$root/host-recovered" regranted.txt --allow-same-folder
run_phase check restart-regranted.txt
test -f "$root/host-recovered/restart-regranted.txt"
flatpak documents > "$root/documents.log"
echo 'All portal recording-folder checks passed.'

# Flatpak recording-folder integration check

`flatpak_recording_folder.py` exercises the real TVHplayer Settings Browse button,
Qt's native directory chooser, the shared write probe, configuration reloads,
and writing from a separate child process. It does not mock the chooser or grant
filesystem access. Use a dedicated test application ID to preserve normal app
settings.

For a test Flatpak build, copy the checkout's `tvhplayer/` and `icons/` directories
to `/app/src/`, and copy the helper to `/app/src/flatpak_recording_folder.py`.
Set `PYTHONPATH=/app/src`. The runtime must provide the app's normal dependencies
and Qt's desktop portal platform theme. Keep the production manifest's filesystem
permissions unchanged (no home/host filesystem grant).

With that app installed and a working desktop portal:

The automated host-side driver requires `Xvfb`, `xdotool`, `dbus-run-session`,
and `gdbus`. It creates an isolated desktop session and uses keyboard input on
the real portal chooser:

```sh
bash tests/integration/run_flatpak_recording_folder.sh io.github.mfat.tvhplayer.RecordingTest
```

It checks folder changes, fresh-process persistence, child-process writes,
rename-induced stale paths, read-only directories, revoked grants, and recovery
by selecting the same folder again. Logs and generated files are retained in the
printed artifact directory. It requires the standard `/run/user/$UID` runtime
directory: a custom host runtime path can yield portal URLs that the sandbox
cannot resolve.

For interactive testing instead:

```sh
app=io.github.mfat.tvhplayer.RecordingTest
flatpak run --command=python3 "$app" /app/src/flatpak_recording_folder.py choose --marker first.txt
flatpak run --command=python3 "$app" /app/src/flatpak_recording_folder.py check --marker restarted.txt
```

Choose a host folder outside the sandbox in the first command. Both commands
must report `RESULT` with `ok: true`, and both files must appear in the host
folder. Each invocation creates a new QApplication and loads the saved config.

Run `choose` again, select a different host folder through Settings, then run
`check` again. Verify that the new files appear only in the new folder. Inspect
`flatpak documents` to confirm that Qt received a document-portal path rather
than accessing a folder through a broad filesystem permission.

Then rename or remove the selected host folder, revoke its document grant, or
remove write permission. Run `stale`; it must report the concrete filesystem
error and `ok: true`, and assert that Settings displays the error. Run `choose`
to select a replacement, then `check` to verify recovery after another restart.
Renaming may remain accessible on some portal implementations; in that case
record the result and use removal or grant revocation for the stale-path check.

This checks real portal access and process restarts. It does not by itself test
an OS reboot, a different desktop portal backend, a production runtime build, or
actual broadcast capture. Server API failures and requested/applied folder state
are covered by the unit tests.

# Recording-folder validation, 2026-11-06

The real portal scenario passed all 12 phases in Ubuntu 26.04 under WSL2.
The test used Flatpak 1.16.6, Qt/PyQt 6.10.2, xdg-desktop-portal 1.21.1,
and the GTK portal backend 1.15.3. Xvfb and a separate session bus isolated the
desktop automation. This was a purpose-built test runtime containing the current
TVHplayer source, not the release KDE 6.11 runtime. The test app had no home/host
filesystem permission.

The checked-in `run_flatpak_recording_folder.sh` driver exercised the actual
Settings Browse button and Qt's native portal chooser. All successful phases
also verified a child-process write and the saved configuration loaded from disk.

| Phase | Result |
| --- | --- |
| Select first host folder through Settings | Passed |
| Restart and write into first folder | Passed |
| Change to second host folder through Settings | Passed |
| Restart and write into second folder | Passed |
| Rename second host folder | Saved document path became stale; ENOENT detected and shown in Settings |
| Select replacement through Settings | Passed |
| Restart and write into replacement | Passed |
| Make replacement read-only with chmod 555 | EACCES detected and shown in Settings |
| Restore permissions and restart | Write succeeded |
| Revoke replacement's document grant | Saved path became stale; ENOENT detected and shown in Settings |
| Select the same host folder again | Grant restored; new document ID received |
| Restart after restoring grant | Write succeeded |

The successful run retained its host files, portal version, document list and
per-phase logs at:
`/home/mehdi/.cache/tvhplayer-recording-check.UOXIHk` in WSL.

Related regression checks passed: 65 tests on Linux; 68 passed and 2 skipped in
the focused Windows run. After the final Settings warning-refresh adjustment,
all 10 targeted UI checks and the complete 12-phase portal scenario passed again.

The stale paths were `/run/user/1000/doc/<document-id>/<folder>`. Their being saved
correctly did not make them immune to host-directory renames or grant revocation.
Reselecting the host folder repaired access; no broad filesystem grant was used.

During harness setup, a custom host `XDG_RUNTIME_DIR` also produced portal paths
outside the sandbox's visible runtime mount. The application's write probe
rejected those paths and displayed ENOENT. The successful run used the standard
`/run/user/1000` directory. This setup issue does not establish the cause of the
previously reported document-portal malfunction.

Application process restarts were tested; an OS reboot and broadcast capture
were not. TVHeadend API rejection/retry and requested-versus-applied state were
tested separately with unit tests.

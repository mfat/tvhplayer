# Windows backend acceptance record

Validated locally on Windows x86-64 with WSLc 3.0.3. The app remains native;
the test backend is built from TVHeadend commit
`40e88d4cef2c81e44474e75fd2f1edb232575ceb`.

## Automated real-host checks

`python windows/backend/integration-test.py` uses a private config and a generated
IPTV test channel. It passed:

- Windows socket-table verification that both published listeners bind only to
  IPv4 loopback; no wildcard/IPv6/LAN listeners.
- Rejection of unauthenticated administrative HTTP requests and incorrect HTSP
  credentials.
- Playlist import and service scan using the Linux FFmpeg in the image.
- Authenticated HTTP MPEG-TS streaming and authenticated HTSP media packets.
- DVR recording into a Windows folder with spaces and non-ASCII characters;
  the resulting recording was readable with FFprobe.
- Container restart preserving credentials, imported channels and recorded media.

`python windows/backend/lifecycle-test.py` passed actual port-collision retry,
duplicate-window exclusion, and cleanup/replacement of an orphan created by
deliberately terminating a private test UI. Tests preserve unrelated WSL workloads.

`python windows/backend/smoke-test.py` checks basic startup and shutdown. An
offscreen full-app launch reached successful mpv initialization and channel fetch.
Windows-side HDHomeRun discovery found the local device and the container's
directed discovery found both DVB-T frontends. RF scanning/tuning was not performed
because that device was already used by the user's remote server.

The final pinned image also passed the media and lifecycle tests:
`sha256:fda0e3415254a8ecabc539042e33d87c438ad3ba48a48836df4a17deaa53bf81`.
Its 613,997,056-byte runtime archive and 1,007,041,279-byte corresponding-source
archive passed SHA256 verification. The complete bundle includes 291 Debian
package records plus TVHeadend, libhdhomerun and scan-table records in its SPDX
inventory. It was promoted into the development app's backend directory.

Cache-miss import was tested by removing only this session's newly built image
while no containers existed, then running the normal provisioning path. It
loaded the verified local archive successfully without a registry pull. Windows
internet connectivity was left enabled; a physically disconnected clean host
remains a separate qualification check.

## Frozen portable build

Built locally with Python 3.15, PyInstaller 6.22.3 and the release-pinned Qt 6.11.
The final 462,847,737-byte portable ZIP passed a full archive integrity test. It
was extracted to a separate directory with spaces in its path and launched with
an isolated user profile. Without the development flag, the app initialized mpv,
autostarted the bundled backend, authenticated and reached channel fetching.
The smoke test then removed only its own backend container.

Local artifact: `windows/dist-wslc/tvhplayer-wslc-test-windows-x86_64-current.zip`.
Its corresponding source is the adjacent `tvhplayer-wslc-test-backend-source.tar.gz`.
The local build used the portable-only option because Inno Setup is not installed
on this machine. Installer packaging remains covered by the Windows CI workflow
and still needs an actual installer/upgrade qualification run.

## Unit/UI checks

The focused backend, playlist, packaging and logging run passed 124 tests with
five platform/integration skips. Setup-consent and cancellation UI tests also
passed. Cancelling startup disconnects queued actions so they cannot run on a
later server start, and the channel view exits its starting state.

Contract tests cover bundle hashes/source pins, path validation, ownership refusal,
port mappings, cancellation, image-upgrade config backups, stale metadata recovery,
guest FFmpeg migration, and host HDHomeRun discovery. The setup UI test verifies
that constructing/opening the dialog makes no installation call, and that only
clicking Install invokes the fixed elevation command and persists resume state.

The broader UI run found three failures with local Python 3.15 / Qt 6.12:
`test_tasks_panel_lists_filters_and_controls_jobs`,
`test_channel_list_columns_can_be_resized`, and
`test_player_bar_casts_the_selected_channel_and_routes_audio`.
All three reproduced on a separate archive of the unchanged HEAD revision with
the same environment. They are not counted as passing checks or attributed to
this backend change.

## External release qualification still required

The following cannot be established on an already-provisioned single host:

- Fresh-machine WSL installation, administrator refusal, policy restrictions,
  virtualization disabled, and reboot recovery using real Windows setup.
- Installer and upgrade smoke tests on the release Python/Qt toolchain.
- Reachability testing from a second physical LAN machine; host binding checks
  above passed but are not a substitute for a second-host test.
- Sleep/resume, drive removal, disk-full behavior, multiple Windows accounts,
  long sustained recordings, and RF tuner streaming under load.
- Actual offline first import on a clean host with its internet disconnected.

The workflow-dispatch `run_wslc_acceptance` option runs media/lifecycle tests on
a managed runner labelled `self-hosted, Windows, X64, wslc`. No such runner is
registered or changed by this code. These checks do not require Docker or an
Ubuntu distribution on that Windows host.

Private WSL rootfs and QEMU runtimes are alternatives/future fallbacks in the
proposal, not implementations supplied by this WSLc delivery. No USB passthrough,
headless DVR service, or ARM64 image is included.

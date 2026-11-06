# Windows backend acceptance record

## First-run review follow-up (2026-11-07)

This section describes new checks, not a claim that every fresh-machine scenario
has passed. The historical results below apply to their recorded source/host.

Local follow-up evidence:

- A new PyInstaller portable executable and ZIP were built from the changed tree
  with Python 3.15.0 and the pinned Windows build dependencies.
- The actual ZIP passed archive verification, missing/corrupt-file rejection,
  bundled-mpv startup, and an authenticated remote-server connection using an
  isolated profile. No local container was created during that remote test.
- The packaged real-backend attempt failed at `wslc info` with `E_ACCESSDENIED`.
  A source-adapter check and a direct Python subprocess reproduced the same
  denial, even without the no-console flag. A standalone shell `wslc info`
  succeeded; this does not establish that subprocess startup is allowed.
  Backend readiness, crash recovery and reboot acceptance are therefore not
  recorded as passing for this run. No global WSL settings were changed.
- GitHub reports zero registered self-hosted runners. A disposable WSL runner
  must be provisioned before the opt-in package/backend job can run.

`TVHPLAYER_PROFILE_DIR` isolates application configuration/cache/logs without
redirecting the OS profile used by WSL. Older released installers are exercised
with redirected app folders only in the remote-server upgrade test; they are not
used for an isolated backend-upgrade claim.

`windows/test-packages.py --portable ZIP --installer SETUP_EXE
--previous-installer PREVIOUS_SETUP_EXE` runs the actual distributed executables,
not a source-imported main window. Run installer tests only on a disposable VM or
dedicated disposable Windows account: the real installer writes current-user
installation registration. App profiles and downloads are isolated, but that is
not a substitute for OS-level isolation.

The default Windows build invokes this test before uploading packages. It checks:

- Real archive verification, plus deliberate missing/corrupt-archive rejection in
  a private extracted copy (the verifier runs from the checkout).
- Real ZIP and installed-EXE startup, bundled mpv initialization, and an authenticated
  connection to a local remote-server fixture.
- Remote-server operation with local setup disabled, without creating a container.
- Replacement of the previous released installer while keeping the profile.

The opt-in `run_wslc_acceptance` dispatch also downloads the newly built packages
and runs `windows/test-packages.py --exercise-backend` on a runner labelled
`self-hosted, Windows, X64, wslc, disposable`. This launches the packaged server,
checks authenticated readiness and channel-setup entry, deliberately terminates
the test app, and verifies orphan recovery and stable credentials. The regular
build cannot establish this result when the managed runner is unavailable.

| Scenario | Automated coverage | Remaining qualification |
| --- | --- | --- |
| No WSL | Source tests cover detection and explicit elevation commands | Fresh VM: install WSL, accept/refuse UAC, restart Windows and resume |
| Virtualization off | Source tests cover confirmed/unknown results, disabling, and explicit recheck | VM/physical machine: actual firmware-off result and enable/restart |
| Old WSL | Source tests cover update choice and recheck | VM with an older installed runtime |
| Missing/corrupt image | Source tests plus actual ZIP archive checks | Clean VM: first import with network disconnected |
| Installer upgrade | Actual previous/current installer remote-profile test | Opt-in packaged backend run; VM snapshot for release-to-release data preservation |
| Provisioning cancelled | Source lifecycle cancellation tests; packaged crash/orphan recovery | Clean VM: cancel while a genuinely uncached image imports |
| No tuner/playlist | Source wizard tests and opt-in packaged empty-server setup | Fresh package UI walkthrough |
| Wizard abandoned | Source UI tests: cancellation, explicit dismissal, retry next session | Fresh package UI walkthrough |
| Existing remote server | Actual ZIP/installer remote connection and source import tests | External physical-server playback/recording |

Shared Linux/Windows readiness now requires authenticated HTTP, reachable HTSP,
and essential defaults. Optional preference failures are logged and exposed as
degraded operation. See [the behavioral contract](../../docs/builtin-first-run.md).

Known local baseline: three unrelated broad UI tests (tasks-panel recording
indicator, column resizing, Chromecast test without a selected server) also fail
on an untouched HEAD snapshot. They are not counted as passing validation.

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
directed discovery found both DVB-T frontends.

## HDHomeRun MPEG-TS transport

Root cause: Tvheadend's HDHomeRun input thread
(`tvhdhomerun_frontend_input_thread`, lines 86–150 of
`src/input/mpegts/tvhdhomerun/tvhdhomerun_frontend.c` at commit
`40e88d4cef2c81e44474e75fd2f1edb232575ceb`) binds UDP on `INADDR_ANY` and tells
the device `udp://<local_ip>:<port>`. With an empty `local_ip` it uses the
container address (for example `172.17.0.3`), which the LAN tuner cannot reach.
Control-plane discovery on UDP 65001 still worked; the media plane did not.

Fix chosen (Option B — explicit UDP publish): advertise a Windows LAN address and
deterministic per-tuner ports via Tvheadend `local_ip`/`local_port`, and publish
the same UDP range with WSLc `--publish LAN:port:port/udp`. Option A (host /
direct networking) was rejected because WSLc 3.0.3 does not provide a supported
host-network mode for this app model. Option C (Windows UDP relay) was rejected
as unnecessary once publish+`local_ip` was verified.

Contract coverage: `tests/test_hdhomerun.py`, `tests/test_windows_wslc.py`,
`tests/test_wslc_lifecycle.py`, and `tests/test_builtin_server.py` cover discovery
metadata, port planning, LAN-only UDP publication, readiness checks, supervisor
lifecycle, and config save/read-back.

Hardware acceptance on this development host (WSLc 3.0.3, HDHomeRun
`192.168.8.148` via `192.168.8.211`):

- Built-in server published MPEG-TS UDP on the LAN address and configured
  Tvheadend `local_ip`/`local_port`.
- HDHomeRun `/tuner0/target` became `udp://192.168.8.211:<published-port>`
  (not a container `172.17.x.x` address).
- RF lock on DVB-T2 at 674 MHz; scan discovered service(s) and mapped channel
  `IRIB UHD HDR`; authenticated HTTP MPEG-TS play returned sync-byte `0x47`
  packets.
- The scan-table 400 was a client naming issue, plus asynchronous table loading:
  the pinned server expects `type=dvb-t`, not `dvbt`. Windows built-in setup now
  uses that canonical type, retries that specific startup-loading error for at
  most two seconds, and preserves the returned scanfile keys exactly. A live
  check returned 1,171 DVB-T tables; `dvb-t/auto/dvb-t_auto-Defaul` created 57 muxes.
  The normal setup UI no longer needs a synthetic table or a backend patch.
  Native Linux, macOS and remote-server requests retain their existing path.
- After stopping competing acceptance-test processes, an isolated selected-device
  run scanned 602 MHz and 674 MHz, found 12 services, mapped 12 channels and
  played IRIB TV1. It then held both frequencies locked and read 1,372,400 bytes
  of valid MPEG-TS from **each** channel simultaneously over six seconds.
  The owned container was removed and both Windows UDP publications were released.

### Review follow-up and reproduction (2026-11-06)

The combined automated suite passed **168 tests, 4 skipped**. It includes startup
selection, existing-tuner route checks, multi-device selection, live-volume
settings preservation, canonical scan-table requests, UDP bindings, authentication,
bundle integrity, and lifecycle contracts. Hardware evidence is separate below.

Startup no longer performs unconditional two-second broadcast discovery. It
reads the selected device from the live owned Linux volume, determines the
Windows route to that specific IP and makes a short unicast probe. It never
chooses the first of several devices. With no selection it reserves up to eight
UDP ports on the default LAN interface for later setup. Missing/offline devices
do not prevent IPTV startup.

The new address/port settings are written atomically before TVHeadend starts,
preserving unrelated settings, so persisted initial scans do not advertise old
UDP ports. API read-back and strict publication checks gate readiness. Existing
HDHomeRun frontend entries get the same route validation as new discoveries;
NIC/DHCP changes produce a restart diagnostic rather than silent zero-service scans.

The IPTV integration test passed authenticated HTTP MPEG-TS, HTSP media,
Windows-folder recording/FFprobe, and preservation of credentials, channels and
recordings across restart. Socket-table checks confirmed loopback-only HTTP/HTSP
and rejection of unauthenticated/wrong credentials. The lifecycle test passed
real port-collision retry, duplicate-window rejection and killed-UI orphan recovery
with UDP publication enabled.

Reproduce a focused RF test, using a free tuner and locally valid frequencies:

```powershell
python windows/backend/hdhomerun-test.py --bundle 'C:\Program Files\TVHplayer\backend' --device 192.168.8.148 --frequency 602000000 --frequency 674000000 --timeout 90
```

The script refuses to take a tuner already locked by another recorder/test. It
holds channels from different RF muxes open together, reads both streams for six
seconds, checks simultaneous RF locks/targets, then verifies container removal
and that the UDP range can be rebound. The default full-band test looks up the
generic table's exact key from the server.

Run real WSLc acceptance scripts sequentially: parallel container creation during
validation produced transient `E_UNEXPECTED` errors on this runtime, while the
same tests passed sequentially. Concurrent media **within one server** passed.
These short tests do not qualify sustained recording load or every WSLc version.

Source references, verified against the pinned commit:

- [HDHomeRun receiver, target address/port, tuning and lock handling](https://github.com/mfat/tvheadend/blob/40e88d4cef2c81e44474e75fd2f1edb232575ceb/src/input/mpegts/tvhdhomerun/tvhdhomerun_frontend.c)
- [Configuration properties `hdhomerun_ip`, `local_ip`, `local_port`](https://github.com/mfat/tvheadend/blob/40e88d4cef2c81e44474e75fd2f1edb232575ceb/src/config.c)
- [Scan-table API and server-provided keys](https://github.com/mfat/tvheadend/blob/40e88d4cef2c81e44474e75fd2f1edb232575ceb/src/api/api_mpegts.c)
- [Microsoft WSL container documentation](https://learn.microsoft.com/en-us/windows/wsl/wsl-container)
- [SiliconDust UDP target/control interface](https://info.hdhomerun.com/info/hdhomerun_config)

`local_ip` and `local_port` are JSON configuration/API properties in this pin,
not supported command-line flags. No upstream TVHeadend modification, global WSL
setting, firewall change, host-network mode, third-party relay or fixed container
address was needed. The Microsoft overview alone does not prove UDP semantics:
the actual published ports, tuner targets, services and received MPEG-TS provide
end-to-end evidence on WSLc 3.0.3.0. Older supported runtimes and multi-device
installations need separate hardware qualification; the directed backend selects
one device with multiple concurrent tuners.

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
  and long sustained recordings under load.
- Actual offline first import on a clean host with its internet disconnected.

The workflow-dispatch `run_wslc_acceptance` option runs media/lifecycle tests on
a disposable runner labelled `self-hosted, Windows, X64, wslc, disposable`. No such runner is
registered or changed by this code. These checks do not require Docker or an
Ubuntu distribution on that Windows host.

Private WSL rootfs and QEMU runtimes are alternatives/future fallbacks in the
proposal, not implementations supplied by this WSLc delivery. No USB passthrough,
headless DVR service, or ARM64 image is included.

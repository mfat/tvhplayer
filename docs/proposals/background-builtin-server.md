# Proposal: Keep the built-in server running in the background

- **Status:** Proposed; not implemented.
- **Date:** 2026-11-06
- **Baseline:** v4.6.1, including the Windows startup and settings-storage changes.
- **Decision:** Add an optional desktop background mode for Windows and Linux,
  including Flatpak. Consider a native Linux systemd integration separately.
- **macOS:** A built-in server is not currently shipped. Its implementation does
  not block background mode on supported platforms.

## Purpose

Let the built-in server continue serving and recording when the player window
closes. Reopening TVHplayer should show the existing server immediately instead
of starting another server or interrupting recordings.

The first version operates within the signed-in user's desktop session. It does
not promise operation before login, after logout, during suspend, or while the
computer is off. Unattended operation across login sessions is a separate service
feature.

This proposal changes the relationship between the window and the app-owned
server. It does not change ownership of user-added local or remote servers, add
network exposure, or implement a macOS backend.

## Current implementation

The main window currently owns most application work. Its `closeEvent` saves
configuration, calls `builtin.shut_down()`, cancels jobs, releases sleep
inhibition, and closes playback and client connections. Closing the window
therefore shuts down the built-in server.

- [Main window and application entry point](../../tvhplayer/tvhplayer.py)
- [Linux built-in supervisor](../../tvhplayer/builtin_supervisor.py)
- [Windows built-in supervisor](../../tvhplayer/wslc_builtin_supervisor.py)
- [Windows runtime adapter](../../tvhplayer/core/windows_wslc.py)
- [Windows settings storage](../../tvhplayer/core/windows_backend_storage.py)
- [Flatpak manifest](../../io.github.mfat.tvhplayer.yml)
- [Existing portal integration for sleep inhibition](../../tvhplayer/sleep_inhibit.py)

Linux supervises an app-packaged foreground TVHeadend child with `QProcess`.
Windows supervises an owned WSLc container. Both have cleanup or recovery rules
for servers left behind by a previous app instance. Detaching the process or
container alone would conflict with these rules and lose its lifecycle owner.

The Windows server now stores live settings in a persistent Linux volume and
exports backups on clean stop. The original Windows settings are preserved.
Archive hashing, repeated ACL updates, and completed playlist migration have
already been removed from the normal repeat-start path. Local tests of the
patched v4.6.1 code measured approximately 1.8–1.9 seconds on repeat starts;
other starts took about 9 seconds. These are measurements on one machine, not a
startup-time guarantee. See [Windows server storage](../windows-server-storage.md).

Background mode complements these improvements: it avoids restarting a healthy
server when the user only wants to close and reopen the window.

## Product behavior

Keep the existing **Start with TVHplayer** option. Add these separate options in
the built-in server settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| Start with TVHplayer | Existing preference | Start the server when the app starts normally. |
| Keep the server running when the window closes | Off | Closing the player window leaves the app supervising the running server. |
| Start the server in the background at login | Off | Request platform autostart without opening the player window. Requires background mode. |

Enabling login startup must explain and enable the required server/background
preferences together. Disabling background mode must also remove the app's login
startup registration, or clearly require that dependent option to be disabled.
Registration failure must not leave the checkbox claiming success.

Close and quit have distinct behavior:

| Action | Expected result |
| --- | --- |
| Close window, background mode off | Existing shutdown and recording-confirmation behavior. |
| Close window, background mode on and server active | Stop playback, save UI preferences, hide the window, keep the controller and required jobs alive. |
| Open TVHplayer again | Activate the resident instance and show its window. Do not restart the server. |
| Stop server | Stop the owned server, complete settings backup, retain the normal ability to start it again. |
| Quit TVHplayer | Explicitly exit the resident app, with recording safeguards and clean server shutdown. |
| Disable background mode while its window is open | Keep the window open; its next close performs normal shutdown. |
| Permission denied or background support unavailable | Explain why background mode cannot be enabled; retain normal visible operation. |

If no window, owned server, or required job remains, the resident app should exit
instead of leaving an idle process indefinitely. Closing a window must not be
reported as quitting when the app remains active.

## Platform choices

| Platform | Initial implementation | Session boundary |
| --- | --- | --- |
| Windows | Resident user app; optional tray controls and per-user login startup. Continue using WSLc supervision. | Signed-in user; no Windows Service in this phase. |
| Flatpak | Resident app inside its existing sandbox; request the Background portal and optional login startup. | Desktop session with permission; no host systemd installation. |
| Native Linux | Same resident controller and activation model; desktop login startup where supported. | Desktop session in the first version. |
| macOS | Leave server-specific background options unavailable until a built-in backend exists. | Define separately when backend packaging is ready. |

The absence of a macOS server is a capability difference, not a reason to delay
the Windows and Linux work. A future macOS supervisor should plug into the same
controller contract. Its binary packaging, signing, server inputs, dependency
bundling, startup/shutdown tests, and supported OS versions need separate work.
An unavailable GitHub macOS runner is also a release-infrastructure issue, not
evidence that a working macOS server backend exists.

## Recommended architecture

Introduce an application-owned `BackendController` independent of the main
window. It owns the supervisor, its lifecycle signals, server credentials and
endpoint, required recording monitoring, and failure/status reporting. The
window observes this controller and may be opened or hidden without destroying
it. Actual names and module boundaries can be settled during implementation.

Keep one resident application instance per user/configuration. For the first
version, the resident process owns both the controller and any visible window.
It must not hand off the server to a detached, unsupervised process.

Use explicit application states:

| State | Responsibilities |
| --- | --- |
| Visible | Window and controller active; normal playback and controls. |
| Background | No visible player window; controller and required jobs active. |
| Starting/stopping | Report progress; serialize competing lifecycle requests. |
| Failed | Preserve diagnostics and recovery controls; notify if hidden. |
| Quitting | Reject new starts; stop jobs/server and release resources once. |

Window visibility and server running/stopped/failed status are separate state
dimensions. A hidden window does not prove that the server is running, and a
server failure must not silently reopen or recreate the player repeatedly.

### Entry point and activation

Add a background launch mode such as `--background` that initializes the
application/controller without constructing the player window. It should not
load mpv, create video rendering surfaces, or require successful player
initialization just to run the server. A desktop-capable Qt application event
loop can remain active without a visible window; set its last-window-close
policy explicitly.

Use a per-user, per-configuration activation channel, for example
`QLocalServer`/`QLocalSocket`, plus a process-instance lock. A second invocation
sends a narrow **show window** request and exits. Do not accept arbitrary shell
commands, executable paths, or credentials over this channel. Restrict access
to the same user and recover stale endpoints only after proving their owner is
gone. Keep the existing backend configuration lock as a separate safety check.

The singleton must work across ordinary launch, login startup, a hidden window,
an in-progress server start, and crash recovery. Never infer ownership merely
from a process name, open port, or matching server response.

An obsolete autostart invocation with `--background` must exit safely when the
preference is disabled or the build has no built-in server capability. It must
not show an unexpected window or start an unwanted server.

### Window and job lifetime

Refactor the current `closeEvent` into a close-to-background path and a single
explicit shutdown path. Before backgrounding, save pending settings edits and
stop playback/rendering. Suspend display-only refresh work and release media
resources where practical. Keep only the work necessary for the enabled
background features.

Audit every task currently cancelled in `closeEvent`. Built-in DVR monitoring,
recording timers, active local recordings, and required playlist/guide work must
not disappear solely because their former owner was a widget. Move their
ownership to application/controller objects as needed. Existing active-job quit
confirmations must apply to **Quit**, not a harmless close-to-background action.

Do not require unloading and recreating every widget in the first change. The
essential contract is that controller/job lifetime is independent of window
visibility. Later memory optimizations must preserve that contract.

### User controls and notifications

Provide **Open TVHplayer**, server status, and **Quit TVHplayer** through the tray
where it is supported. Also support reopening from the normal application
launcher; a tray icon must not be the only recovery path. On Linux desktops
without a tray, use portal background status and notifications where available.

The window must show whether background mode and login startup were actually
granted. A hidden server failure, failed settings backup, or lost background
permission needs an actionable notification and retained diagnostics. Do not
expose credentials, stream tickets, or provider URLs in status text.

## Flatpak implementation

Flatpak is not a blocker. The
[Background portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Background.html)
supports background permission and an optional autostart request. Its response
reports those grants separately. Version 2 also provides `SetStatus` for a short
background status message.

Use an asynchronous portal request when the user enables the option, with a
reason such as keeping scheduled recordings running after the window closes.
Request login startup only for the corresponding explicit setting. Inspect the
response and interface version; do not assume that every desktop grants or
implements every capability. Handle denial, missing interfaces, and revocation.

Keep the controller and TVHeadend inside the same sandbox. Retain the current
recording-folder access and portal grants. This proposal does not require broad
home access, `flatpak-spawn --host`, or a host-installed service. Portal
interfaces are available through Flatpak's standard filtered session bus access;
follow existing QtDBus portal patterns in this repository. See the
[portal API reference](https://flatpak.github.io/xdg-desktop-portal/docs/api-reference).

Permission loss must initiate controlled shutdown and preserve completed
backups when the desktop allows it. Abrupt termination remains possible, so
ordinary crash-recovery safeguards are still required. Do not bypass a user's
denial by silently installing another autostart mechanism.

## Windows implementation

Keep using the user's WSLc runtime and persistent settings volume. The resident
controller retains the configuration lock and ownership records while the
window is hidden. Reopening the window must not trigger stale-container cleanup
against the healthy resident server.

Use an explicitly enabled per-user startup registration for login startup.
Choose the concrete Windows mechanism during implementation, and handle app
updates, moved portable installations, disabling the option, and uninstall.
Avoid administrator privileges and a system-wide Windows Service in this phase.

Closing the window is no longer a backup boundary when the server remains
running. Continue exporting settings on clean server stop and before image
upgrades. Add periodic settings backups for long-running background sessions
before considering this feature complete. Periodic backups must use a coherent
snapshot or a verified TVHeadend-safe procedure, retain the previous valid
backup, and serialize with upgrade, restore, and shutdown work. Do not copy a
changing settings tree and silently call it a consistent backup. Finalize the
snapshot method and bounded backup interval during implementation and document
the recovery window. Recordings remain outside these settings backups.

## Recordings, sleep, and exit

Continuing to run does not itself keep a computer awake or wake it for a future
recording. Keep the existing recording-related sleep handling active without a
window, and test its transitions. An idle background server must not hold an
indefinite sleep inhibitor merely because background mode is enabled.

Do not promise recording during suspend or automatic wake from suspend until a
separate platform-supported wake mechanism is implemented and tested.

Explicit quit retains recording safeguards. Once confirmed, shut down exactly
once, finish bounded server cleanup and backup work, and release locks,
activation endpoints, timers, and inhibitors. Handle OS logout/shutdown within
the time available; do not assume interactive confirmation is possible there.
Keep persistent ownership records valid if cleanup cannot finish so the next
start can recover safely. A GUI crash or permission loss must not lead the next
instance to adopt an unknown server.

## Why background mode before systemd

For desktop use, background mode covers Windows and Linux/Flatpak with one
lifecycle model. Its purpose is to preserve server operation when the window
closes, not to turn the desktop player into a machine-wide service.

For a dedicated Linux recorder that must operate before login or after logout,
a systemd-managed backend is a better fit. A user service with lingering can
run across those session boundaries; see
[loginctl enable-linger](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html).

That future integration needs separate host installation and service management,
headless operation, logging, update and permission policies, and authenticated
communication from the player. A GUI-capable `--background` process must not be
assumed to work in a non-graphical boot environment. A service-only entry point
would need to operate independently of the desktop and media player.

Do not automatically run `systemctl --user` or enable lingering from the Flatpak.
Initially, users already running a separate TVHeadend service can continue to
add it as an ordinary server connection. An optional managed service integration
for native Linux packages can follow once the shared controller boundary is
stable. Exactly one manager may own a given server/configuration at a time.

## Implementation sequence

1. **Separate lifecycle ownership.** Introduce the controller and application
   shutdown path without changing default close behavior. Keep both existing
   supervisors and their ownership/authentication checks.
2. **Single instance and background entry point.** Support activation of a
   resident instance and initialization without constructing the player.
3. **Windows and native Linux background mode.** Add opt-in settings, close/quit
   behavior, reopen controls, task ownership, and failure notifications.
4. **Flatpak portal integration.** Add grants, denial/revocation handling,
   status reporting, and desktop tests. Feature detection must gate availability.
5. **Optional login startup.** Register only after explicit opt-in, verify its
   result, and test disable/update/uninstall behavior on each supported platform.
6. **Long-running operation.** Complete periodic settings backups, bounded
   recovery, recording/sleep tests, and resource-use checks before release.
7. **Later independent work.** Add a macOS built-in backend; consider native
   Linux systemd service support. Neither blocks the initial platform rollout.

These are dependency steps, not a promise to ship partially tested background
mode. The capability remains off by default until its platform acceptance checks
pass. The v4.6.1 startup release does not implicitly include this proposal.

## Acceptance checks

Test lifecycle logic with fake supervisors and real platform runs. At minimum:

- Default close still performs the existing shutdown behavior.
- With the option enabled, closing and reopening preserves the server's
  process/container identity and active recording; it does not restart it.
- A second launch activates the resident window during startup, normal
  operation, and stopping, without creating another server or stealing a lock.
- Background-only launch avoids creating the player, loading mpv unnecessarily,
  or opening a window. Explicit normal activation creates a usable window.
- Stop, quit, OS logout, denied background permission, and app crashes each
  follow their defined cleanup/recovery path. No foreign process or volume is
  stopped, reused, or removed.
- Flatpak grants and denies background/autostart independently; test GNOME and
  KDE, including a desktop without usable tray support and missing portal APIs.
- Windows login startup uses the intended user/install path and is removed when
  disabled. Native Linux autostart works under the supported desktop session.
- Active and scheduled recording behavior, required refresh jobs, and sleep
  inhibition continue correctly without a visible window.
- Settings migration, restore, upgrade backup, periodic backup, and final backup
  cannot race. Interrupted exports retain the last known valid backup.
- Disabling background mode and explicit quit do not lose unsaved preferences
  or bypass existing recording confirmations.
- Long-running background operation has no growing log buffers, duplicate
  timers, orphan helpers, accumulating activation sockets, or abandoned locks.
- Existing remote-server behavior and loopback-only built-in exposure remain
  unchanged. IPC and status messages do not disclose secrets.
- Platforms without a packaged built-in server do not advertise unsupported
  server-specific options.

Capture repeat-launch latency, idle CPU/memory, and recording continuity before
and after implementation. Compare startup and resource usage on the same
machine rather than treating one local timing as a universal target.

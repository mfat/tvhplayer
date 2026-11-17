# Keep the built-in server running when the window closes

**Keep the server running when the window closes** is enabled by default.
You can turn it off under **Settings → Sleep**. The option appears only when
this build has a built-in server. Existing explicit choices are preserved. It does not start the server; **Start with TVHplayer** remains a separate
server preference.

With the option enabled and the server starting, running, or stopping, the close
button stops playback and hides the player and its child windows. TVHplayer
continues supervising the same server. Recording monitoring, local recording
jobs, playlist/guide jobs, conversions, and recording-related sleep inhibition
retain their existing owners and stay active. Display-only metadata/progress
timers pause until the window returns. This version retains the player widgets
and engine in memory; it does not provide a separate headless server process.

Where available, the tray offers **Open TVHplayer** and **Quit TVHplayer**.
Launching TVHplayer normally also reopens the resident window, including on
desktops without a tray. One desktop instance is allowed per user/configuration.
The activation endpoint accepts only a show request, uses same-user socket
access, and is removed only while holding the configuration's instance lock.
On Unix the instance lock uses a kernel file lock, which works across Flatpak
PID namespaces. Flatpak activation uses its shared per-app runtime directory,
not the sandbox's private `/tmp`.

**File → Quit TVHplayer**, **Ctrl+Q**, and the tray Quit action keep the existing
recording/job confirmations and clean server shutdown, including the Windows
settings export. Cancelling Quit restores the player. Closing with a stopped
server retains normal exit behavior. A server stop/failure while hidden restores
the window so recovery controls are available. Disabling background mode leaves
the next close using normal shutdown.

The ordinary Minimize button still minimizes to the taskbar. Background mode
uses `hide()`, not `showMinimized()`: all application windows must be unmapped for
the desktop to recognize windowless background activity.

## Flatpak permission

Enabling the option requests background permission through
`org.freedesktop.portal.Background.RequestBackground`, with `autostart=false`.
A saved preference is checked again before the first hide in a new app session.
The window stays visible while permission is pending; a successful grant
completes a pending close. Denial, cancellation, an unavailable portal, or a
request timeout disables the setting and leaves the window open with an
explanation. Explicit Quit remains available during the request.

The response's `background` field must be true; an autostart grant alone is not
enough. Portal version 2 status text is sent when hidden and cleared when shown;
version 1 desktops may reject this optional status method. Status text does not
set the desktop's window classification. The desktop owns that classification
and enforcement of permission changes, and may terminate a sandbox abruptly.

No host service, login startup registration, filesystem permission expansion,
or Flatpak override is installed. Operation is limited to the current desktop
session and does not promise recording through suspend or logout. Existing
Windows backups still occur on clean server stop, not each window hide; this
change does not add periodic live settings snapshots.

References: [Background portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Background.html),
[desktop app-state definitions](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.impl.portal.Background.html),
[Flatpak runtime directories](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

## Verification

Automated coverage includes show activation, separate profiles, crash recovery,
rejection of other activation commands, actual D-Bus request/response marshalling
for granted and denied background permission, close/reopen without server
shutdown, pending permission, explicit asynchronous quit, cancelled quit,
settings denial, and normal exit with a stopped server. D-Bus protocol tests use
an isolated fake desktop, not a simulated Python callback alone.

Cross-sandbox activation has also been exercised in the installed Flatpak
runtime, using `tests/integration/flatpak_background_activation.py` and a
disposable profile. Run its `owner PROFILE` and `activate PROFILE` modes in two
separate Flatpak invocations with the same profile path. The first must print
`READY` then `ACTIVATED`; the second must print `ACTIVATION SENT`. The helper
starts no player/server and changes no portal permission.

Before release, exercise a test Flatpak on both GNOME and KDE, with and without
tray support. Grant background permission, start a recording, close the window,
and verify the desktop reports the app as background/windowless and the server
process and recording remain unchanged. Reopen from the launcher and tray; deny
and revoke permission; verify explicit Quit and logout recovery. Test Windows
tray operation and clean-stop settings export separately. These real desktop
classification and platform lifecycle checks are not established by the isolated
D-Bus or activation tests.

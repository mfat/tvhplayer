# Built-in server startup and first-run behavior

The installer and portable ZIP run the same application. The installer does not
install WSL. On Windows the app detects the bundled backend from its manifest;
that means the backend is offered, not that the archive or host has been verified.
Remote-server use does not require WSL or local setup.

## Discovery, provisioning, and readiness

Windows first use reports separate stages: checking Windows support, protecting
settings, checking the image, verifying the archive when an import is necessary,
importing the image, preparing storage, checking tuner networking, starting the
server, testing its connection, applying settings, and updating playlist commands.
The progress indicator is indeterminate; it does not invent a download percentage.

The runtime records image states separately:

| State | Evidence |
| --- | --- |
| `not_checked` | No image check has completed in this startup attempt |
| `available` | A readable manifest names the required image; this is not archive verification |
| `verified` | The production bundle verifier has accepted the archive before import |
| `installed` | The required immutable image identity and architecture are present in WSLc |

`archive_verified` remains false when an already imported image is reused. Missing
or damaged archives therefore do not break a usable imported image. When import
is necessary, a missing or damaged archive fails before it reaches the runtime.

Both native Linux and Windows require the same initial readiness contract:

- The app-owned server is alive and its expected endpoints are configured.
- The HTTP API answers using the generated administrator credentials.
- An HTSP TCP connection succeeds. Linux startup messages alone are insufficient.
- Required defaults apply, including playback authentication. Windows additionally
  verifies owned-container identity and loopback port publication; selected
  HDHomeRun routing and guest-FFmpeg migration must succeed.

Failures to apply the recordings folder, recording margins, or disable the web
setup wizard are degraded preferences, not proof that playback is unavailable.
They are recorded in `startup_warnings`, logged, and shown as a warning in Server
Management. An unapplied recordings folder also produces the existing folder
warning. Other configuration failures stop startup. Ready does not mean these
optional preferences succeeded.

## Failure presentation

The checklist appears after startup fails. It reports confirmed passes, failures,
and checks that have not run. Failed rows have short help and an action: Windows
feature repair invokes an elevated fixed command only after a click; BIOS help
opens instructions because firmware settings cannot be changed by the app.

Unexpected failures receive a short problem-specific summary. Technical details
are collapsed by default and can be copied; the same credential sanitizer used
by logging removes passwords, tokens, URL logins, and authorization headers.
Raw diagnostics remain in logs. No generic checklist replaces the actual error.

When virtualization is disabled or unavailable, the built-in server remains
disabled across app restarts. Only an explicit Enable and check action resumes
checks. Remote servers remain available.

## Channel onboarding

Setup records `setup_started`, `setup_completed`, and `setup_dismissed` separately.
The legacy `setup_offered` flag is not treated as completion. Completion is based
on a successfully loaded nonempty channel list from the built-in server, not on
clicking Finish, opening the IPTV importer, or starting a tuner scan.

When a ready built-in server has no channels, setup is offered at most once per
application session. Cancellation permits another offer on the next launch.
The explicit Don't open setup automatically checkbox suppresses automatic offers;
File > Set Up Channels remains available and lets users change that preference.
Switching to a remote server before the scheduled offer does not open local setup.

## Validation boundary

Source tests cover failure classification, diagnostics, onboarding, readiness,
image reuse, cancellation, and progress. `windows/test-packages.py` exercises the
real distributed executables, archive validation, remote-server use and installer
upgrade with isolated app profiles. Its opt-in backend mode also exercises real
WSLc startup, authenticated readiness, crash recovery, and credential preservation.
The optional `TVHPLAYER_PROFILE_DIR` environment variable isolates TVHplayer's
configuration, cache and logs without changing Windows' own profile directories.
WSL retains its normal OS environment. Previous releases without this override
are tested only for remote-server upgrade behavior, not isolated backend upgrades.

Fresh WSL installation, UAC refusal, Windows policy, BIOS changes, and reboot
recovery must be qualified in disposable Windows VMs. Neither a mocked test nor
one successful run on an already configured host proves those scenarios. See
[the qualification matrix](../windows/backend/VALIDATION.md).

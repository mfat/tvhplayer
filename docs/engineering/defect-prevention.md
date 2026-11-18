# TVHplayer — Defect Prevention Standard

**Status:** Proposed engineering policy  
**Applies to:** All contributors and coding agents modifying TVHplayer  
**Scope:** Application, Qt UI, TVHeadend/HTSP/HTTP integration, playlist/EPG/recording pipelines, libmpv, built-in server, tests, packaging and release workflows  
**Related document:** [`defect-audit.md`](defect-audit.md) — a separate, periodic procedure for searching for remaining defects

## 1. Purpose

Prevent defects *before code is merged*. This is a set of development rules, not a request to run a full repository audit on every task. Apply the relevant controls in the normal implementation workflow. When a new failure mechanism is confirmed, strengthen the appropriate rule or test rather than merely recording the symptom.

These rules were motivated by recurring patterns in TVHplayer's history: blocking Qt callbacks, expensive processing despite worker threads, out-of-order responses, state desynchronization, incorrect external API assumptions, large-dataset regressions, cross-platform packaging failures, and nondeterministic tests. Historical examples appear in §10; they are **evidence of past failure modes, not assertions that those bugs remain open**.

## 2. Definition of done — mandatory for every change

Before declaring a change complete, the coding agent **MUST**:

1. **Describe the intended behavior and invariants.** State what must remain unchanged, including effects on remote servers, the built-in server, recordings, channel lists, and user configuration.
2. **Trace the affected path end-to-end.** Locate the entry point, owners of mutable state, backend interactions, consumers, and cleanup paths. Search for *sibling call sites* of the modified function or pattern.
3. **Review failure conditions.** Consider slow and failed I/O, cancellation, repeat actions, out-of-order responses, partial results, shutdown, malformed data, and platform differences where applicable.
4. **Write a regression test for a bug fix.** Prefer a test that fails on the old behavior and passes with the fix. If not feasible, state precisely why and what other evidence was obtained.
5. **Execute relevant tests.** Run the focused test(s) and an appropriate broader suite. Report exact commands and results; never call an unrun test “passed.”
6. **Review side effects.** Confirm that the change does not silently start scans, downloads, background polling, server mutations, or destructive filesystem operations.
7. **Inspect the final diff.** Check for accidental changes, obsolete branches, hidden new dependencies, and missing documentation or packaging updates.
8. **Report verification limits.** State which environments were tested and which remain unverified. Never claim cross-platform correctness based only on Linux unit tests.

**Avoid unnecessary process:** A small copy edit does not require a concurrency benchmark. A change to HTSP, Qt lifecycle, playlist persistence, libmpv, or packaging does.

## 3. Hard engineering rules

### R01 — Protect the Qt GUI thread

- **MUST NOT** perform potentially blocking HTTP/HTSP calls, disk scans, synchronous subprocess waits, filesystem deletion of many files, large parsing/serialization, or worker `wait()/join()` on the GUI thread.
- **MUST** check indirect work invoked by Qt signals, timers, view delegates, window close handlers, property getters, and signal handlers.
- **MUST** keep model/view application of results bounded. Emitting one Qt signal per channel for thousands of channels is not automatically acceptable just because fetching happens off-thread.
- **MUST NOT** assume `QThread`, `threading.Thread`, or `async` automatically makes work responsive. Python CPU-bound code can hold the GIL; Qt result application also runs on the UI thread. Use measured batching, GIL-releasing native work, or a process when justified.
- **MUST** preserve existing responsiveness benchmarks and add a representative case when introducing a new hot path.

### R02 — Explicit asynchronous ownership and cancellation

Every asynchronous operation **MUST** define:

- **Owner:** window, dialog, server session, playlist job, or supervisor that owns the request and its resources.
- **Request identity:** server identity plus generation/request token when changing selection or server could make a result stale.
- **Completion:** success, failure, timeout, and partial-success semantics.
- **Supersession:** whether a new request replaces, queues behind, or runs alongside the old one.
- **Cancellation:** what stops, what may still commit, and how late results are handled.
- **Shutdown:** how workers, subprocesses, native callbacks, timers, and outstanding signals are cleaned up without blocking the GUI or destroying live objects.

**MUST NOT** apply stale results after a server switch, channel change, dialog closure, or job cancellation. **MUST NOT** destroy running Qt threads. Use connection ownership rules for HTSP and backend objects; do not casually share a mutable connection across concurrent operations.

### R03 — Treat UI state as a projection of real application state

- **MUST** distinguish `pending`, `success`, `missing`, `failed`, `cancelled`, and `stale` when these affect correctness or messaging. A blank EPG cell is not automatically “No EPG.”
- **MUST** derive recording indicators, playback badges, and task counts from authoritative lifecycle information, not optimistic toggles alone.
- **MUST NOT** make data fetching depend unintentionally on whether a UI column, panel, or window is visible.
- **MUST** separate built-in-server state from the actively selected remote-server state. A built-in-server startup event must not reset an unrelated connection.
- **MUST** test state transitions after restart, disconnect, refresh, and server switching.

### R04 — Bound algorithmic work and use stable identities

- **MUST** evaluate complexity for large collections and hot update paths; avoid nested scans and per-update linear searches when an index is appropriate.
- **MUST** test representative sizes for affected features (e.g. ~60,000 channels, ~1,000 groups, several thousand recordings, bursty programme updates, large IPTV/EPG feeds). Choose sizes proportional to the feature.
- **SHOULD** maintain keyed indices for channel-to-row, stable channel UUID, source identity, and similar lookups; rebuild indices only when underlying ordering or membership changes.
- **SHOULD** batch API requests, model notifications, disk writes, and UI updates, while preserving correctness and meaningful progress.
- **MUST** avoid treating display names as unique identities, especially across playlists, channels, and EPG mappings.

### R05 — Make persistent operations resumable and observable

For playlist, EPG, recording, and settings workflows:

- **MUST** define transaction/commit boundaries and what remains after failure or cancellation.
- **MUST** distinguish *processed*, *sent*, and *committed* counts; progress must not claim durable success for unsaved changes.
- **MUST** leave persistent state recoverable after an interrupted import or server timeout.
- **MUST** avoid duplicate channels or mappings on retry; stable stream/source identities are preferred.
- **MUST** keep scan/check behavior independent of metadata edits or refreshes unless explicitly requested or documented.
- **MUST** ensure any time-based flush or checkpoint interval is measured correctly after blocking operations.
- **SHOULD** use atomic file replacement and appropriate temporary directories for generated outputs. Never overwrite recordings unintentionally.

### R06 — Verify external service and native-library contracts

- **MUST** verify assumed endpoint behavior, field names/types, pagination, status values, authentication, and callback lifetime against the actual implementation or documentation—not a guessed shape.
- **MUST** handle missing, invalid, and unexpected responses without corrupting previously valid configuration.
- **MUST** distinguish HTSP vs HTTP paths and the supported capabilities of each; test both when changing shared functionality.
- **MUST** build/normalize URLs centrally and test schemes, explicit and implicit ports, IPv6, trailing slashes, escaping, and credentials with reserved characters.
- **MUST** treat native `ctypes`/libmpv callbacks, OpenGL resources, and Python/Qt object lifetimes as safety-critical; do not release a callback closure or native resource while another thread may still use it.
- **MUST** verify FFmpeg/mpv argument ordering, quoting, timing, and stream behavior with realistic cases, including nonseekable live streams.

### R07 — Design for all supported target environments

When touching platform-sensitive code, **MUST** review applicable combinations of:

- Windows paths, `file://` URIs, file locks, case-insensitive environment variables, process termination, DLL loading, Python ABI and WSL/container paths.
- macOS app bundles, arm64/Intel differences, native menu shortcuts, framework/library loading, file permissions and packaging.
- Linux distribution Python/Qt versions, deb/rpm/AppImage/Flatpak packaging, sandbox portals, X11/Wayland, and GNOME/KDE window behavior.
- Qt native title bars, window restoration, keyboard navigation, accessibility descriptions, resize constraints, DPI and focus.

**MUST** distinguish unit-test compatibility from *packaged binary* compatibility. A dependency downloaded by CI must be available and reproducibly pinned or mirrored appropriately. Verify version alignment between the app and bundled built-in server.

### R08 — Test the negative path and interactions

Tests **MUST** cover relevant failure dimensions, not just the happy path:

- Timeout, connection error, partial/malformed result, and missing fields.
- Repeated click, duplicate request, delayed/out-of-order callback, and cancellation.
- Close or quit while work is running.
- Switching servers/channels while an old request remains pending.
- Alternate settings combinations (hidden columns, disabled panels, different playback backends where supported).
- Large input, burst updates, and multiple data sources with identical display names.
- Platform-specific branches and release/packaging artifacts.

For a bug fix, **MUST** search for other uses of the unsafe pattern and either address them or document why they are safe.

### R09 — Keep tests hermetic, deterministic, and meaningful

- **MUST NOT** let normal unit tests contact GitHub, a real TVHeadend server, public IPTV providers, or the user's environment. Use fake servers, controlled clocks, temporary profiles, and dependency injection.
- **MUST** isolate timers and callbacks so a test's windows cannot trigger network requests after the test has ended.
- **MUST NOT** use arbitrary sleeps where an explicit event, barrier, polling condition, or test-controlled clock would be reliable.
- **MUST** keep timing assertions realistic and explain measured thresholds; do not weaken an assertion merely to make CI green without identifying the source of variance.
- **MUST** clearly label optional slow/live/hardware integration tests and ensure they are not silently relied on by the standard suite.

### R10 — Preserve scope and prove completion

- **MUST** prefer a minimal fix to broad refactoring during defect repair.
- **MUST** avoid unrelated behavior changes in shared UI/backend methods. If refactoring is necessary, add characterization tests first.
- **MUST** distinguish confirmed cause from hypothesis; do not claim a fix is verified without reproducing its target condition where possible.
- **MUST** record unresolved risks and any follow-up test/integration work.
- **MUST NOT** introduce a new global mutable state manager, timer, or worker helper to solve a one-off symptom without checking for an existing owner/abstraction.

## 4. Risk-based verification gates

| Change class | Minimum verification before completion |
| --- | --- |
| Documentation or strings only | Review diff; check affected links/strings; any relevant focused tests |
| Pure data transformation | Input/output tests, malformed and boundary cases, affected consumers |
| Qt widget/model/view | Offscreen UI test; focus/visibility/state combinations; responsiveness when relevant |
| Network, HTSP, HTTP, DVR | Fake slow/error server; timeout/cancel/retry/out-of-order test; protocol parity |
| Playlist, EPG, or persistence | Partial commit/restart/idempotency tests; large-data run; progress semantics |
| libmpv, native callbacks, subprocesses | Lifetime/cleanup tests, play/stop/switch/quit scenarios, native/platform integration where available |
| Packaging, ABI, WSL/Flatpak | Target-platform CI and artifact smoke test; documented unverified hardware/sandbox constraints |

If a high-risk change cannot meet its gate, **MUST** report the exact gap; do not silently downgrade the gate.

## 5. Required implementation workflow for coding agents

1. **Observe:** Read the issue/request and locate relevant code, tests, and recent history. Establish an actual failure mechanism before fixing a bug.
2. **Map:** Identify dependencies, other call sites, async owners, state transitions, external contracts, and platform branches.
3. **Plan minimally:** Specify invariants and the smallest safe change; call out high-risk regressions.
4. **Write a failing regression:** Prefer an observable functional or timing assertion with deterministic fake dependencies.
5. **Implement:** Keep UI work bounded, background jobs owned, state transitions explicit, and persistence recoverable.
6. **Verify:** Run focused and broader tests, check responsiveness or artifacts when applicable, and review the diff.
7. **Report:** Provide changed files, observed behavior, test commands/results, and limitations.

### Completion report template

```text
Change:
Root cause / intended behavior:
Other affected call sites checked:
State/lifecycle/side-effect risks checked:
Tests executed (command → result):
Performance or packaged-platform validation (if applicable):
Remaining unverified conditions:
```

## 6. Recommended test commands

Run from the repository root in an environment with the test dependencies installed:

```bash
# Focused examples — adjust to the changed subsystem
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_responsiveness.py -q
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_playlist_sync.py tests/test_playlist_dialogs.py -q
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_mpv_player.py -q

# Full application suite (as configured by .github/workflows/tests.yml)
QT_QPA_PLATFORM=offscreen python -m pytest tests -q -p no:cacheprovider --timeout=300 -ra
```

Optional slow/live/hardware scenarios should follow the current repository's integration-test controls. **Do not** assume they were run merely because the standard suite passed. Compare against `.github/workflows/tests.yml` if CI commands change.

## 7. Architectural boundaries to preserve

- **Qt presentation:** Render state, collect user intent, and apply small bounded model changes on the GUI thread.
- **Use-case/controller layer:** Own operation identity, supersession, cancellation, state transitions, and authorization of completion callbacks.
- **Backend adapters:** Encapsulate HTSP/HTTP/server-specific requests, parsing, timeouts, and connection ownership.
- **Worker/process layer:** Handle expensive or blocking work and report bounded/coalesced results, without direct widget manipulation.
- **Persistence layer:** Control durable writes, checkpointing, recovery, and idempotent retry.
- **Native player/server supervisors:** Explicitly manage process/renderer lifetime and cleanup order.

Do not require a wholesale rewrite to meet these boundaries. Improve them at touched seams and use characterization tests for risky extractions.

## 8. Review red flags (search prompts, not automatic bug findings)

Look more closely whenever a diff introduces:

- `wait`, `join`, `sleep`, a synchronous HTTP request, or a large loop in a UI callback.
- A new `QTimer` poll, frequent signal emission, repeated full-list traversal, or thousands of widgets.
- Worker completion lambdas that capture a `QWidget`, mutable current-server reference, or channel selection without a request token.
- A shared backend connection used by multiple concurrent operations.
- Repeated normalization/serialization of a large settings object.
- A `try/except` that converts unexpected responses into “success,” “no EPG,” or “working.”
- A new unbounded `limit`, hardcoded URL scheme/port, or hand-built stream command.
- Native callback reassignment during shutdown or use of already-destroyed Qt objects.
- Changes to package dependencies or pins without target-artifact validation.

These are **audit triggers**, not proof. Confirm call paths, timing, and existing safeguards before filing a defect.

## 9. Keeping the policy effective

- Update this policy when a new *generalizable* failure mechanism is proven. Avoid appending one-off bug workarounds.
- Ensure `AGENTS.md` links to this document and instructs agents to apply the relevant rules for every code change.
- Keep detailed historical investigations and unverified findings in [`defect-audit.md`](defect-audit.md) and the separate audit report, not in this short policy.
- Review performance thresholds, target platforms, and integration requirements when supported platforms or packaging change.

## 10. Historical evidence and motivations

Links below point to actual TVHplayer commits, issues or PRs reviewed when the policy was drafted (November 18, 2026):

| Mechanism | Historical example |
| --- | --- |
| Slow server calls froze Qt in multiple places | [Commit `4aa5981`](https://github.com/mfat/tvhplayer/commit/4aa59814b58d91a37644a1869a8a13a292a2bb90) |
| Per-update linear search in large channel model | [Commit `95a09a6`](https://github.com/mfat/tvhplayer/commit/95a09a62a) |
| Python worker's large decode still impacted GUI | [Commit `4fbc61b`](https://github.com/mfat/tvhplayer/commit/4fbc61b98) |
| Built-in server startup disturbed another server | [Commit `71fcaf6`](https://github.com/mfat/tvhplayer/commit/71fcaf68b) |
| Out-of-order stream URL requests | [Commit `e8be854`](https://github.com/mfat/tvhplayer/commit/e8be85450) |
| Native libmpv callback lifetime | [PR #43](https://github.com/mfat/tvhplayer/pull/43) |
| Playlist progress vs durable writes | [Commit `07fb919`](https://github.com/mfat/tvhplayer/commit/07fb919f4) |
| Recording indicator out of sync | [Issue #52](https://github.com/mfat/tvhplayer/issues/52) |
| Programme subtitle coupled to column visibility | [Issue #70](https://github.com/mfat/tvhplayer/issues/70) |
| Windows file URI conversion | [Commit `1d01615`](https://github.com/mfat/tvhplayer/commit/1d0161541) |
| Python native extension / Debian ABI | [Commit `c26cd3a`](https://github.com/mfat/tvhplayer/commit/c26cd3ae1) |
| Test-created windows performing late update checks | [Commit `6990789`](https://github.com/mfat/tvhplayer/commit/69907892a) |

**Principle:** A historical fix is a starting point for reviewing *sibling defects*, not evidence that the same defect still exists.

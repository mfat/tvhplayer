# TVHplayer — Systematic Defect Discovery Playbook

**Status:** Proposed repeatable audit procedure  
**Primary user:** Coding agent or reviewer with a local checkout and test access  
**Output:** `docs/engineering/audit-findings.md` (create for each audit; preserve dated runs or link to tracked issues)  
**Companion:** [`defect-prevention.md`](defect-prevention.md) governs ordinary development; this document governs a dedicated, read-only discovery pass

## 1. Mission and constraints

Find **currently reachable defects or credible failure risks** by looking for remaining instances of failure mechanisms documented in TVHplayer history. The audit must be evidence-driven, current-code-specific, and reproducible wherever possible.

**Non-goals:** style-only criticism, speculative architecture rewrites, relisting fixed historical bugs, inflating counts with duplicate manifestations, or implementing fixes during discovery.

**Default safety rules:**

- **DO NOT** modify production code during the discovery pass.
- **DO NOT** contact public IPTV providers, delete real recordings, alter the user's TVHeadend, or rewrite real settings as part of a test. Use fixtures, fake servers, temporary directories, and disposable instances.
- Temporary repro scripts or isolated tests may be created without production changes; record them and do not silently include them in a release. Request a separate implementation task for fixes.
- **DO NOT** call a concern confirmed based only on a pattern or suspicious API name. Trace the reachable call path and confirm current safeguards.
- **DO NOT** claim that a test was executed unless it was actually run.
- Record the branch, full audited commit SHA, platform/Python/Qt versions, audit date, and test environment before beginning. Older review observations are leads, not findings.

## 2. Inputs and audit preparation

Review, in roughly this order:

1. `AGENTS.md`, [`defect-prevention.md`](defect-prevention.md), architectural docs and current support matrix.
2. Recent commit history and diffs for repairs, reverts, hotfixes, and changed boundaries.
3. GitHub bug issues, relevant PR descriptions/reviews, and reopened or unresolved reports.
4. Tests and CI: `.github/workflows/tests.yml`, `tests/test_responsiveness.py`, `tests/test_pyqt6_ui.py`, `tests/test_playlist_sync.py`, `tests/test_playlist_dialogs.py`, `tests/test_mpv_player.py`, and platform-specific tests.
5. Current call sites and module boundaries, especially `tvhplayer/tvhplayer.py`, `channel_view.py`, `guide_view.py`, `playlist_dialogs.py`, `guide_dialogs.py`, and `tvhplayer/core/`.
6. Any existing performance measurements, logs and reproducible external reports.

Example read-only commands:

```bash
git rev-parse HEAD
git status --short
git log --all --date=short --pretty='%h %ad %s' -n 200
git log --all --regexp-ignore-case --grep='fix\|race\|freeze\|hang\|stale\|blocking\|regression\|crash'
rg -n 'wait\(|join\(|subprocess\.run|requests\.|QTimer|QThread|dataChanged|processEvents|os\.walk|rmtree' tvhplayer
```

The `rg` expression is a **lead generator**, not a detector: many matches are safe. For each, identify the calling thread, reachable workload, and protection already present.

## 3. Hypothesis-driven phases

### Phase A — Mine historical bug mechanisms

Build a table of historical issues and fixes with:

- Symptom and user impact.
- Actual root cause supported by the patch or issue evidence.
- Unsafe pattern (e.g. synchronous remote call in Qt slot, stale async response, O(N×M) row update).
- Fix strategy and regression test introduced.
- Other current code paths with the same mechanism.
- Whether the historical path is still exposed.

**Rule:** For each *confirmed* mechanism, search for sibling implementations. Avoid merely checking that the original patch remains present.

### Phase B — Trace complete workflows

Perform an end-to-end call and state flow for each high-risk workflow:

| Workflow | Main transitions to inspect |
| --- | --- |
| App and built-in server lifecycle | Startup → readiness → server selection → background mode → sleep/wake → shutdown/crash cleanup |
| Remote connection | Add/edit server → normalize URL/credentials → connect/authenticate → metadata subscription → disconnect/reconnect |
| Channel playback | Select → stream URL → player start → frame callbacks → pause/timeshift/record → channel switch/stop/quit |
| Channel metadata | Initial load → group/filter/sort → EPG updates → row repaint → refresh → server switch |
| Playlist management | Add/edit/remove → parse/plan → server mutations → checkpoint → stream checks → cancel/resume/retry |
| EPG management | Fetch/download → decompress/parse/map → import → periodic refresh → stale/missing/error presentation |
| Recording | Schedule/start/stop/cancel → server acknowledgement → Tasks panel → indicator state → late refresh |
| Packaging | Fresh install/upgrade → dependency discovery → native libraries → built-in backend → first run |

For every stage ask: **Who owns it? Which thread/process executes it? Can the user change the target while it runs? What state is authoritative? What remains after a crash?**

### Phase C — Search current code for specific defect families

#### C1. Blocking, GIL contention, and event-loop load

Inspect Qt signals/slots, timers, constructors, dialogs, model updates, event filters, close handlers and player callbacks for:

- Synchronous API calls, filesystem traversals, subprocess waits, joins, or expensive serialization.
- High-frequency refreshes operating on hidden views or unchanged data.
- Per-row `dataChanged` emissions and excessive re-sorts/re-filters.
- Unbounded Python decoding, XML parsing, regex work and bulk memory copies in threads sharing the GIL.
- Full snapshots cloned or normalized on the GUI thread.

Trace both backend work **and the cost of applying its result**. Use existing `StallMeter` tests and representative large fixtures. Report worst/p95 event-loop gap, total busy time, workload size, and environment; do not present a timing number without measurement conditions.

#### C2. Concurrency, stale results and resource lifetime

Search for:

- Results applied to an obsolete selected server/channel/dialog.
- Multiple jobs sharing one HTSP connection without sequencing or ownership guarantees.
- Repeated clicks creating duplicate non-idempotent DVR mutations.
- Cancelled jobs continuing to write, or progress reported before server commit.
- Background starts/stops resetting the wrong server or client state.
- Qt objects destroyed while workers still own signals or callbacks.
- Native `ctypes` callbacks, mpv render contexts, OpenGL widgets, or subprocesses freed/terminated in the wrong order.

Require a sequence diagram or concise timeline for suspected races. Use deterministic barriers/events to force the problematic interleaving instead of sleeps.

#### C3. State, identity and data semantics

Search for:

- Display name used as stable identity; duplicate channel names and changing Xtream provider names.
- Empty/pending/error/no-EPG states conflated.
- UI column visibility or active panel changing whether underlying data is loaded.
- Recording/playing indicators set independently of backend state.
- Sorting and channel/subchannel representation differing between HTTP and HTSP.
- Stale event IDs, cache invalidation gaps, repeated full reloads, and incorrectly assumed page limits.

Test transition matrices, not only single input/output cases.

#### C4. External API, authentication and media assumptions

Inspect:

- TVHeadend endpoints, pagination, total counts, schemas, auth types, error statuses and persistence semantics.
- URL composition with schemes, missing ports, IPv6, escape characters, trailing slashes and existing user-provided URLs.
- Distinctions between remote and built-in Tvheadend, fork and upstream server versions.
- FFmpeg startup/probe behavior, IPTV connection limits, headers, nonseekable streams, hardware decode and playback error paths.
- Unsupported assumptions about libmpv callback threading and cleanup.

Corroborate uncertain server behavior with the actual server implementation or a disposable test server. Do not treat documentation guesses as evidence.

#### C5. Platform and packaged behavior

Inspect all reachable platform branches for:

- Windows paths, file locks, `file://` conversion, Python ABI, case-insensitive environment names, process lifecycle and WSL/container network/storage behavior.
- Flatpak document portal grants, sandboxed recording directories and packaged Qt/libmpv behavior.
- macOS frameworks, permissions, ARM/Intel libraries, window shortcuts and application bundle cleanup.
- X11 vs Wayland/KDE/GNOME geometry, decorations, resizing, focus, accessibility and native event filters.
- Pinned dependencies, disappearing binary artifacts, stale caches, and mismatch between packaged built-in-server versions.

A unit test that passes in offscreen Qt does **not** prove compositor, sandbox, GPU, or bundled binary behavior. Report these separately.

#### C6. Unexpected side effects and resource use

Measure or instrument:

- Idle network traffic and backend request counts.
- Stream checks launched during import/edit/remove when not requested.
- Repeated full channel downloads and metadata subscriptions.
- Disk writes and cache churn on periodic refreshes.
- Memory peaks, orphaned processes, residual temporary files and leaked workers after cancellation/quit.

Do not assume the still-open [traffic issue #63](https://github.com/mfat/tvhplayer/issues/63) is solved or caused by a specific mechanism without reproducing it.

### Phase D — Adversarial verification matrix

Use safe simulated dependencies by default. The following are starting scenarios, not claims of existing defects.

| Scenario | Fault injection | Passing invariant |
| --- | --- | --- |
| Late stream URL | Block remote URL lookup; switch server/channel; release old request | Old result cannot change new playback or server state |
| Slow record/stop | Delay DVR RPC; press action twice; let response arrive after timeout | No unintended duplicate operation; UI remains responsive |
| Close dialog mid-request | Hold backend response while dialog closes | Prompt close; worker safely retained/cancelled; no destroyed-object access |
| Startup/remote overlap | Activate remote server while built-in server transitions to ready | Remote channel list and selected server remain intact |
| EPG visibility combinations | Hide Now and Next, enable subtitle/description under channel name | Data availability does not depend on hidden columns |
| Large channel burst | ~60k channels, ~1k groups, thousands of event changes | Bounded main-thread work and correct ordering/state |
| Large playlist interruption | 50k–100k entries, slow writes, cancel or fail mid-batch | Durable progress truthful, no data loss/duplicates on retry |
| EPG/guide import under load | Large XMLTV/compressed feed and repeated updates | GUI responsive; bounded temp files and resources |
| Idle usage | No playback, optional automatic checks disabled, several polling cycles | Only documented necessary network traffic |
| Native player shutdown | Quit while mpv frame callback and worker work are active | No crash, callback-after-free, hang or leaked process |
| Cross-platform file handling | Windows URI, open compressed file, Flatpak selected folder | Correct conversion, closing/replacement and portal permissions |
| Release upgrade | Install/upgrade packaged artifacts in clean target environment | Compatible Python/native libs and required assets present |

Also test with malformed/unexpected API records and duplicate channel names. Add a scenario only if it exercises a reachable current path.

### Phase E — Confirmation and false-positive elimination

For each candidate:

1. Locate **exact current code** and calling path. Record `path:line` at the audited SHA.
2. State the violated invariant and a concrete timing/data/environment sequence.
3. Check existing defensive code, test coverage and whether the path is actually reachable.
4. Isolate with a deterministic fake, controlled clock, workload, or disposable integration environment.
5. Capture a failing assertion, log, stack trace, measured stall, wrong state, or protocol mismatch.
6. Re-run the reproduction and relevant tests to distinguish reproducibility from timing noise.
7. Identify other surfaces using the same mechanism; combine duplicate findings by root cause.
8. Specify smallest likely fix, regression tests, and risks—**without modifying production code**.
9. Classify evidence level as **Confirmed**, **Strongly supported but unverified**, or **Hypothesis**.

When unavailable environments prevent confirmation, give the missing evidence or environment precisely (e.g. real GNOME Wayland, Windows packaged build, physical HDHomeRun), not a generic “needs testing.”

## 4. Prioritization

Use **severity** and **evidence** separately. A severe hypothetical race is not automatically more actionable than a reproduced data-loss defect.

| Severity | Criterion |
| --- | --- |
| **P0 — Critical** | Proven data loss/corruption, severe security exposure, broad crash-on-start, or similar release-blocking defect |
| **P1 — High** | Repeatable crashes, UI hangs, broken core playback/recording, irreversible incorrect server mutation, or broadly broken platform packaging |
| **P2 — Medium** | Significant wrong UI state, limited performance regression, incorrect handling of valid inputs, workaround available |
| **P3 — Low** | Minor behavioral or presentation bug with limited impact |

Prioritize within each tier by reachability, user impact, frequency, number of platforms/users affected, and reproducibility. Do not infer prevalence from one bug report.

## 5. Audit report requirements

Save a report at `docs/engineering/audit-findings.md`. For subsequent audits, timestamp or archive prior reports so the previous evidence remains traceable.

### Required report header

```markdown
# TVHplayer Defect Audit — YYYY-MM-DD
- Audited commit: <full SHA>
- Branch and worktree status: ...
- Environment(s): OS, Python, Qt, relevant server/player versions
- Scope inspected: modules, commits/issues, test suites
- Tests actually run: commands and pass/fail/skip counts
- Important omissions: untested platforms, hardware, integration dependencies
- Summary: confirmed / strongly supported / hypotheses
```

### Individual finding template

```markdown
## TVH-AUD-001 — Descriptive title
- Severity: P1
- Evidence: Confirmed | Strongly supported but unverified | Hypothesis
- Component / category: Qt event-loop / async lifecycle / data / protocol / platform / test
- Audited code: `path/file.py:123-160` at `<full SHA>`
- Reachable through: <UI action or background trigger>
- Violated invariant: <what must always be true>
- Failure sequence: <specific events / inputs / ordering>
- Actual evidence: <test assertion, logs, timings, code-path proof>
- Reproduction: <safe exact command or script and expected failure>
- Existing safeguards and why insufficient: ...
- User impact and scope: ...
- Root cause and sibling call sites checked: ...
- Minimal proposed correction: ...
- Regression tests to add: ...
- Fix risks / cross-platform concerns: ...
- Limitations or missing validation: ...
- Related history/issue: <link if relevant>
```

**Never invent line numbers, executed test results, performance measurements, or source citations.** Use the audited checkout. Historical links support the *pattern*, while current-code references support the *new finding*.

## 6. Required final deliverables

An audit run should produce:

1. A short executive summary describing what is confirmed vs uncertain.
2. Findings ranked P0–P3, deduplicated by failure mechanism, with evidence and safe reproduction.
3. A **sibling-path coverage table** for each confirmed failure family: inspected locations, safe locations, vulnerable locations, and uninspected locations.
4. A **verification ledger** listing exact test commands, results, sizes, and measured conditions.
5. A **coverage gap list** showing tests/platforms/hardware not available and how to validate them later.
6. A minimal remediation order, distinguishing critical fixes from architectural debt.
7. Suggested updates to [`defect-prevention.md`](defect-prevention.md) **only if a new generalizable mechanism was proven**.

Stop only when the chosen scope has been traversed or constraints are explicitly documented. Do not stop at the first few promising suspects and call it comprehensive.

## 7. Suggested audit execution strategy

Prefer **several focused passes** over a single undifferentiated agent run:

1. **UI/performance pass:** main thread, model/view, Qt notifications, GIL, timers and result application.
2. **Concurrency/state pass:** ownership, cancellations, stale replies, remote-vs-built-in state, recording, native/player cleanup.
3. **Integration/platform pass:** protocol, playlist/EPG contracts, packaging, WSL/Flatpak, Windows/macOS/Wayland.
4. **Independent verifier pass:** challenge every finding, reproduce, eliminate duplicate or unreachable reports, assign evidence level.

Run the high-risk passes first. Reports from independent agents should be consolidated against the same commit SHA to avoid mismatched line numbers or already-fixed findings.

## 8. Historical leads for the first audit

These are prompts for searching *other current paths*, **not a list of outstanding defects**.

| Historical mechanism | Evidence | Suggested sibling search |
| --- | --- | --- |
| Blocking synchronous operations in the Qt UI thread | [Commit `4aa5981`](https://github.com/mfat/tvhplayer/commit/4aa59814b58d91a37644a1869a8a13a292a2bb90) | All dialogs, menu commands, timer callbacks, close handlers |
| Large model updates with repeated searches | [Commit `95a09a6`](https://github.com/mfat/tvhplayer/commit/95a09a62a) | Guide, recordings, filtered channels, group badges |
| Worker decode holding the GIL | [Commit `4fbc61b`](https://github.com/mfat/tvhplayer/commit/4fbc61b98) | XMLTV, playlist parsing, HTSP messages, JSON, regex |
| Old request completes after selection change | [Commit `e8be854`](https://github.com/mfat/tvhplayer/commit/e8be85450) | Cast, search, metadata, recording, server switching |
| Built-in server event invalidated unrelated remote state | [Commit `71fcaf6`](https://github.com/mfat/tvhplayer/commit/71fcaf68b) | Backend reconnect, sleep/wake, autostart, recording updates |
| Native callback use-after-free on shutdown | [PR #43](https://github.com/mfat/tvhplayer/pull/43) | Render callback lifecycle, Qt event filters, media teardown |
| GUI state coupled to visibility | [Issue #70](https://github.com/mfat/tvhplayer/issues/70) | Hidden columns, panes, dialogs and filtered views |
| Playlist checkpoints and progress differ from durable writes | [Commit `07fb919`](https://github.com/mfat/tvhplayer/commit/07fb919f4) | Cancellation, server timeouts, batch flush, retries |
| GUI tests running external update checks | [Commit `6990789`](https://github.com/mfat/tvhplayer/commit/69907892a) | All timers and delayed tasks surviving test teardown |
| Platform-dependent path and ABI rules | [Windows URI commit](https://github.com/mfat/tvhplayer/commit/1d0161541), [Python ABI commit](https://github.com/mfat/tvhplayer/commit/c26cd3ae1) | Every OS branch and packaging workflow |
| Open reports requiring current verification | [Window geometry #56](https://github.com/mfat/tvhplayer/issues/56), [unexpected traffic #63](https://github.com/mfat/tvhplayer/issues/63), [playlist edit #65](https://github.com/mfat/tvhplayer/issues/65) | Reproduce against HEAD before attributing any root cause |

## 9. Prompt to activate this playbook

```text
Read AGENTS.md, docs/engineering/defect-prevention.md and
 docs/engineering/defect-audit.md.

Audit TVHplayer HEAD for remaining defects using the documented five-phase
procedure. Search for sibling defects of the repository's historical failure
mechanisms. Reproduce candidates safely, separate confirmed findings from
hypotheses, and rank by severity and evidence.

Do not change production code or real user/server data. Save the report to
 docs/engineering/audit-findings.md with exact audited SHA, code locations,
reproduction evidence, tests actually executed, and unverified environments.
Follow the methodology until the defined scope is covered, not merely until
several bugs have been found.
```

---

**Guiding principle:** A *pattern* provides a hypothesis; a **reachable current code path plus evidence** provides a finding. The goal is fewer undiscovered defects—not more speculative audit output.

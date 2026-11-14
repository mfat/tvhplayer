# Optional SQLite Settings Backend — Agent Execution Prompt

You are implementing and evaluating an optional SQLite configuration backend for TVHplayer’s Tvheadend fork.

Work autonomously within the scope below. Start with the benchmark phase. Do not implement the production backend unless the benchmark gate passes. Do not stop after producing another plan: inspect the repositories, perform the authorized work, verify it, and report results.

## Projects and locations

- TVHplayer: `/home/mahdi/GitHub/tvhplayer`
  Repository: https://github.com/mfat/tvhplayer
- Tvheadend fork: `/home/mahdi/GitHub/tvheadend`
  Repository: https://github.com/mfat/tvheadend
  Target branch: `tvhplayer`

Verify actual paths, branches, revisions and working-tree state before starting. Read applicable AGENTS.md instructions. Preserve unrelated user changes. Use isolated worktrees when necessary. Do not reset, overwrite or commit unrelated changes.

Follow the installed codebase-memory skill for structural exploration. Use Context7 for current SQLite and other library/API documentation. If indexed source is stale or incomplete, read the relevant source directly.

Do not push, merge, publish releases or modify a live user configuration. Local implementation, tests, disposable fixtures and local commits are authorized.

## Objective

Determine whether SQLite still provides a meaningful startup improvement over the current optimized file backend. If it does, implement an optional, authoritative, durable and reversible SQLite settings backend.

The target workload is approximately 59,000 IPTV channels and more than 120,000 configuration files.

Keep the file backend as the default and a fully supported export target.

SQLite must store the existing serialized settings payloads as BLOBs:

- Ordinary settings use JSON.
- Some mux/network settings use compressed HTSMSG binary.
- Reuse the existing serializers and decoders.
- Do not redesign settings objects into relational tables.

## Non-goals

- Rewriting EPG or recording databases.
- Changing HTSP.
- Redesigning TVHplayer’s channel UI.
- Changing JSON/HTSMSG formats.
- General code cleanup or unrelated optimizations.
- Shipping a read-only SQLite snapshot as a production cache.

## Existing material to reuse

Inspect these files before implementing.

TVHplayer:

- `docs/startup-optimization/0002-sqlite-startup-prototype.patch`
- `docs/cold-startup-profile.md`
- `docs/cold-startup-measurements.json`
- `docs/tvheadend-source.md`
- `packaging/tvheadend/pins.env`
- `rpm.spec`
- `io.github.mfat.tvhplayer.yml`

Tvheadend:

- `src/settings.c`
- Relevant settings headers, filebundle implementation and settings callers.

The existing prototype includes a Python importer, a nodes schema, a C SQLite reader and shared decoding work. Adapt useful code rather than starting over. Inspect its tests and limitations.

Historical experiment results, for context only:

- Cold file-data native startup: file 24.511 s; SQLite 16.150 s.
- Warm native startup: file 19.261 s; SQLite 15.779 s.
- One-time import: 52.327 s.
- Compact database: 174,292,992 bytes.
- Source payload: 117,792,497 bytes.
- Sorted API snapshots matched in that experiment.
- Successful playback was not established.

These measurements do not prove a benefit against the latest optimized fork.

At an earlier inspection:

- TVHplayer pinned `57610597563a3f49ac1d132c4735cb0bee6d4364`.
- The local fork was at `27012c0849c363bec555bfb51a321a0b22381df8`.

Verify current revisions; do not assume either remains current.

The optimized fork has included parallel settings loading, reused directory handles, sorted-set/bouquet improvements, reduced early notifications and overlapping XMLTV discovery. Determine which changes are present in the actual benchmark revision.

## Working rules

1. Keep a concise progress log with completed work, exact revisions, commands, results and unresolved issues.
2. Report meaningful progress regularly.
3. Use disposable fixtures, separate configuration paths and separate ports.
4. Never alter or run migration against the user’s live profile.
5. Do not silently disable features to improve one benchmark arm.
6. Do not fabricate timings, playback success or correctness results.
7. If a real fixture or working test stream is unavailable, complete independent harness work and identify the precise missing input. Synthetic tests do not satisfy the real-workload performance gate.
8. Ask only for information that cannot be discovered safely.
9. Keep changes in reviewable logical units corresponding to the phases below.
10. A failure of the performance gate means stop production implementation, retain the research artifacts and report the evidence.
11. Inconclusive measurements mean the gate has not passed.
12. Do not treat process-kill testing as proof of power-loss durability.

## Phase 0 — Inspection and implementation contract

Before coding the production backend, record:

- Exact repository revisions and build configuration.
- Existing settings API signatures and behavior.
- All direct configuration-directory access relevant to migration.
- Which paths are managed settings and which remain ancillary files.
- Existing bundled-default behavior.
- Existing startup/save/delete behavior.
- Existing profile/process locking.
- Available fixtures and benchmark instrumentation.
- Current package and platform support.

Audit:

- `hts_settings_load`
- `hts_settings_load_r`
- `hts_settings_save`
- `hts_settings_remove`
- `hts_settings_exists`
- `hts_settings_open_file`
- `hts_settings_makedirs`
- Direct configuration paths, renames, deletes and backup operations.

Do not assume every file beneath the profile is a settings record.

Resolve these design requirements explicitly before production implementation.

### A. Missing records versus intentional deletion

The backend must distinguish:

- A key that has never been configured.
- A stored value.
- An intentionally deleted value.
- A read/decode/storage error.

Bundled defaults may apply where the agreed compatibility behavior requires them. They must not silently resurrect intentionally deleted authoritative records.

The existing file loader may fall back to bundled defaults when loading returns no result. Inspect the actual behavior and document any deliberate change.

Use tombstones or another explicit suppression mechanism if needed. Define:

- File deletion.
- Directory/subtree deletion.
- Recreation beneath a deleted directory.
- `exists` behavior.
- Export to file mode.
- Compatibility with older file-only binaries.

Do not claim lossless export if deletion suppression cannot be represented in the destination. Resolve that incompatibility or state and enforce the supported boundary.

### B. Authority and version compatibility

Exactly one backend is authoritative for managed settings.

When SQLite is active:

- Managed reads and writes both use SQLite.
- Old managed files are a backup, never a live fallback.
- Database failure must not silently select stale files.
- Missing selected databases must not be silently recreated as empty databases.
- Unknown or unsupported schema versions must fail clearly.

Define precedence for startup options and any profile marker.

An older Tvheadend binary may ignore a new marker. Add application-level compatibility checks and define the supported downgrade procedure. Require verified export before switching to a file-only binary.

Explicitly address direct launches of older binaries. Do not claim a marker alone protects against binaries that do not understand it.

### C. Persistence and failure reporting

Define when a save is considered committed and visible to subsequent reads.

`hts_settings_save` historically returns void. Inspect current callers and provide a concrete error-reporting strategy. Logging an SQL error while the application reports a successful save is insufficient.

Define bounded retry behavior, degraded/error state, shutdown handling and any acknowledgment limitations.

### D. Profile lifecycle locking

Use a profile-wide lock shared by supported server launches, migration, export and recovery operations.

SQLite transaction locks alone do not protect a backend switch or ancillary files.

## Phase 1 / PR A — Benchmark parity

Implement only research tooling and the adapted read-only prototype in this phase.

1. Adapt the existing prototype onto the selected current optimized fork revision.
2. Provide a same-binary file/SQLite switch.
3. Record compiler, build options, dependency versions, hardware, filesystem, fixture fingerprint and exact commits.
4. Restore an identical disposable fixture before each measured run.
5. Compare optimized file backend without application prefetch, optimized file backend with normal TVHplayer prefetch, and SQLite prototype with explicitly documented prefetch behavior.
6. Use the actual current product configuration as the primary comparison baseline.
7. Measure prefetch cost inside the application-launch interval.
8. Keep scanning, grabbers, bouquet behavior, recordings and EPG settings equivalent.
9. Instrument saves/removes and subsequent settings reads during startup. Detect reads that would observe stale SQLite snapshot data. Reject runs affected by divergence. Do not hide the problem by disabling features in only one arm. If the read-only prototype cannot produce a valid comparison, report the limitation and design the smallest research-only correction needed.
10. Collect at least 10 runs per variant per cache condition.
11. Alternate or randomize run order using a recorded schedule.
12. Separate warm file-data cache, file-data eviction, and true cold OS startup, only if actually measured.
13. Do not describe `POSIX_FADV_DONTNEED` as equivalent to a cold boot.
14. Evict or warm all relevant backend data consistently.
15. Report median, range and raw samples, p95 with sample-size limitations stated, CPU time, I/O, peak RSS, native server START, HTSP `initialSyncCompleted`, full Qt channel-list population/rendering, and first successfully decoded playback frame from a confirmed working stream.
16. Define timestamp origins and readiness events precisely.
17. Report one-time import separately.
18. Verify counts and normalized sorted hashes for channels, services, muxes, networks, tags, bouquets, EPG, and HTSP channel metadata and stable IDs.
19. Document exclusions of volatile fields. Do not normalize away meaningful differences.
20. Control time/network-dependent inputs where feasible without changing feature parity.

### Benchmark gate

Proceed only if like-for-like results show:

- At least approximately 20% or at least 3 seconds improvement in median cold end-to-end application launch against the current optimized product baseline.
- Reproducible results, not an isolated fast run.
- No material warm-start, memory, playback or correctness regression.

Define the primary cold condition and readiness endpoint before interpreting results. Explain any practical regression tolerance.

If the gate fails or remains inconclusive:

- Stop production backend work.
- Preserve the reproducible prototype and measurements.
- Explain the result and any remaining uncertainty.

Deliver:

- Reproducible build/import/run/verification scripts.
- Raw machine-readable measurements.
- A concise results report.
- Exact revisions and fixture fingerprints.
- A clear pass/fail/inconclusive decision.

## Phase 2 / PR B — Authoritative storage backend

Start only after Phase 1 passes.

Architecture:

- Put file and SQLite drivers behind existing settings APIs.
- Keep SQLite details out of channel/IPTV/business logic.
- Keep file mode as the default.
- Keep production selection inaccessible until migration/recovery is ready.
- Reuse the file backend’s serialization and shared decoder.
- Preserve recursive depth, path rules, skipped names and relevant ordering.

Starting schema:

```sql
CREATE TABLE metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE nodes (
  path TEXT PRIMARY KEY,
  parent TEXT,
  name TEXT NOT NULL,
  kind INTEGER NOT NULL,
  ordinal INTEGER NOT NULL,
  data BLOB
);

CREATE INDEX nodes_children ON nodes(parent, ordinal);
```

This is a starting point, not a frozen schema. Add constraints and deletion-state representation required by the contract.

Store:

- Schema version.
- Backend compatibility version.
- Completed migration marker.
- Source manifest/fingerprint.
- Any generation identifier needed for consistency.

Requirements:

- Canonical relative paths.
- Valid parent/name/path relationships.
- Defined root representation.
- Exact subtree boundaries.
- Deterministic sibling ordering.
- Defined insert/delete/rename ordering behavior.
- Validation against path traversal.
- Explicit symlink handling.
- No second authoritative directory tree.

Do not adopt WITHOUT ROWID by assumption. Benchmark schema changes if they affect performance materially.

Reads:

- Prepared statements.
- Batch child enumeration where useful.
- `ORDER BY ordinal` with a deterministic tie policy.
- Caller-specified recursive depth.
- Safe connection ownership.
- Measured choice of serial versus parallel reading.
- Defined snapshot/read-after-write behavior.
- Correct handling of empty, missing, malformed, compressed and oversized payloads.
- Storage errors distinguishable from absence.

Writes:

- Real durable create/update operations.
- File deletion.
- Directory/subtree deletion.
- Directory creation and exists semantics.
- Empty directories.
- File/directory replacement according to actual API semantics.
- Rename/move behavior where callers require it.
- Appropriate ancestor cleanup.
- Deletion suppression according to the agreed contract.

Transactions:

- One serialized writer with documented lock ordering.
- Bounded transaction sizes for bulk updates where semantics permit.
- No unbounded write queue.
- No indefinite persistence deferral.
- Checked SQL calls, including commit and close/finalization errors.
- Bounded handling of `SQLITE_BUSY`.
- Explicit `SQLITE_FULL` and I/O-error behavior.

Durability:

- Begin with `synchronous=FULL`.
- Compare WAL and rollback journaling on supported filesystems.
- Do not relax durability solely because process-kill tests pass.
- Document checkpoint policy and WAL growth behavior.
- Verify SQLite build/linkage and relevant runtime configuration.

Deliver:

- Backend implementation.
- Contract tests covering file/SQLite behavior.
- Failure reporting and concurrency documentation.
- Evidence that ordinary file mode still works unchanged.

## Phase 3 / PR C — Migration, export, backup and recovery

No normal user may select SQLite before this phase passes.

Conversion:

1. Acquire the profile lifecycle lock.
2. Stop Tvheadend and prevent restart for the entire conversion and activation.
3. Verify sufficient working space or fail safely on insufficient space.
4. Back up the complete profile, including ancillary assets.
5. Preserve required ownership and permissions; treat credentials as private.
6. Import managed records into `settings.sqlite.new`.
7. Exclude database sidecars, temporary files, backups and unmanaged paths.
8. Treat unreadable or unsupported records as explicit errors.
9. Use one transaction or bounded transactions with an unmistakable incomplete state.
10. Verify `PRAGMA integrity_check`, complete payload manifest, counts, required schema invariants, and representative decoding, plus broader checks where feasible.
11. Validate recovered server state on a disposable copy where feasible.
12. Finalize/checkpoint and close the database safely before publishing it.
13. Durably publish the database and then the authoritative selector using a documented recoverable protocol.
14. Preserve the original authoritative state until the activation commit point.
15. Release the lock and start the selected backend only after verification.

Do not describe two independent file renames as one atomic transaction.

Document the exact on-disk states and recovery action after failure:

- Before import.
- During import.
- After verification.
- After database publication.
- Before selector replacement.
- After selector replacement.
- During cleanup.

Use appropriate file and parent-directory synchronization for the platform. Check all errors.

Cancellation:

- Safe before the activation commit point.
- Must not leave an ambiguous authoritative backend.
- Cleanup must never delete the last valid copy.

Export/rollback:

1. Acquire the profile lifecycle lock.
2. Stop Tvheadend before taking the export snapshot.
3. Keep it stopped through export, verification and activation.
4. Export current SQLite state into a temporary file profile.
5. Preserve current ancillary files and required permissions.
6. Preserve post-migration edits and deletions.
7. Apply the defined bundled-default/deletion export semantics.
8. Verify payload manifests and recovered application state.
9. Switch authority through the same recoverable activation mechanism.
10. Preserve a verified database backup.

Never implement rollback by selecting the original stale file tree.

Backup:

- Use the SQLite backup API or another documented consistent snapshot procedure.
- Do not copy only the main database while committed data may remain in WAL.
- Copying database and WAL independently during writes is not automatically consistent.
- Coordinate ancillary state as required.
- Test restore, not just backup creation.
- Require explicit user choice before restoring a backup that can discard newer state.
- Do not claim automatic corruption repair.

Compatibility:

- Reject unsupported schemas without mutating them.
- Define supported upgrades.
- Require export for incompatible downgrades.
- Test application launch checks against older binaries.

## Phase 4 / PR D — Application integration and verification

TVHplayer UI:

- Explicit experimental opt-in.
- Clear current backend status.
- Conversion progress.
- Safe cancellation.
- Export/switch-back action.
- Actionable storage and recovery errors.
- No hidden environment variable that silently switches production state.
- Conversion happens once, never on every normal launch.

Correctness tests:

- 100, 1k, 10k and approximately 60k-channel fixtures.
- IPTV URL edits.
- Channel names/numbers/metadata.
- Tags and bouquets.
- Network/mux/service creation and deletion.
- Deleted entries remain deleted after restart.
- Stable IDs and matching API/HTSP state.
- Repeated conversion/export cycles.
- Read-after-write behavior.
- Credentials and access-control settings.

Functional tests:

- Channel mapping.
- Bouquet rebuilds.
- EPG restore/update.
- Recording scheduling and edits.
- DVR/autorec.
- Authentication.
- Playback from a confirmed working stream.
- Shutdown/restart during and after write bursts.

Edge and fault tests:

- Plain and compressed settings.
- Corrupt payloads.
- Missing and empty paths.
- Nested/empty directories.
- Long paths.
- Hidden/temp files.
- Symlinks and traversal attempts.
- Bundled defaults and deletion suppression.
- Permissions.
- Disk full.
- Busy database.
- Failed commits.
- Interrupted conversion/export.
- Process termination during writes.
- Corrupt database.
- Unsupported schemas.
- Concurrent launches.
- Old-binary downgrade attempts.
- Failure at every activation transition.

Platforms:

- Native Linux.
- Flatpak.
- Windows built-in server under WSL.
- WSL Linux filesystem and `/mnt/c` only where supported.
- macOS where a built-in server is actually distributed.

Validate linkage, filesystem locking, permissions and packaging on each supported platform. Clearly distinguish tested from untested platforms.

### Final performance gate

Repeat the Phase 1 comparison using the complete durable backend, including realistic writes and checkpointing.

The read-only prototype’s result alone does not qualify production release.

Measure:

- Cold/warm end-to-end launch.
- Native startup.
- HTSP sync.
- UI completion.
- First playback frame.
- CPU/I/O/memory.
- Playlist import/update throughput.
- Conversion/export duration.
- Busy and idle disk conditions.

Stop release preparation if the complete backend loses the required benefit or introduces material regressions.

## Phase 5 / PR E — Release preparation

Only after correctness, recovery, platform checks and the final performance gate pass:

- Prepare synchronized source-pin updates in `packaging/tvheadend/pins.env`, `rpm.spec`, and `io.github.mfat.tvhplayer.yml`.
- Follow `docs/tvheadend-source.md`.
- Pin one tested fork commit.
- Run package consistency checks.
- Keep the file backend default.
- Keep SQLite experimental and explicitly opt-in.
- Document conversion, backup, recovery, export and downgrade.
- Prepare reviewable local changes and release notes.

Do not push, merge or publish without separate authorization.

## Final acceptance criteria

- Equivalent supported API/HTSP state across backends and restarts.
- Every supported mutation persists according to the documented contract.
- No stale-file fallback or mixed authority.
- Bundled defaults and intentional deletions have explicit, tested semantics.
- Conversion/export interruption leaves a recoverable authoritative profile.
- Export preserves committed changes made after migration.
- Backup restoration is verified.
- Unsupported binaries/schemas cannot silently masquerade as a successful supported launch.
- The complete durable implementation passes the performance gate.
- File-mode behavior remains compatible.
- All claimed platform and playback results have actual evidence.

## Final report

Report:

1. Phases completed.
2. Exact revisions and changed files.
3. Benchmark results and gate decision.
4. Correctness, recovery and platform verification performed.
5. Tests not run and why.
6. Remaining limitations or required inputs.
7. Reviewable commits/artifact locations.
8. Whether production enablement criteria are satisfied.

If the benchmark fails, the correct outcome is a documented research result and no production backend implementation.

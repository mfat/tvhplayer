# TVHplayer Engineering Rules

1. Before editing code, identify the relevant data flow, state owners, asynchronous operations, platforms, and affected call sites. Explain the failure mechanism. Do not implement speculative fixes.

2. Never execute network requests, blocking filesystem operations, subprocess waits, worker joins, large JSON/XML decoding, or unbounded loops in the Qt GUI thread. Audit indirect calls too.

3. Background threads do not guarantee responsiveness: Python GIL contention, Qt signal storms, and large result application must also be measured. Use bounded batches, GIL-releasing native code, or worker processes where justified.

4. Every asynchronous operation must define its owner, cancellation behavior, stale-result rejection, failure behavior, and shutdown cleanup. Never apply a result to a closed dialog, obsolete server, or superseded selection.

5. No unbounded per-item widget creation or nested linear scans in hot paths. Large channel lists and recording histories require bounded, incremental, or indexed processing.

6. Keep server state, cached state, pending state, and displayed state distinct. UI visibility, filtering, or column configuration must not determine whether underlying data is fetched.

7. Confirm external contracts against TVHeadend, HTSP, HTTP, FFmpeg, mpv, and operating-system behavior. Do not guess protocol fields, URL construction, authentication behavior, thread safety, or native callback lifetimes.

8. Every new feature or fix requires tests of success, failure, timeout, cancellation, repeated invocation, late responses, missing data, and interaction with related features when applicable.

9. For user-visible background operations, progress must distinguish work processed, server changes committed, and final completion. Cancellation must leave persistent state recoverable.

10. Check Linux, Windows, and macOS behavior for paths, case sensitivity, file locking, subprocesses, Qt key sequences, and packaging. For GUI changes, consider GNOME/KDE, X11/Wayland, DPI, resizing, keyboard access, and focus behavior.

11. Tests must be hermetic: no real GitHub update checks, live server dependencies, uncontrolled timers, real user configuration, or external downloads unless explicitly classified as integration tests.

12. Every performance-sensitive change must be tested with representative large datasets, slow servers, burst updates, and measured GUI responsiveness. No unexplained regression of an established budget.

13. Preserve existing settings, user data, server connections, recording state, and unrelated behavior. Before changing a shared method, identify and test its other consumers.

14. Each bug fix must include a regression test that fails before the fix and passes afterward, unless technically impractical. Report any untested assumptions.

15. Before declaring completion, run relevant targeted tests and the available full suite, inspect the diff, and state which platforms and integrations were actually verified. Never describe unexecuted tests as passing.

Overall: Before implementing any feature or bug fix, identify how it behaves under slow execution, cancellation, repeated invocation, large datasets, different operating systems, and concurrent operations. Add tests for the relevant failure scenarios before declaring the work complete.

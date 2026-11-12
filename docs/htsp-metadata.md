# Progressive HTSP metadata

The channel fetch still waits for `initialSyncCompleted` before reporting success.
While it waits, the window consumes accumulated channel changes every 150 ms, so
channels can appear before the complete list, service details and now/next have
arrived. Partial metadata does not complete channel onboarding.

After authentication, metadata connections start one socket reader. RPC callers
serialize writes and wait for their sequence-numbered replies; the reader alone
receives frames and dispatches unsequenced metadata. Incomplete frames stay in the
receive buffer. Idle connections remain subscribed. Disconnects and explicit
close wake waiting requests, and close joins the reader before a connection can
be reused. Connections used only for administrative queries retain the synchronous
path and do not request the full channel dataset.

The backend protects metadata snapshots with a lock. Channel changes coalesce by
HTSP ID; repeated updates to a channel occupy one pending entry, and deletes
replace updates. A Qt timer takes those batches on the GUI thread. The table
updates source slots and remaps persistent indexes with layout notifications,
preserving sorting, filtering and selection without resetting the model for each
batch. Deleted source slots are reused.

Fetches are cancelled when replaced or when the window closes. Batches are checked
against the active server's endpoint, protocol and credentials. Completed fetches
use the latest synchronized snapshot so changes received during optional RPCs are
not overwritten. A disconnected adopted metadata connection triggers a background
reload, with at least five seconds between attempts.

This changes channel presentation and live updates, not Tvheadend's own startup
or the HTTP playback path. It does not persist channel metadata across launches.

## Validation

`tests/test_htsp_reader.py` exercises real socket pairs: fragmented frames,
sequence dispatch, idle updates, initial synchronization, disconnects, timeouts,
shutdown and reconnects. Channel model and window tests cover batched changes,
filtering, selection, server/account switching and completion ordering.

A local synthetic 60,000-channel socket-to-model run displayed its first batch in
0.18 seconds and completed in 3.9 seconds across 24 batches, without a model reset.
This isolates the client pipeline; it excludes Tvheadend startup, authentication,
server/network latency, optional service/EPG requests and a fully populated UI.

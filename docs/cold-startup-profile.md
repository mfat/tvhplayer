# Native Tvheadend startup investigation (2026-11-13)

This investigation is separate from the pending Python metadata/UI work.
The source baseline is the fork at `40e88d4ce`, including the IPTV, idnode,
and HTSP tag fixes described in `tvheadend-source.md`. The local executable
also contains the previously developed sorted-set insertion and settings-directory
reuse changes. Those changes were retained in both test executables.

## Measurement method

All retained startup comparisons use fresh processes and a fresh copy of the same
profile on the workspace's **ext4** filesystem. `/tmp` on this host is tmpfs;
earlier experiments there were discarded as disk-startup measurements. Copies
retain all networks, muxes, services, channels, bouquets, access settings and EPG.
No scan, health check, EPG restoration or bouquet module was disabled. Each test
uses unique loopback ports and the same foreground command options as the Linux
built-in server. Only isolated test processes are stopped.

For cold file-data trials, the copied filesystem is flushed with `sync -f`, then
`POSIX_FADV_DONTNEED` is requested for each copied file before process launch.
Directory/inode caches are not globally dropped; this is **not** a cold OS boot.
Runs overlapping interactive TVHplayer/playback are excluded from conclusions.
Warm trials still use new processes but leave file-data caches populated.

Startup is measured through the START notice, followed separately by authenticated
HTSP hello/authentication and `enableAsyncMetadata(epg=0)` through the received
`initialSyncCompleted` marker. Existing `--trace main` enter/leave messages identify
stages. Additional monotonic trace-only measurements separate IPTV network loading
from thread creation, EPG inflate/decode/restore/destruction, and HTSP enqueue work.
No new server command-line option or configuration format is introduced.

## Attribution

An ext4 warm candidate run recorded these elapsed stages (seconds):

| Stage | Time |
| --- | ---: |
| MPEG-TS initialization | 7.760 |
| IPTV network loading, within MPEG-TS | 7.748 |
| IPTV thread creation, within MPEG-TS | 0.002 |
| Channels | 3.068 |
| Bouquet resolution | 1.153 |
| EPG grabbers | 1.963 |
| EPG initialization | 4.702 |
| EPG inflate, within initialization | 0.755 |
| EPG binary message decode, within initialization | 0.220 |
| EPG object restoration, within initialization | 3.565 |
| EPG message destruction, within initialization | 0.108 |
| HTSP endpoint registration | below 1 ms |
| Initial HTSP metadata enqueue | 0.526 |
| Full initial metadata received and parsed by client | 4.707 |

The copied EPG expands to 110,281,811 bytes. Around 229,000 broadcasts remain
non-expired during these tests; the original reported 252,799 count is not the
current fixture. Existing expiration logic continues to apply as wall time passes.

GDB sampling of the main startup thread found repeated `htsmsg_field_find` /
`strcmp` calls in property loading and EPG restoration; inflate and settings-file
opens/metadata operations in input loading; sorted-array movement in bouquet
resolution; and a blocking `tv_find_grabbers` child read during XMLTV discovery.
EPG object restoration also reaches channel timer updates and timer-queue work.
Samples locate candidates, not precise exclusive CPU percentages. Cold ext4 input
and channel stages grow substantially, showing that cached-process CPU timings
alone do not characterize cold disk startup.

## Candidate and validation

The tested candidate rejects a field when its first byte differs before calling
`strcmp`. It preserves linear-search ordering and duplicate-key behavior. A native
regression test compares the real lookup against independent linear search for
10,000 probes, plus null arguments, empty/list field names, shared prefixes and
duplicate fields. AddressSanitizer and UndefinedBehaviorSanitizer checks pass.
A cache-hot lookup microbenchmark improved from 0.91–1.44 seconds to 0.34–0.66
seconds per 6.9 million representative probes. This is not an end-to-end startup
claim. The end-to-end results below are reported separately from the repeatable EPG-stage improvement.

Sorted full API snapshots match across the measured executables for 58,868 channels,
1,034 tags, 11 networks, 58,865 muxes, 58,868 services, 21 bouquets and 224,575
future EPG events. EPG snapshots include all exposed metadata for events whose stop
time exceeds one fixed cutoff an hour beyond the initial test time, so natural
expiration cannot masquerade as data loss. Runtime DVR/now-next fields are excluded
from hashes; stored identities, mappings and programme content are retained.

## Remaining work that needs design

- Input/channel cold loading reads many small configuration files and constructs
  objects serially. A persistent startup snapshot or parallel loader needs an
  explicit invalidation/recovery design and, if authoritative storage changes,
  migration. No RAM-only configuration or persistent-format shortcut was added.
- EPG restoration spends much more time constructing/updating objects than decoding
  messages. Deferring timers or batching inserts must preserve now/next, overlap,
  expiration, references and notification behavior; it is not a safe blind skip.
- Caching XMLTV discovery needs invalidation for PATH, executable/package changes
  and environment-dependent discovery. No discovery module was disabled.
- Bouquet sorted-set movement remains measurable, but replacing the structure or
  changing load order requires preserving intermediate mapping behavior.
- Server metadata enqueue and full client synchronization are distinct. Optimizing
  one does not demonstrate the same gain in the other.

## Tracing-disabled warm comparisons

| Pair | Baseline startup | Candidate startup | Baseline EPG parse/restore | Candidate EPG parse/restore |
| --- | ---: | ---: | ---: | ---: |
| 1 (candidate first) | 14.236 s | 15.122 s | 2.042 s | 1.449 s |
| 2 (baseline first) | 17.884 s | 13.452 s | 2.679 s | 1.766 s |

EPG parse/restore improves by 29% and 34% in these pairs, consistent with the
lookup samples and independent microbenchmark. Overall startup varies too much
to attribute an equivalent percentage improvement to this small change. Retaining
the lookup optimization is justified by the repeatable EPG-stage result and exact
lookup-equivalence tests, rather than a claim that cold startup is solved. The
instrumented per-message sub-stage timings include clock-reading overhead and
should not be compared directly with the tracing-disabled totals.

The tracing-disabled cold-file-data pair (playback closed) recorded 39.709 seconds
for the baseline and 33.039 seconds for the candidate. EPG parse/restore was
2.761 versus 2.618 seconds. This is one pair, with warm inode/directory caches;
it is an observation, not a repeatable 17% cold-boot guarantee. Cold startup
remains dominated by input/channel loading.

The first disk-backed baseline overlapped user playback and is excluded. The
earlier `/tmp`/tmpfs timing experiments are also excluded from disk conclusions.
Their data-equality checks remain useful, but their timings do not represent disk
startup. Source tests and source builds are performed from ordinary source trees;
no packaged binary is patched.

[Machine-readable measurements](cold-startup-measurements.json) retain the selected
valid runs and snapshot hashes. Packaged sources pin `f02aee227`, retained by tag
`tvhplayer-2026-11-13`. The published GitHub archive was verified file-for-file
against the clean archive used for the successful build.

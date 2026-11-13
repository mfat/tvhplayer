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
valid runs and snapshot hashes. Packaged sources now pin `576105975`, retained by tag
`tvhplayer-2026-11-13-2`, including the previously local idnode/settings changes. The published GitHub archive was verified file-for-file
against the clean archive used for the successful build.

## Continuation: descriptor-relative configuration loading

### Baseline audit

The continuation began with clean TVHplayer HEAD `018ddf06925afaefc43b9ee6396894a4533535c6`
and clean Tvheadend HEAD `57610597563a3f49ac1d132c4735cb0bee6d4364`.
`git ls-remote` reported TVHplayer's published `main` at `98dac3e277e28691fcac76f94cd61999cfa5803d`
and the fork's published `tvhplayer` at `57610597563a3f49ac1d132c4735cb0bee6d4364`.
The extra local TVHplayer commit updates documentation and packaging pins; it
contains no further startup implementation. All three current packaging pins
already select `576105975`, rather than the task's older `f02aee227` pin.

`cab97c72d` committed the previously local sorted-set insertion change, and
`576105975` committed the previously local settings-directory reuse change, with
their regression tests. Both are ancestors of the packaged revision. Historical
JSON's `candidate: f02aee227` is therefore an incomplete source label: those runs
also included the local idnode/settings changes described at the top of this
report. They were present in both sides of that comparison. They were not
reimplemented here. The sibling source checkout remains untouched.

The native IPTV scan queue, notification deduplication, bouquet mapping, HTSP tag
handling, field lookup and trace improvements were retained. TVHplayer's progressive
delivery, bounded batches, incremental model updates and direct built-in HTTP
playback were also retained. No Python/UI optimization or second channel cache
was added.

### Selected change and attribution limits

The last real-profile evidence still identifies IPTV initialization (7.748 s) as
the largest measured stage. Its loading chain is:

```text
iptv_network_init
  iptv_network_create0
    hts_settings_load_r(1, .../muxes)
      hts_settings_load_path / hts_settings_load_one
        fb_open2
    UUID-order mux construction
      iptv_network_load_mux / iptv_mux_create0
        mpegts_mux_create / idnode_load
        inline service restoration or separate service-directory loading
        mpegts_mux_post_create / scan queue preparation
```

The published directory-reuse change kept an `fb_dir` open, but direct
`fb_open2()` still formed a full pathname, called `tvh_fopen`, then resolved that
pathname again with `stat`. The new implementation opens the child relative to
`dirfd`, uses `fstat` on the opened file, and uses atomic `O_CLOEXEC` when
available. A locked close-on-exec fallback remains. This avoids repeated directory
prefix traversal and replaces the old `F_GETFD`/`F_SETFD` pair with an atomic
close-on-exec open on Linux. (`fdopen` can still check descriptor flags.)
The existing bundle branch, compression and settings formats are preserved.
The direct-open path also no longer truncates paths at 512 bytes.

Source paths are `src/filebundle.c:fb_open2`, `src/wrappers.c:tvh_openat`,
`src/tvheadend.h`, and `support/test-settings-load.py`. The candidate is stored as
an isolated local fork checkout under `packaging/tvheadend/work/startup-next`;
the exported patch linked below preserves it independently of ignored build work.
It is not applied by any packaging script.

The original disposable `.startup-profile/fixture` no longer exists. No live
configuration was copied or modified. Consequently, the new measurements isolate
filesystem loading, deserialization and message allocation; they do **not**
attribute time to mux/service object allocation, idnode registration, linkage,
notifications or scan queue work. Existing sampling remains the evidence for
those candidates. In particular, these numbers cannot be substituted into the
historical 7.748-second network stage.

### Validation and benchmark scope

Both pinned and candidate native executables were compiled from source with the
same configuration and compiler. The final candidate's server module also built
inside the installed KDE 6.11 Flatpak SDK with the manifest's Tvheadend flags,
including Linux DVB, SAT>IP and HDHomeRun support. Pinned local scan tables and
existing static HDHomeRun/libdvbcsa dependencies were supplied to that SDK build.
This checks the server module, not a complete new application bundle or release.

The expanded native loader regression runs against the real executable under
GDB, without continuing main. It covers JSON, gzip/binary settings, recursion,
plain/dangling/directory symlinks, ignored files, missing paths, empty directories,
bundled fallback, long paths, an open directory renamed before its child is read,
and close-on-exec. It passes on Linux and in the Flatpak SDK. Existing native
sorted-set and field-lookup tests pass in both environments; TVHplayer's six
packaging-pin tests pass. The SDK initially exposed missing libc debug types in
the test harness; explicit return-type casts fixed that test portability issue.

The isolated benchmark uses an ext4 fixture below ignored build work: 58,865
UUID-named mux directories, each containing one JSON `config` with enabled, URL,
mux name, scan result and an empty services map. GDB calls the real
`hts_settings_load_r(1, absolute_mux_directory)`. Timings include opening, reading,
decoding and allocating messages; they exclude fixture creation, destruction,
serialization and comparison. Each process makes three calls. Complete maps are
serialized and compared once per process using sorted JSON SHA-256. `/proc`
supplies resident memory and user/system CPU deltas for each timed call.
Runs are sequential in baseline/candidate, then candidate/baseline order.
File-data caches are left populated; there is no cache eviction or cold-boot claim.

| Pair order | Pinned loader | Candidate loader | Pinned CPU | Candidate CPU |
| --- | ---: | ---: | ---: | ---: |
| Baseline first | 7.411 s | 6.614 s | 7.410 s | 6.610 s |
| Candidate first | 7.447 s | 4.391 s | 7.440 s | 4.390 s |

CPU is the median of user + system time per call. Final loaded-map RSS is
47,040 KiB for the baseline and 46,848 KiB for the candidate; process high-water
marks also include the separately excluded serialization. All four complete maps
have SHA-256 `365b39911fb605f157108a0538f182a7d08d2db0f0b00e1738e145f0fd1e0c49`.
Both pairs favor the candidate, but its inter-process variability is substantial.
These observations do not establish a stable percentage improvement. The change
also removes demonstrably unnecessary pathname/descriptor work independently of
the measured magnitude. No cold-file-data trial was made for this candidate.

The earlier descriptor-relative prototype retained both close-on-exec `fcntl`
calls. Two five-call comparisons initially suggested 4–6% lower median wall time,
but a later CPU comparison did not consistently improve. That form was superseded
by atomic `O_CLOEXEC`; its measurements remain separately labelled in the JSON.
No SQLite prototype was attempted: without the real fixture, there is insufficient
new evidence that a storage migration would be the best remaining investment.

The stream smoke test uses a separate disposable, single-channel configuration
and a loopback MPEG-TS source. In both executables it verifies channel, service,
mux and tag identities, receives 188,000 bytes from the configured channel's HTTP
stream, identifies MPEG-2 video/MP2 audio, decodes three video frames, completes a
manual mux scan, shuts down cleanly and repeats after restart. The START notice, first
HTSP channel, initial synchronization, received stream bytes and decoded video
are recorded separately. These small-fixture observations establish functional
streaming, not a large-profile speedup or TVHplayer launch-to-playback result.
The old `first_channel_seconds` continues to mean metadata receipt only.

The real large-profile channel/mux/service/bouquet/tag/EPG API hashes were not
repeated. Large EPG restoration, now/next, overlap/expiration and DVR scheduling
remain unverified for this candidate. No related production code was changed.
Hardware DVB/HDHomeRun operation was not tested; their modules compile and DVB
scan tables load. WSL uses the same Linux APIs and needs no Windows host change,
but an actual Windows/WSL build and runtime test remain outstanding.

### Remaining opportunities, in priority order

| Work | Expected impact from existing evidence | Complexity / regression risk |
| --- | --- | --- |
| Recover the disposable real fixture; measure final network/channel stages and successful streaming | Establishes whether the loader saving affects the dominant 7.748 s stage and the 3.068 s channel stage | Low implementation risk; necessary before packaging |
| Separate remaining directory enumeration/opening from object/property loading on that fixture | Likely relevant to both input and channel cold startup; exact shares still unknown | Medium; retain filebundle fallback and existing formats |
| Overlap external XMLTV discovery with earlier native initialization, joining before module/config restoration | Up to the measured roughly 2 s discovery stage could overlap; unmeasured | Medium/high; preserve registration order, failure handling and all grabbers |
| Reduce redundant EPG timer queue reinsertions, then consider bulk restoration | Targets the 3.565 s object-restoration component rather than 0.220 s decoding | High; requires now/next, overlap, expiration, references and DVR tests |
| Bulk bouquet set construction where intermediate membership can be preserved | Targets part of the 1.153 s stage; binary search/memmove already implemented | Medium/high; `bouquet_add_service` consults sets and can map channels immediately |
| SQLite or another authoritative backend | Potential filesystem benefit remains unquantified after targeted work | High migration/recovery complexity; isolated comparison first |
| Further HTSP synchronization changes | Secondary until native startup improves and is remeasured | Avoid duplication; existing 0.526 s enqueue and client sync are distinct |

Channel loading already sets `channel_in_load` around creation and pairs slave EPG
afterward. Service and tag setters use the existing idnode mapping helpers;
blanket notification suppression would require checking their side effects.
EPG restore still calls `epg_broadcast_deserialize` and the ordinary broadcast
insertion logic. Its timer callback can expire/free events and inform DVR, while
`gtimer_arm_absn` removes and reinserts into a sorted queue. Blindly suppressing
callbacks would change intermediate semantics. XMLTV still invokes
`tv_find_grabbers` and falls back to PATH discovery; no incomplete cache or disabled
grabber was introduced.

Candidate source: `47207c8001b4e4cfa2ef39b9be3e09e00f175279`, local branch
`startup-descriptor-loading`. [Review/apply the fork patch](startup-optimization/0001-filebundle-directory-relative.patch).
The three production packaging pins remain at `576105975`; nothing was pushed,
published or approved for packaging. Exact binary hashes, individual samples,
superseded prototype results and stream-smoke observations are appended under
`descriptor_relative_continuation` in [the measurements JSON](cold-startup-measurements.json).

## SQLite experiment after recovering a real fixture

The previous missing-fixture limitation was resolved by copying the current
built-in configuration into ignored, disposable benchmark work. A before/after
size/mtime manifest found **zero changes during copying** across 127,571 files.
No test server used the live configuration. This is a new current fixture, not a
claim that the earlier deleted fixture was recovered byte-for-byte.

An actual SQLite database and native C reader were implemented in local fork
commit `79f13bdbf8642944a6fa629f266b651ffc5e788f`, based on `47207c800`.
[Experimental source patch](startup-optimization/0002-sqlite-startup-prototype.patch).
The database is retained locally at
`packaging/tvheadend/work/sqlite-investigation/settings-rowid.sqlite`. It contains
private configuration bytes and is deliberately excluded from Git.

### What the prototype measures

The importer retains relative paths, directory enumeration order and original file
bytes. A rowid table indexes paths and parent/order. `hts_settings_load_path` can
read those rows when `TVH_STARTUP_SQLITE` names the database. Both backends share
the existing JSON/gzip/binary decoder; no serialization format was replaced.
Native object allocation, property loading, registration, service/tag linkage,
scan queues, EPG restoration and HTSP synchronization still run normally.
Bundled defaults retain the existing filebundle fallback.

**This is a read-only startup experiment, not a completed production backend.**
Writes still go to the disposable file tree and do not update SQLite. Database
creation was separate from startup and took 52.327 s for the compact layout.
Normal-operation edits, transactional writes, migration, recovery and persistence
after those edits require further implementation and testing. No production
startup cache, packaging dependency or release pin was introduced.

The source payload totals 117,792,497 bytes. The compact database occupies
174,292,992 bytes including indexes. An initial WITHOUT ROWID layout occupied
372,015,104 bytes and produced one slower 30.312 s warm startup. It was retained
as an unsuccessful experiment, not selected. Other stages also varied in that
run, so the entire slowdown cannot be attributed to the table layout alone.

### Real-profile results

These are tracing-enabled, fresh-process measurements through the START notice,
using the existing benchmark and API verification method. Copy/import time is
excluded. Warm trials leave file-data caches populated. Each trial uses a fresh
copy, isolated loopback ports, the existing built-in server options, and clean
SIGTERM shutdown. No scan, grabber, EPG restoration or bouquet feature was disabled.

| Case | Native startup | CPU through START | RSS at START |
| --- | ---: | ---: | ---: |
| Packaged source `576105975`, warm control | 16.792 s | 15.32 s | 586,236 KiB |
| Descriptor-relative source `47207c800`, warm | 19.230 s | 17.34 s | 586,404 KiB |
| Prototype binary, file backend, warm | 19.261 s | 17.49 s | 586,688 KiB |
| Same prototype binary, compact SQLite, warm | 15.779 s | 14.06 s | 591,260 KiB |
| Prototype binary, file backend, cold file data | 24.511 s | 17.33 s | 586,424 KiB |
| Same prototype binary, compact SQLite, cold file data | 16.150 s | 14.17 s | 591,284 KiB |

The compact SQLite reader shows a useful startup benefit in these observations,
particularly the cold-file-data pair. The later packaged-source warm control is
closer to SQLite than the other file runs: the warm gain is not a stable 3.5-second
guarantee. These are a small number of sequential observations, not a statistical
performance guarantee. Resident memory increases by about 4.5–4.7 MiB.

Cold trials use `sync -f` followed by per-file `POSIX_FADV_DONTNEED` on the run
copy. The SQLite trial additionally flushes and evicts the SQLite file. Inode and
directory caches remain warm; **this is not cold OS boot**, and `/tmp` tmpfs was
not used for the data. The initial WITHOUT ROWID result is not mixed with the
compact-layout comparisons.

The cold input stage fell from 10.275 to 5.438 s and channel initialization from
6.975 to 1.819 s. Warm file/prototype input was 7.401 s versus 5.761 s for SQLite,
but the separate pinned warm control was already 5.429 s. Warm input improvement
alone is therefore not established consistently. Channel loading was 3.676–3.937 s
with files versus 1.823 s in the SQLite warm run. EPG and XMLTV were not optimized
and varied between processes; their timings remain in the raw records.

A same-process GDB check isolated the real settings loader from native object
construction. In files/SQLite/SQLite/files order, loading network/mux settings
took 3.378/1.633/1.629/2.086 s, and channel/tag settings took
1.080/0.326/0.183/0.299 s. It reused one binary and closed the database between
turns. This supports a read-path saving while also showing allocator/cache
variation. It does not explain the entire native input stage or remove the
remaining object/property/registration work.

All seven sorted API snapshots match across the pinned control, both file
variants, both database layouts and the cold trials: **58,868 channels, 1,034 tags,
11 networks, 58,865 muxes, 58,868 services, 21 bouquets and 191,044 future EPG
events**. EPG uses the same fixed future cutoff (`1794577619`) for all comparisons;
the total number of restored broadcasts declines naturally while tests run.
HTSP channel hashes and metadata counts also match. Full metadata synchronization
still takes roughly 3.8–5.1 s after connection; first channel metadata arrives
within roughly 16–21 ms of enabling metadata. Neither means successful playback.

### Tests, playback limitation and decision

The native executable builds against SQLite 3.46.1. The real-loader regression
passes with SQLite disabled and enabled, including compressed settings, symlinks,
recursion, exclusions, bundled fallback, empty/missing paths and long paths. The
importer checks database integrity, refuses replacement and creates private files
with mode 0600. Successful benchmark processes exit cleanly. SQLite-specific
Flatpak/Windows/WSL packaging and runtime compatibility were not tested; the
earlier descriptor-relative candidate's SDK checks remain historical results.

Playback was attempted on the same configured IPTV channel with both backends.
Neither produced a decodable video frame (FFmpeg exit 187 in both cases), although
both servers started and exited normally. The file-backend control therefore did
not supply a known-working playback case. **No launch-to-successful-stream gain is
claimed.** A currently working channel is still needed for that validation.

There is now measured evidence that SQLite can reduce the configuration-reading
portion of real large-profile startup. There is not yet evidence that a complete
authoritative migration, including its write/recovery complexity, is ready to ship.
Retain this experiment for designing that decision. Next work is transactional
write/delete/rename support, migration and recovery design, recording/EPG update
regressions, and a working-channel playback comparison. Native IPTV object work
and EPG restoration remain significant costs that changing storage does not remove.
The live configuration, published fork and all release pins remain unchanged.

Raw observations, import costs, API hashes, playback failures and the isolated
loader check are preserved under `sqlite_startup_experiment` in the measurements
JSON. Prototype build/use instructions are included in its source patch.

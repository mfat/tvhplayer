# Windows built-in server

Native Windows TVHplayer runs its built-in TVHeadend in an app-owned WSL container.
Remote servers remain usable without WSL. Complete Windows packages include the
offline image and expose Built-in Server before WSL is installed. Installing or
repairing WSL requires an explicit button click and a Windows elevation prompt;
the app never changes global WSL settings. Docker is a build-host tool only.

## Build and enable

On a Linux build host with Docker (or a compatible engine), run from the repository:

```sh
sh windows/backend/build-image.sh
```

This uses the existing TVHeadend source pins and checksum verification, builds
Linux FFmpeg into the image, and exports `dist/tvheadend.tar` and `manifest.json`.
The release bundle contains an immutable image ID, archive SHA256, exact TVHeadend
commit, Debian package/FFmpeg versions, SPDX package inventory, license archive,
and corresponding source. The Debian image digest and apt snapshots are pinned.
This pins inputs; it does not claim bit-for-bit reproducibility of timestamps and
build output. The source export includes exact Debian source versions plus the
TVHeadend, HDHomeRun and scan-table inputs and their build instructions.

Build and runtime stages fetch only binary package indexes. Source indexes are
added in the corresponding-source export stage, including the later snapshot
needed for packages inherited from the pinned base. APT retries transient archive
failures and rejects incomplete index updates, so missing security metadata cannot
silently change dependency resolution.

Windows build hosts can use the installed WSLc instead of Docker:

```powershell
.\.venv\Scripts\python.exe windows/backend/build-bundle.py --engine wslc.exe
```

If the build session's inherited DNS is broken, `--dns 1.1.1.1` explicitly sets
that temporary WSLc session's resolver before each build. It does not change
Windows adapter DNS or any application runtime setting.

For a Windows release build, set `TVHPLAYER_BACKEND_BUNDLE` to that output directory
before running `windows/build-windows.sh`. Both installer and ZIP receive the same
verified runtime files next to the EXE in `backend/`. Corresponding source is a
separate release asset. The installer copies the backend directory recursively
and preserves AppData and recordings on upgrades and uninstall. Windows CI resolves
a content-addressed backend artifact (see below), verifies it, and packages the same
bundle into both Windows release formats. No WSL setup is performed as an installer
side effect. The app never downloads a backend at runtime.

## Backend fingerprint and reusable CI artifacts

Backend identity is a SHA-256 fingerprint of the inputs that affect the image and
release bundle, plus a deliberate `BUILDER_POLICY` string
(`ubuntu-24.04-docker-v1` in `windows/backend/fingerprint.py`). Hashed inputs
include the Containerfile, apt snapshot config and sources, entrypoint,
`build-bundle.py`, `fingerprint.py`, `artifact_store.py`, and
`packaging/tvheadend` pins/scripts. Application UI or Windows packaging-only
changes do not change the fingerprint. Outputs are not hashed: SBOM UUIDs and
image export timestamps differ between builds.

Print the current fingerprint:

```sh
python windows/backend/ci_artifact.py fingerprint
```

Published backends are immutable GitHub prereleases tagged
`backend-<fingerprint>`. Each release holds the verified bundle
(`tvheadend.tar`, `manifest.json`, SBOM, licenses, corresponding source, and
`inputs.json`). Tags are never retagged or have assets replaced. They are not
marked as the repository's latest release. Retain them until an operator deletes
a tag that is no longer referenced by supported application releases; there is
no automatic garbage collection.

CI behavior (`backend-bundle.yml`, also called from `build-windows.yml`):

1. Compute the fingerprint.
2. If a matching `backend-<fingerprint>` release exists and rebuild was not
   forced, download it and run `verify-bundle.py`. Verification failure fails
   the job; CI does not fall back to another fingerprint.
3. On a miss, build with Docker on Ubuntu 24.04, verify, and publish the new
   tag when the workflow has write access (push/tag/same-repo PR or dispatch).
4. Fork PRs may build for testing but do not publish.
5. Concurrent publish races keep the first successful release; the loser adopts
   that immutable bundle unless `--force-rebuild` kept a local build for the run.

Explicit rebuild (does not overwrite an existing tag):

- Actions → **Backend bundle** → Run workflow → enable force rebuild, or
- Actions → **Windows build** → enable force backend rebuild.

Application releases reuse whatever backend fingerprint the tree currently
computes. Promote a backend change by merging input changes so CI publishes a
new `backend-<fingerprint>` tag, then cut a normal `v*` app release. If a
backend release is deleted or corrupted, restore it by running Backend bundle
with force rebuild on a commit that still produces that fingerprint, or bump
an input / `BUILDER_POLICY` to publish a new fingerprint and ship a new app
build that references it.

For a local portable-only build without Inno Setup, set
`TVHPLAYER_PORTABLE_ONLY=1`. `TVHPLAYER_BUILD_LABEL=wslc` uses separate
`windows/build-wslc` and `windows/dist-wslc` output directories, preserving other
development builds. Output paths are resolved and checked before generated files
are replaced. Release CI uses the normal installer-plus-ZIP build.

For development, put the bundle in `windows/backend/dist`. Complete schema-2 bundles
enable the backend automatically. Legacy development bundles can be enabled on
Windows with working WSL 2.9.3 or later:

```powershell
$env:TVHPLAYER_EXPERIMENTAL_WSLC = '1'
python -m tvhplayer.tvhplayer
```

On the prepared development checkout, `windows\run-dev.cmd` enables the backend
and uses `.venv` and the playback DLL in `windows/build`. The launcher requires
those dependencies to have been installed; it does not download them.

Select Built-in Server. First use verifies the archive, loads it offline if absent,
and starts a randomly named container with `--pull never`. The backend uses host
ports on `127.0.0.1`, generated credentials in the dedicated ACL-protected config
directory, and Linux paths `/config` and `/recordings`. Only absolute local-drive
folders without commas are supported. Stop the backend before changing recordings
folders. IPTV playlists use `/usr/bin/ffmpeg`. Tuner setup reads the backend's
hardware tree. If container broadcasts find no tuners, Windows performs a local
HDHomeRun discovery and configures directed discovery when exactly one device
responds. This can take about 20 seconds. Detecting both DVB-T frontends of the
development network's HDHomeRun has been verified; scanning and streaming through
the container still require hardware testing. USB passthrough is not configured.

Runtime operations run in a background thread. A per-config QLockFile rejects
duplicate windows. A persisted random name and owner label identify an orphan
after a crash; both must match before stopping or removing it. No global cleanup,
`wsl --shutdown`, or unrelated container removal is used. Stop waits for in-flight
operations to finish, then removes the owned container; shutdown waits at most
35 seconds. CLI operations are cancellable; cleanup ignores cancellation and uses
bounded stop/remove commands. Port collisions retry with new ports and identities.
If Windows kills the app before cleanup completes, verified orphan recovery occurs
on the next backend start. Missing orphan containers are handled safely. Before an
image change, config is backed up in the protected `backend-backups` directory;
recordings are outside that archive and are never removed. Existing playlist FFmpeg
wrappers are migrated idempotently to `/usr/bin/ffmpeg`.

If prerequisites are missing, the nonmodal setup dialog explains installation,
virtualization and restart requirements. Install/repair uses `wsl --install
--no-distribution`; update uses `wsl --update`. Only a user click invokes elevation.
Setup progress is persisted in `wslc-setup.json`; after a reboot, selecting Built-in
Server checks prerequisites and resumes provisioning. No reboot is forced. A
missing/corrupt image fails with a bundle diagnostic and leaves remote servers
available. Closing setup before installation cancels backend work.

## Validation and release gate

Run `python -m pytest tests/test_windows_wslc.py -q` for mocked adapter, ownership,
path, checksum, cancellation, network binding, and FFmpeg tests. These do not prove
actual WSLc networking or filesystem semantics.

The real-host test scripts exercise authenticated HTTP/HTSP media, DVR recording,
Unicode mounts, container restart, port collisions, duplicate windows and killed-UI
orphan recovery. See [VALIDATION.md](VALIDATION.md) for the checks that passed and
the fresh-machine/hardware release qualification still required. The image ID,
package versions and hashes for each build are recorded in its `manifest.json`.

CLI syntax was checked against the installed `wslc --help`, `run --help`,
`load --help`, `inspect --help`, and `stop --help`. Microsoft's API overview:
https://learn.microsoft.com/en-us/windows/wsl/wsl-container

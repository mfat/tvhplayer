# DVR backend API

`TvhBackend` is the Python API for TVHeadend recordings. `create_backend(server)` returns an HTTP or HTSP implementation. The desktop UI does not call the operations added here yet; schedule, list, and stop are the ones the window already uses.

Import the types from `tvhplayer.core`:

```python
from tvhplayer.core import (
    AutorecSpec,
    DvrEntryUpdate,
    TimerecSpec,
    create_backend,
)

backend = create_backend(server)
backend.cancel_dvr_entry(entry)
backend.update_dvr_entry(entry, DvrEntryUpdate(comment='Kept'))
backend.create_autorec_entry(AutorecSpec(title='News', days_of_week=0x1F))
backend.create_timerec_entry(TimerecSpec(title='Nightly', start=19 * 60, stop=20 * 60))
```

Both transports raise `TvhError` (or `TvhAuthError` / `TvhConnectionError`) when the server rejects the call. Recorder privilege is required for DVR changes. `notify_dvr_file_moved` requires admin.

## Entry actions

| Method | Effect | HTTP | HTSP |
|---|---|---|---|
| `create_dvr_entry` | Schedule or start one recording. Returns `None`. | `dvr/entry/create` | `addDvrEntry` |
| `create_dvr_entry_by_event` | Schedule from an EPG `event_id`. Optional `config_uuid`. Returns the server id, or `''` when the response has none. | `dvr/entry/create_by_event` | `addDvrEntry` with `eventId` and optional `configName` |
| `list_dvr_entries` | Upcoming, running, finished, and failed rows from the combined grid. | `dvr/entry/grid` | In-memory `dvrEntryAdd` / `dvrEntryUpdate` |
| `list_removed_dvr_entries` | Removed-recordings log. Empty when the server deletes the log with the file. | `dvr/entry/grid_removed` | Same path through the HTSP `api` proxy |
| `stop_dvr_entry` | Graceful stop of a running recording. The file is kept. | `dvr/entry/stop` | `stopDvrEntry` |
| `cancel_dvr_entry` | Drop a scheduled timer. A running recording is aborted, the file is kept, and the entry is classified as failed. | `dvr/entry/cancel` | `cancelDvrEntry` (the row stays in the database) |
| `remove_dvr_entry` | Delete a completed recording from storage. | `dvr/entry/remove` | Same HTTP path through `api` |
| `delete_dvr_entry` | Remove the database record. This does not promise to delete the media file. | `idnode/delete` | `deleteDvrEntry` |
| `set_dvr_rerecord(entry, action)` | `allow`, `deny`, or `toggle` for a finished or failed entry. | `dvr/entry/rerecord/<action>` | Same path through `api` |
| `set_dvr_prevrec(entry, action)` | `set`, `unset`, or `toggle`. Set marks the timer completed and flags the file deleted. Unset creates a new timer. | `dvr/entry/prevrec/<action>` with `uuid` | Same path through `api` |
| `update_dvr_entry` | Replace only the fields set on `DvrEntryUpdate`. | `idnode/save` | `updateDvrEntry` |
| `move_dvr_entry(entry, category)` | `finished` or `failed`. Reclassifies the row. The file stays where it is. | `dvr/entry/move/<category>` | Same path through `api` |
| `recording_url` | HTTP URL for VLC. Basic auth is embedded when credentials are set. | Entry `url`, or `dvrfile/<uuid>` | `getTicket` (`dvrId`); `ticket` is appended to the returned path |
| `open_recording` | `read` / `seek` / `stat` / `close`, also a context manager. | HTTP Range against the dvrfile URL | `fileOpen` `/dvrfile/<id>`, then `fileRead`, `fileSeek`, `fileStat`, `fileClose` |
| `get_dvr_cutpoints` | Cut, mute, scene, and commercial-break markers. | Raises `TvhError`. The JSON API does not document cutpoints. | `getDvrCutpoints` |
| `notify_dvr_file_moved(src, dst)` | Tell the server a file was relocated. Admin privilege. | `dvr/entry/filemoved` | Same path through `api` |

`stopDvrEntry` is the call this client already uses for a graceful stop. The published HTSP method list documents `cancelDvrEntry` as the cancel path and does not list `stopDvrEntry`.

The DVR reference does not list request parameters for `prevrec`. This client sends `uuid`, the parameter documented for cancel, remove, and rerecord.

Each call takes one entry. The server also accepts a JSON list of uuids on some of these paths; loop the Python method to change several rows.

## Playback

`recording_url` is the URL to hand to VLC. `open_recording` is for reading bytes:

* `read(size, offset=None)` is portable. `offset` is an absolute byte position. Omit it to continue after the previous read.
* HTTP `seek` uses a signed offset. `SEEK_END` with a negative offset moves backward from the end and needs a known `size`.
* HTSP `seek` forwards `offset` and `whence` to `fileSeek`. That offset is unsigned, and `SEEK_END` means backward from the end.
* `whence` is `SEEK_SET`, `SEEK_CUR`, or `SEEK_END`.
* An HTSP file handle is valid while the backend connection stays open. HTTP `size` comes from `HEAD` `Content-Length` and may be `None` when that request fails.

`DvrCutpoint.type` is `0` cut, `1` mute, `2` scene, `3` commercial break. `kind` is the matching name.

## Editing one recording

`DvrEntryUpdate` fields left as `None` are not sent.

| Field | HTTP `idnode/save` | HTSP `updateDvrEntry` |
|---|---|---|
| `start`, `stop` | Unix seconds | Unix seconds |
| `title`, `subtitle`, `description` | `{"eng": text}` | plain string |
| `comment` | `comment` | `comment` |
| `channel` | channel UUID | `channelId` |
| `start_extra`, `stop_extra` | stored as given | `startExtra` / `stopExtra`, documented as minutes |
| `retention` | `retention` | `retention` (days) |
| `priority` | `pri` | `priority` |
| `enabled` | JSON boolean | `1` / `0` |
| `config_name` | `config_name` | `configName` |

HTSP priority is `0` important, `1` high, `2` normal, `3` low, `4` unimportant, `5` not set. HTTP receives that same integer as `pri`. A stored grid value of `6` appears in server examples and is outside this list.

idnode save replaces the supplied fields. It does not merge a partial language map into an existing title.

## Series timers

`days_of_week` is the HTSP bitmask: Monday `0x01` through Sunday `0x40`. `0` means not set. HTTP `weekdays` is a list of `1`–`7` for the same days.

`start` and `start_window` are minutes from midnight. `priority` uses the scale above. `dup_detect` is sent only as HTSP `dupDetect`. `broadcast_type` is HTSP `broadcastType` and HTTP `btype`. `directory` is sent only on HTSP.

| Method | HTTP | HTSP |
|---|---|---|
| `list_autorec_entries` | `dvr/autorec/grid` | Same grid through `api` (no HTSP list RPC) |
| `create_autorec_entry` | `dvr/autorec/create` (`conf` JSON). `title` is required. | `addAutorecEntry` |
| `update_autorec_entry` | `idnode/save` | `updateAutorecEntry` when `htsp_id` is set, otherwise `idnode/save` through `api` |
| `delete_autorec_entry` | `idnode/delete`. Pending timers for the series are deleted with it. | `deleteAutorecEntry` when `htsp_id` is set, otherwise `idnode/delete` |
| `create_autorec_by_series` | `dvr/autorec/create_by_series` (`event_id`, optional `config_uuid`) | Same HTTP path through `api` |

Rows from the grid have a uuid and no HTSP id, so an HTSP connection updates and deletes those rows through the HTTP proxy. A timer created with `addAutorecEntry` returns an HTSP id; set `AutorecEntry.htsp_id` to that value to use the native update and delete RPCs. `updateAutorecEntry` has no documented `success` field; a reply that omits it is treated as success.

`list_dvr_configs` reads `dvr/config/grid` on both transports. HTSP `getDvrConfigs` only returns uuid, name, and comment, so the HTSP backend uses the HTTP grid and returns the same `DvrConfig` objects (`uuid`, `name`, `comment`, `storage`, `profile`, `enabled`, `raw`).

## Time-based timers

`TimerecSpec.start` and `stop` are minutes from midnight (`0`–`1439`). HTTP sends `HH:MM`. `title` is required to create.

| Method | HTTP | HTSP |
|---|---|---|
| `list_timerec_entries` | `dvr/timerec/grid` | Same grid through `api` |
| `create_timerec_entry` | `dvr/timerec/create` | `addTimerecEntry` |
| `update_timerec_entry` | `idnode/save` | `updateTimerecEntry` when `htsp_id` is set, otherwise `idnode/save` |
| `delete_timerec_entry` | `idnode/delete` | `deleteTimerecEntry` when `htsp_id` is set, otherwise `idnode/delete` |

`directory` is HTSP-only. Listed rows store `start_minute` and `stop_minute`. The string `Any` in a grid becomes `None`.

## HTSP `api` proxy

Paths above that say "through `api`" are the HTTP path without the `api/` prefix, sent as HTSP method `api` with `path` and `args`. The HTTP backend posts the same path under `api/`. Example: HTTP `POST api/dvr/entry/cancel` with `uuid`, HTSP `api` path `dvr/entry/cancel` with `args.uuid`.

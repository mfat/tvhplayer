# TVHeadend player backend

`TvhBackend` is the Python API a UI calls for live TV. `create_backend(server)` returns an HTTP or HTSP implementation of the same methods. Recordings, series timers, and time timers are documented in [dvr-backend.md](dvr-backend.md). This page is the rest of the player surface: channels, tags, the guide, stream profiles, images, and server status.

Playback is always an HTTP URL. mpv and ffmpeg do not demux HTSP `muxpkt`, so neither backend subscribes to the HTSP stream. Pass `stream_url` or `image_url` to the player as returned. Both already contain basic auth when the server config has a username or password.

```python
from tvhplayer.core import (
    Channel,
    EpgQuery,
    create_backend,
)

backend = create_backend({
    'name': 'Living room',
    'url': 'http://127.0.0.1:9981',
    'username': 'user',
    'password': 'secret',
    'protocol': 'htsp',  # or 'http'
    'htsp_port': 9982,
})
try:
    for channel in backend.get_channels():
        now = backend.get_epg(channel, limit=1)
        play = backend.stream_url(channel, profile='pass')
finally:
    backend.close()
```

A failed call raises `TvhError`. Authentication and connection failures are `TvhAuthError` and `TvhConnectionError`. HTTP accepts a Basic header on the first request and retries with digest when the server challenges, which is the same pair `tvh-json.py` installs. HTSP answers the SHA-1 challenge the way Kodi's HTSP client does.

The HTTP URL is the API base, including a webroot path when the server is not mounted at `/`. HTSP uses that URL's host and `htsp_port` (default 9982). `hello` also reports a webroot; image and stream URLs add it only when the HTTP base does not already end with it.

## Channels and tags

`get_channels` returns `Channel` rows sorted by number, then name. A number of `0` sorts last.

| Field | HTTP `channel/grid` | HTSP `channelAdd` |
|---|---|---|
| `uuid` | `uuid` | `channelIdStr` |
| `name` | `name` | `channelName` |
| `number` | `number` | `channelNumber` |
| `number_minor` | `number_minor` | `channelNumberMinor` |
| `icon` | `icon` | `channelIcon` |
| `tag_ids` | tag uuids | decimal `tagId` values |
| `htsp_id` | absent | `channelId` |
| `enabled` | `enabled`, default true | default true |

`list_channel_tags` returns `ChannelTag` rows sorted by `index`, then name. HTTP reads `api/channeltag/grid`. HTSP stores `tagAdd`, `tagUpdate`, and `tagDelete` while `enableAsyncMetadata` syncs. That sync still requests `epg: 0`, so the socket does not download the whole guide.

Match a channel to a tag like this: HTTP `Channel.tag_ids` equals `ChannelTag.uuid`. HTSP `Channel.tag_ids` equals `str(ChannelTag.htsp_id)`. `ChannelTag.member_ids` is the same kind of identifier in the other direction (channel uuid or decimal channel id).

`Channel.to_raw()` is the dict stored on the channel table. It keeps the server payload and overlays `uuid`, `name`, `number`, and the fields above when they are set.

## Guide

Times are Unix seconds. `genre` values are ETSI EN 300 468 content nibbles. `list_content_types()` returns those ids and their names from `epg/content_type/list` (`key` 0 is the empty type). HTSP loads that list through the `api` proxy.

`EpgQuery` leaves a field unsent when it is `None`. `get_epg(channel, limit=24)` is `query_epg(EpgQuery(channel=channel, limit=limit))`.

| `EpgQuery` | HTTP `epg/events/grid` | HTSP |
|---|---|---|
| `title` | `title` | `epgQuery` `query` |
| `fulltext` | `fulltext=1` for an exact title | no equivalent; the HTTP grid is used |
| `channel` | `channel` uuid | `channelId` when `htsp_id` is set |
| `channel_tag` | `channelTag` uuid | `tagId` when `htsp_id` is set |
| `content_type` | `contentType` | `contentType` |
| `duration_min`, `duration_max` | `durationMin`, `durationMax` (seconds) | `minduration`, `maxduration` |
| `mode` | `now` | no equivalent; the HTTP grid is used |
| `limit` | `limit` | applied to the returned list |
| `offset` | `start` (row offset, not a programme time) | no equivalent; the HTTP grid is used |
| `lang` | `lang` | `language` |

HTSP picks one call:

* `getEvents` when the query is only a channel (and a limit). `maxTime` is `limit` hours ahead, and the list is then cut to `limit`.
* `epgQuery` with `full=1` when a title is set and any channel or tag filter has an HTSP id. Tag, content type, duration, and language ride on that call.
* The HTTP grid through `api` for an exact title, `mode`, a non-zero offset, a channel or tag that has no HTSP id, or a tag, genre, or duration filter that has no title. `epgQuery` requires a query string, so a tag with no title uses the grid.

`get_event(event_id)` is HTTP `epg/events/load` and HTSP `getEvent`. It raises `TvhError` when the server returns no programme.

`list_related_events` is `epg/events/related` (same series link). `list_alternative_events` is `epg/events/alternative` (same event on another broadcast). HTSP has no native RPC for either, so both go through `api`. Servers older than 4.2.4-5 or 4.3-589 do not implement them; the error surfaces as `TvhError`.

`EpgEvent.description` is the long text, or `summary` when the long text is empty. `summary` stays the short text only. A language map such as `{"eng": "News"}` becomes the first filled string. Image fields (`image`, `image_poster`, `image_backdrop`, `image_still`, `rating_label_icon`) are references like `imagecache/38`, not bytes. `dvr_uuid` and `dvr_state` are set when that broadcast is already scheduled. `dvr_state` is `scheduled`, `recording`, `completed`, `completedError`, `completedWarning`, or `completedRerecord`.

An omitted `limit` is not sent by `EpgQuery`. The grid helper then uses the same cap as the other list calls, 10000 rows. `get_epg` always sends the limit you pass.

## Profiles, streams, and images

`list_profiles` is HTTP `api/profile/list` and HTSP `getProfiles`. A profile row is `uuid`, `name`, and `comment`. The HTTP list is sometimes `{key, val}` instead of a full object; `key` is the uuid and `val` is the name.

`stream_url(channel, profile=None)`:

* HTTP: `/stream/channel/{uuid}`
* HTSP: `/stream/channelid/{htsp_id}`

`profile` is appended as `?profile=` using the profile name (`pass`, `matroska`, or a name from `list_profiles`). Omit it to take the server default. HTSP raises `TvhError` when the channel has no numeric id.

`image_url(reference)` joins `imagecache/38` or a channel icon onto the HTTP base and embeds basic auth. An absolute `http://` or `https://` URL is returned unchanged, with no credentials added. `''` returns `''`.

## Status

These calls need the admin privilege on the server. HTSP reads them through `api`. Each object keeps the original row on `raw`, and `.get(key, default)` reads that row, so existing signal and stream tables can keep using `input`, `signal`, `peer`, `started`, and `channel`.

| Method | Path | Typed fields |
|---|---|---|
| `get_inputs` | `status/inputs` | `name` (JSON `input`), `signal`, `signal_scale`, `snr`, `snr_scale`, `stream`, `weight` |
| `get_connections` | `status/connections` | `peer`, `user`, `started`, `kind` (JSON `type`) |
| `get_subscriptions` | `status/subscriptions` | `channel`, `username`, `state`, `start` |
| `get_activity` | `status/activity` | `current_time`, `next_activity`, `activities`, `subscription_count`, `connection_count` |

`signal_scale` and `snr_scale` are `1` when 65535 means 100%, `2` when 1000 means 1 dB, and `0` when the reading is not valid. Signal and SNR are often zero while the tuner is idle.

`SubscriptionStatus.channel` is a display string. `.get('channel')` still returns the original value when that value is a dict.

`get_activity` needs Tvheadend 4.3-2405 or later. Times are Unix seconds. `0` means that activity has nothing scheduled. `activities` uses the keys the server sends: `dvr`, `ota_grabber`, `int_grabber`, and `mux_scheduler`. A DVR time in the past means a recording is already running. The counts match `status/subscriptions` and `status/connections`.

## Recordings

Schedule, stop, cancel, series timers, time timers, cutpoints, and recording files are the methods on the same object. See [dvr-backend.md](dvr-backend.md). `create_dvr_entry_by_event(event.event_id)` schedules the programme `get_event` or `query_epg` returned.

## What this library does not call

Networks, muxes, services, users, access entries, and `raw/export` are server administration. HTSP `subscribe` and `muxpkt` are not used for playback.

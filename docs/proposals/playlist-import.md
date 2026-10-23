# Proposal: Playlist Import

- **Status:** Proposed
- **Date:** October 2026

## What this is

The user picks an M3U or M3U8 playlist, from a web address or a local file, and TVHplayer turns its entries into channels on a Tvheadend server. The built-in server is the default target. A user who has added other servers can pick one of those instead.

An imported playlist is a **playlist source**. TVHplayer remembers it, so the user can refresh it later. A refresh updates the channels in place: renamed, renumbered, and moved streams keep their channel, new entries are added, and removed entries go away.

## Why the app does the work

Tvheadend has its own playlist importer, the *IPTV Automatic Network*. TVHplayer does not use it. The app reads the playlist itself and writes plain IPTV muxes through the JSON API. Research on the pinned Tvheadend commit (`51ec612fa`), its forum, and its issue tracker found these problems with the built-in importer:

| Problem with the automatic network | What the app does instead |
| :--- | :--- |
| A stream whose address changes is deleted and created again. Its channel is lost, along with recordings links and guide mapping. Providers that rotate tokens do this daily. | The app matches entries to muxes by a stable key and edits the address in place. A test confirmed the channel uuid stays the same. |
| Every re-fetch overwrites name, number, icon, guide id, tags, and headers. Hand edits on the server are lost. | Same behaviour for fields the playlist sets, but the app decides which fields it owns. |
| Its parser takes any line without `#` as a stream. Telewebion's master playlist has `EXT-X-VERSION:6` without `#`, so native HLS requests `…/EXT-X-VERSION:6` and fails with 403. | Entries the app cannot trust Tvheadend to read go through ffmpeg. |
| It reads only `#EXTVLCOPT:program`, `\|key=value` headers on http lines, and `\|`-separated tags. Real playlists use Kodi conventions: `#EXTVLCOPT:http-user-agent`, `http-referrer`, `#EXTGRP`, `;`-separated `group-title`, `x-tvg-url`. | The app parses the Kodi IPTV Simple syntax and converts it. |
| `file://` and `pipe://` playlist addresses are read on the server. | The app reads the playlist on this machine, so a local file works for a remote server too. |
| It scans every stream after import. Forum users report 5,000 entries taking 7–8 hours and providers banning their IP. | Networks are created with *Service ID* = 1. Each mux gets its service immediately and nothing is tuned until someone watches. Tested: channels appeared instantly and played. |
| Created through the API, it re-fetches every minute (`refetch_period` 0) and waits 0 s for data (`max_timeout` 0). | The app sets every network field it relies on. |

## Choosing the server

The import dialog has a **Server** list. It shows the built-in server first and preselects it. The user's other servers follow, in the order of the server list.

- **Built-in server.** TVHplayer holds its admin login. If the server is not running, the import starts it and waits for the ready signal the supervisor already gives. The built-in server keeps starting and stopping with the app; the import does not change its lifetime.
- **Other servers.** Changing networks and muxes needs the admin privilege. Before writing anything, the app calls `api/mpegts/network/grid`. A 401 or 403 stops the import with the administrator message in the error table below.
- **HTSP servers.** Admin calls always use the HTTP JSON API at the server's address, whichever protocol the server entry uses for viewing.
- **Platforms without the built-in server** (macOS and Windows today) show only the user's servers. With none configured, the menu item explains that a server is needed.

Streams received through ffmpeg run ffmpeg **on the target server**. For the built-in server the app knows which ffmpeg that is: it looks it up on the PATH the child inherits (`/app/bin/ffmpeg` in Flatpak, `/usr/bin/ffmpeg` from the deb and rpm). For another server the app cannot check, so it uses `/usr/bin/ffmpeg`, where distro packages and the common Docker images install it. An absolute path avoids a Tvheadend lookup quirk where a bare `ffmpeg` can run `ffmpegthumbnailer` (issue 1632).

## User flow

The user imports a playlist and it works. The dialogs use no Tvheadend or streaming terms: no muxes, networks, ffmpeg, HLS, or connection limits. Every technical choice in this document is made by the app.

1. **File → Import Playlist…** opens one small dialog:
   - **Playlist:** a text field for a web address, plus **Browse…** for a file.
   - **Add channels to:** the server list, with the built-in server preselected. The list is hidden when the built-in server is the only server.
   - **Import**.
2. The import runs in the background. The dialog shows "Adding channels…" with a progress bar and **Cancel**.
3. It ends with one sentence, such as "Added 120 channels from Kodinerds." or "Updated the channels from Kodinerds: 3 added, 2 removed.". If some entries could not be added, a second sentence says how many, with a **Details** button that lists the names.
4. When the target is the current server, the channel list reloads. When it is another server, the message offers **Show channels**, which switches to that server.

The playlist's name comes from the file name or the web address's host. A source whose address is already imported to that server is refreshed instead of added twice.

**File → Playlists…** lists the imported playlists with **Refresh** and **Remove**:
- **Remove** asks "Remove the channels from <name>?" and then deletes the network. Its muxes, services, channels, and bouquet go with it, which a test confirmed. The app then deletes the leftover `*** <name>` network tag, which Tvheadend leaves behind.
- Playlists imported to the built-in server refresh by themselves when TVHplayer starts. Since the built-in server runs only while the app runs, Tvheadend's own timers are not used.

Plain-language errors:

| Situation | Message |
| :--- | :--- |
| Download failed | "Could not download the playlist. Check the address and your internet connection." |
| Not a playlist | "This file is not a TV playlist." |
| No usable entries | "This playlist has no channels TVHplayer can add." |
| Server account is not an admin | "This account cannot add channels to <server>. Sign in with an administrator account in Manage Servers." |
| Server unreachable | The same connection message the channel list already shows. |

Settings the user never sees:
- **Connection limit:** 2, enough to watch one channel while recording another.
- **ffmpeg location:** found automatically for the built-in server; `/usr/bin/ffmpeg` on other servers.
- **How streams are received:** always through ffmpeg, as described below.

## How each entry is received

Every entry is received through an ffmpeg command that TVHplayer builds. The user is not asked.

A single path keeps import fast and makes every channel behave the same:

- **Program number.** The network creates each service without scanning (*Service ID* = 1), and that service only plays a stream whose program number is 1. A test showed a stream with program 1234 delivering no picture. ffmpeg's output always carries program 1 (`-mpegts_service_id 1`), whatever the source used.
- **Reconnects.** Tvheadend does not reconnect when an HTTP stream drops, so recordings end early without being marked failed. Forum threads from 2017 to October 2026 converge on ffmpeg with reconnect options.
- **Formats.** Tvheadend's HLS reader fails on malformed master playlists (Telewebion) and cannot join separate audio renditions (ZDF). RTSP, RTMP, and DASH are not Tvheadend inputs at all (issue 2005). ffmpeg reads all of these.

The cost is one ffmpeg process per stream being watched or recorded. Nothing runs while a channel is idle.

| Entry address | What the app does |
| :--- | :--- |
| `http(s)://`, `udp://`, `rtp://`, `rtsp://`, `rtmp://`, and other ffmpeg inputs | Builds an ffmpeg command for it. `\|` headers and `#EXTVLCOPT` headers become ffmpeg options. |
| `pipe://ffmpeg … -i URL …` | Playlists made for Tvheadend, such as kodinerds-iptv, wrap every stream this way. The app takes the input address and any `-headers`, `-user_agent`, or `-referer` from the command and builds its own command. The playlist's other options are dropped, so nothing from the playlist runs as given. |
| any other `pipe://` command | One question before the import: "This playlist wants to run 3 programs on <server>. Only allow this if you trust where the playlist came from." **Allow** or **Skip them**. An allowed command runs as `/bin/sh -c 'COMMAND \| FFMPEG -i pipe:0 … pipe:1'`, so its output also carries program 1. |
| `file://` | Skipped. It names a file on whichever machine runs Tvheadend. |

The built-in server always has ffmpeg: the Flatpak builds it, and the deb and rpm depend on it. If the app cannot find it anyway, the import stops with "TVHplayer could not find ffmpeg, which it needs to play imported channels."

### The ffmpeg command

`core/playlist.py` builds the command. Tvheadend splits it without a shell, honouring `"…"`, `'…'`, and backslash escapes. The builder quotes every value and escapes `"` and `\`. A test runs a Python copy of `spawn_parse_args` on the built command and checks that the argument list comes back unchanged.

```
pipe://FFMPEG -nostdin -hide_banner -loglevel error
  [-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 -reconnect_delay_max 5]
  [-user_agent "UA"] [-headers "Referer: R\r\n"]
  -i "URL" -c copy
  -metadata service_name="NAME" -metadata service_provider="PLAYLIST"
  -mpegts_service_id 1 -f mpegts -mpegts_flags resend_headers pipe:1
```

- No `-map 0`. On an HLS master it would copy every variant. ffmpeg's default picks the best video and audio, the same as the user's current Telewebion command.
- The service name and provider are set inside the stream, as the kodinerds-iptv playlist does.
- The reconnect options are added for `http(s)` inputs only. They exist in FFmpeg 4.3 and later; the Flatpak builds 4.4.5.
- Tvheadend stored a 759-character command intact in a test.

## What is written to the server

One **IPTV Network** (`iptv_network`, not the automatic one) per playlist source:

| Field | Value | Reason |
| :--- | :--- | :--- |
| `networkname` | source name | Shown in Tvheadend's UI. |
| `service_sid` | 1 | Creates the service without scanning. |
| `scan_create`, `skipinitscan`, `idlescan` | off, on, off | No tuning until someone watches. |
| `max_streams` | connection limit | Provider limit. |
| `max_timeout` | 15 | The web UI default; the API default is 0. |
| `bouquet` | on | Channels are created and kept in sync by a bouquet. |
| `epgauto_default` | on | New channels auto-map guide data by `tvg-id`. |

The network's bouquet is enabled with *Map to channels* and the options *Map zero-numbered channels*, *Map radio channels*, and *Map encrypted services*. Without zero-numbered mapping, entries with no channel number are skipped. A test confirmed renames, renumbers, and removals carry through to channels.

One **mux** per included entry:

| Mux field | From the playlist |
| :--- | :--- |
| `iptv_url` | the built ffmpeg command |
| `iptv_sname`, `iptv_muxname` | entry name |
| `channel_number` | `tvh-chnum`, `tvg-chno`, or `channel-number` |
| `iptv_icon` | `tvg-logo` |
| `iptv_epgid` | `tvg-id` |
| `iptv_tags` | groups from `group-title` (split on `;` and `\|`) and `#EXTGRP`, one per line |
| `epg` | 0 |

`epg` 0 turns off over-the-air guide grabbing for the mux. With the default on, Tvheadend re-tunes every watched IPTV stream at 02:04 and 14:04 for up to 10 minutes (issue 1925).

Updates are sent in batches: `api/idnode/save` accepts a list of nodes, which a test confirmed. New muxes need one `api/mpegts/network/mux_create` call each.

## Matching entries on refresh

Each entry gets a key: `tvg-id` when it is present and unique in the playlist, otherwise the entry name, with a ` #2`, ` #3` suffix for repeats. The source remembers key → mux uuid.

On refresh:
- known keys update their mux, including a changed address;
- new keys create muxes;
- keys missing from the playlist delete their mux and so their channel;
- a mux uuid that no longer exists on the server is created again.

The map is saved after every batch, so a cancelled import leaves the remembered state matching the server.

A refresh never deletes anything when the download fails or the playlist parses to zero entries.

## Playlist parsing

`core/playlist.py`, with no Qt imports, reads:

- `#EXTM3U` header attributes: `x-tvg-url`, `url-tvg`;
- `#EXTINF` duration, attributes, and the name after the last unquoted comma;
- `#EXTGRP`, `#EXTVLCOPT:http-user-agent`, `http-referrer`, `program`;
- `URL|key=value&key=value` headers, keys case-insensitive, with a `!` prefix accepted and stripped.

It ignores `#KODIPROP`, catch-up attributes, and `tvg-shift`.

- **Encoding:** UTF-8, with an optional BOM, falling back to Latin-1.
- **Line endings:** CRLF accepted.
- **Downloads:** go through `proxy.configure_session`, follow redirects, and stop at 50 MB.
- **Errors:** a file that does not start with `#EXTM3U`, or that has no entries, is reported as *"This file is not an M3U playlist."*

## Guide data

When the playlist header names an XMLTV address, the app loads that guide without asking.

- **Built-in server.** TVHplayer downloads the guide (gzip accepted) on import, on refresh, and on start when refresh-on-start is on. It enables Tvheadend's *External: XMLTV* module and writes the file to `<config>/epggrab/xmltv.sock`. Channels match by `tvg-id` through `epgauto_default`.
- **Other servers.** The socket is on that machine, so the app cannot write to it. The option is shown only when the server already lists an *XMLTV URL grabber* module (a `tv_grab_url` script, as TVH-IPTV-Config ships). The app then sets that module's arguments to the address.

## Code layout

| Piece | Where | Qt |
| :--- | :--- | :--- |
| Parser, entry plan, ffmpeg command builder | `tvhplayer/core/playlist.py` | no |
| Admin API calls: network, mux, bouquet, tag, epggrab | `tvhplayer/core/tvh_admin.py`, a small client on `requests` that reuses `urls.http_auth` and `proxy.configure_session` | no |
| Sync: diff, batches, progress callback, cancel flag | `tvhplayer/core/playlist_sync.py` | no |
| Saved sources | `playlists` list in `tvhplayer.conf`, normalised in `core/config.py`; each source names its server by `builtin` or by URL | no |
| Import dialog, progress, Playlists dialog | `tvhplayer/playlist_dialogs.py` | yes |
| Background run | a `QThread` worker that calls the sync and emits progress | yes |

`docs/backend.md` says the backend library does not call network or mux APIs. That stays true: admin calls live in `tvh_admin.py`, not on `TvhBackend`.

## Tests

- **Parser** fixtures: Kodi syntax, `#EXTGRP`, `#EXTVLCOPT`, `|` headers, BOM, CRLF, a name containing commas, quoted attributes, missing names, duplicate names.
- **Planner:** every row of the receiving table.
- **Command builder:** quoting round-trip through a Python port of Tvheadend's `spawn_parse_args`.
- **Sync** against a fake admin client: add, update, address change, removal, cancel mid-batch, failed download, empty playlist, vanished mux uuid.
- **Integration**, skipped when no Tvheadend binary is found:
  1. Start a throwaway server like the built-in one.
  2. Import a playlist whose single entry is `pipe://ffmpeg -f lavfi -i testsrc … -f mpegts pipe:1`. It needs no network.
  3. Check that a channel exists and that `/stream/channel/<uuid>` returns MPEG-TS.

## Phases

Each phase is one commit with its tests.

1. Parser, planner, and command builder.
2. Admin client and sync, with the integration test.
3. Import dialog, for the built-in server and other servers.
4. Playlists dialog: refresh, remove, and refresh on start.
5. Guide data from `x-tvg-url`.

## Out of scope

- Catch-up and archive playback.
- Failover between several sources of one channel.
- Picon generation.
- Tvheadend's *Use A/V library* option, which the built-in build does not include.
- Choosing individual channels or groups before importing. Unwanted channels can be disabled on the server afterwards.

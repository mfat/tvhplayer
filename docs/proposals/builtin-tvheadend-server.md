# Proposal: Built-in Tvheadend Server

- **Status:** Proposed
- **Replaces:** `docs/proposals/local-tvheadend-server.md` in commit `6fb3742` on `testing`
- **Date:** October 2026

This document replaces that proposal. The earlier text used one name for three different things. This text keeps them apart.

## What this is

A **built-in server** is a Tvheadend process that TVHplayer ships and fully owns. The app starts it, watches that child, restarts it, and stops it. The binary, config directory, log stream, HTTP port, and HTSP port belong to the app.

A **local instance** is a Tvheadend the user already runs on this machine: a distro package, a systemd service, or a build they made themselves. TVHplayer stores its URL and connects, the same way it connects to any other server. The address field already accepts `http://127.0.0.1:9981`. Quitting TVHplayer leaves that process alone.

The built-in server is listed with the other servers. It is one permanent entry, marked as built-in. Choosing it connects to the child this app owns, on the port the app assigned. A user-added server that points at `127.0.0.1:9981` is still a local instance.

## Ownership

TVHplayer is the only manager of the built-in server.

| Piece | Rule |
| :--- | :--- |
| Binary | The `tvheadend` built into that package. Flatpak uses `/app/bin/tvheadend`. Native Linux and the macOS `.app` carry their own binary beside the app. |
| Process | A child of TVHplayer, supervised with `QProcess`. The app does not adopt a Tvheadend it found already listening. |
| Config | `-c` points at a directory the app created for this server. Tvheadend creates the files inside it. |
| Logs | The child's stderr, read by `QProcess`. |
| Ports | Chosen and remembered by the app. 9981 and 9982 are not required. |
| Lifecycle | Start, ready, restart, and stop act on that child only. Quit stops it. Recordings that child is writing stop with it. |

The supervisor lives in the app on native Linux, macOS, and inside Flatpak. A systemd unit is not the manager. `systemctl --user` would start the user's service, and inside Flatpak it would leave the sandbox.

There is no user-facing binary picker and no `$PATH` search. A development build may point the supervisor at a `tvheadend` the developer compiled. That hook is not the built-in server users get.

User-added servers stay ordinary connections. The built-in entry is app state that is also shown in the server list. Its start, stop, restart, and status controls act on the child. The user cannot retarget that entry at another host, edit its URL, or remove it.

## Platforms

The same ownership rules apply to every package in this pass. Windows is out of scope. The Windows app keeps connecting to servers the user configures.

- **Flatpak.** A module in `io.github.mfat.tvhplayer.yml` builds `tvheadend` and installs it at `/app/bin/tvheadend`. The running app uses that binary. A Tvheadend installed on the host is a local instance. The sandbox does not spawn it. The manifest already sets `--share=network`, so `127.0.0.1` is the host loopback and a port already taken on the host is taken for this process too. `--device=all` exposes `/dev/dvb` and `/dev/dri`. Membership in `video` and `render` is still decided on the host. The built-in process runs as the user who launched TVHplayer.
- **Native Linux.** The package carries its own `tvheadend` next to the app. `/dev/dvb` is an input when that user can open the device. The server process still starts when no tuner is present.
- **macOS.** Tvheadend's `configure` has a Darwin path and turns LinuxDVB off there. The `.app` contains a Darwin `tvheadend`. This package has no local DVB device nodes. IPTV, SAT>IP, and HDHomeRun are the inputs it can offer.

Start, stop, the ready check, and the loopback bind are the same on all three. Local tuner hardware is a Linux input. It is not a gate on whether the built-in server runs.

Each package compiles its own `tvheadend` with `--enable-bundle`. That switch embeds the web UI and DVB scan tables into the binary through Tvheadend's file bundle. It does not start a server, and it does not by itself make Tvheadend part of TVHplayer. The packages need it so the binary can serve its UI and scan files without `/usr/share/tvheadend`.

The Flatpak module in `io.github.mfat.tvhplayer.yml` has to satisfy `./configure` inside the build sandbox:

- OpenSSL is a hard dependency. zlib and libpcre2 are auto-detected; the KDE SDK is expected to provide them, and the module must add them if `pkg-config` does not find them.
- `--enable-bundle` with zlib requires Python 3's `gzip` module. pngquant stays off (`pngquant` defaults to no) and is not a required package.
- bzip2 is a warning when missing, not a failed configure.
- `support/getmuxlist` clones `https://github.com/tvheadend/dtv-scan-tables.git` into `data/dvb-scan` during `./configure` when that directory is absent. The Flatpak build must supply that tree as a `git` or `archive` source before configure. Configure must not be the step that clones it.

## Config directory

`-c` is `<app config directory>/tvheadend`. The app config directory comes from `tvhplayer.core.config.default_config_dir()`:

- Linux, including Flatpak: `$XDG_CONFIG_HOME/tvhplayer`, or `~/.config/tvhplayer`. Inside Flatpak the manifest does not grant the host home, so this path is the app's sandbox config.
- macOS: `~/Library/Application Support/TVHplayer/tvheadend`.

The app creates that directory and passes `-c`. It does not create Tvheadend's internal tree. Tvheadend writes its own files there, including `config`, `accesscontrol`, `channel/config`, `channel/tag`, `dvr/config`, and `input`.

Without `-c`, Tvheadend picks `/var/lib/tvheadend` or `/etc/tvheadend` when that directory is owned by the current user, otherwise `~/.hts/tvheadend` if it exists, otherwise `$XDG_CONFIG_HOME/hts` or `~/.config/hts`. Those locations belong to a Tvheadend the user installed. The built-in server never uses them.

`tvhplayer.conf` stays the client settings file beside that directory. It remembers whether the built-in server should start with the app, and which HTTP and HTSP ports the last successful child bound.

## Command

Tvheadend stays in the foreground. Forking is off unless `-f` / `--fork` is passed, so the steady-state command omits `-f`. `QProcess` is then the parent of the daemon.

```bash
tvheadend \
  -c "<app-config>/tvheadend" \
  -B \
  --bindaddr 127.0.0.1 \
  --noacl \
  --http_port <http-port> \
  --htsp_port <htsp-port>
```

- `-c` selects the app-owned config directory.
- `-B` / `--nobackup` skips the config-tree backup Tvheadend would write on upgrade.
- `--bindaddr 127.0.0.1` is required on every start. This is what keeps the socket on loopback.
- `--noacl` disables every access check for every client that can reach the socket. It does not mean "allow localhost." It is passed only together with `--bindaddr 127.0.0.1`. Any other process on the machine that can connect to that loopback port can call the API. The UI says that plainly. If the child does not hold the listen socket, the supervisor stops it. A `--noacl` process must not remain up after a failed bind.
- `--http_port` and `--htsp_port` are the ports the app chose for this child.
- `-C` / `--firstrun` is not used. When the access list is empty it writes one enabled admin entry with an empty username. Tvheadend warns that this entry is wide-open administration until access control is edited. `--noacl` would ignore that entry anyway.
- `--logfile` is not used. Passing it turns debug on for every subsystem and adds a debug file. It is not a normal log path.
- `--nostderr` is not used. The in-app log is the child's stderr via `QProcess`. `--nostderr` would make that stream empty.
- `--pid` is not used. Tvheadend opens that file only when `-f` / `--fork` is also set, and this command does not fork. `QProcess.processId()` is the child PID.

## Ready, ports, and stop

The built-in server does not have to use Tvheadend's standard ports. HTTP 9981 and HTSP 9982 stay free for a local instance. The app chooses an HTTP port and an HTSP port in the high range and passes them to `--http_port` and `--htsp_port`. It does not bind a probe socket and then close it. That check races with the real bind.

A start is successful only when all of the following are true:

1. The `QProcess` child is still running. Its PID is `processId()`. No pid file is consulted.
2. Stderr has logged `Starting HTTP server` and `Starting HTSP server` for this child.
3. Stderr has not logged a `bind:` failure.
4. `GET /api/serverinfo` on the chosen HTTP port returns Tvheadend's server info.

`/api/serverinfo` answering is not enough. Any other Tvheadend already listening on that port answers it too. The child staying alive is not enough either: if `bind` fails, Tvheadend logs `bind: <addr>:<port>: ...` (for example `Address already in use`), keeps running, and leaves that listener unset. Mapping the listen socket to a PID is not the check. On Linux that means parsing `/proc/net/tcp` and `/proc/<pid>/fd`, and a Flatpak of `org.kde.Platform` does not include `ss` or `lsof`. macOS has no `/proc`. The stderr line is the portable signal.

If a `bind:` failure appears before the server is ready, the supervisor stops that child and picks a new port pair. It does this up to 3 attempts. After the third bind failure, or if the child exits for another reason, the status is failed. The UI does not connect to whoever is answering on the port.

The pair is remembered only after a successful ready check. The next launch requests that pair first. A remembered port of 9981 or 9982 is discarded and a new pair is chosen.

Stop and quit signal that child only. The supervisor asks `QProcess` to terminate, waits up to 5 seconds, then kills the child if it is still running. It never picks a process to signal by port number.

## Server list

The built-in server appears in both places the app lists servers: the main-window server combo and the configured-servers list. The entry is always present on Linux, macOS, and Flatpak. Windows is unchanged and does not gain this entry.

- The label is a fixed name, such as "Built-in Server", plus the running, starting, stopped, or failed state.
- Its URL is `http://127.0.0.1:<http-port>`, filled in after the ready check with the port the child bound. Until then the entry is listed and cannot be connected.
- Selecting it in the combo makes it the current server. If the child is not running, the app starts it, waits for the ready check, then loads channels from that port.
- The configured-servers list shows the same entry. Add, edit, and remove apply to user-added servers. Those actions leave the built-in entry in place, and edit does not open its address, username, or password for change.
- The entry stores a built-in flag in `tvhplayer.conf` so a restart can tell it apart from a user-added server that also uses loopback. The flag is the identity. The port is not.

Controls for that entry:

- Status: stopped, starting, running, or failed.
- Start, stop, and restart.
- **Open Web Interface**, described below.
- Auto-start with TVHplayer.
- A log view of the child's stderr.

### Open Web Interface

The built-in controls include an **Open Web Interface** action. It opens the built-in server's web UI in the system default browser. That page is where the user scans tuners and maps channels for this server.

- The URL is `http://127.0.0.1:<http-port>/`. `<http-port>` is the port the ready check confirmed this child is listening on. It is whatever port the app assigned. It is not hardcoded to 9981.
- The action is available only while the built-in server is running. While it is stopped, starting, or failed, the action is inactive.
- The app opens that URL with Qt's desktop URL opener (`QDesktopServices.openUrl`). On native Linux and macOS this launches the default browser. Inside Flatpak the same call goes through the OpenURI portal, so the sandbox does not spawn a host shell and does not need a browser bundled in the app.
- This action belongs to the built-in entry. It is shown when that entry is selected. A user-added server, including a local instance, does not get this action.

Startup waits for the ready check before loading channels from the built-in server.

`closeEvent` stops the child this app started. Before that stop, if `list_dvr_entries()` reports any entry whose category is `recording`, the app asks for confirmation and names those titles. The message says that quitting TVHplayer will stop the recording. Cancel leaves the window and the child running. If the recording list cannot be read while the child is running, the app asks for confirmation without a title rather than quitting silently. With no recording in progress, quit stops the child without that dialog.

## Permissions

On Linux, reading and writing `/dev/dvb` usually requires the `video` group, and VAAPI or similar transcoding needs `render`. When `/dev/dvb` exists and this user cannot open it, the app explains that. The built-in server still runs so IPTV and network sources work. The macOS package has no `/dev/dvb` check.

## Work plan

1. **Supervisor.** Implement the process owner in the app: shipped-binary path, `-c` under `default_config_dir()`, the command above, ready check from `processId()` plus stderr (`Starting HTTP server`, `Starting HTSP server`, no `bind:` failure) plus `/api/serverinfo`, up to 3 bind retries without a probe socket, and stop-only-the-child. Confirm quit when a built-in recording is in progress.
2. **UI.** List the built-in server in the main server combo and the configured-servers list as a permanent, non-editable entry. Add its status, start, stop, restart, stderr log, and **Open Web Interface**, which opens `http://127.0.0.1:<http-port>/` in the default browser only while this child is running. The port in that URL is the one the child bound. User-added servers stay ordinary connections.
3. **Packages.** Build `--enable-bundle` `tvheadend` into the native Linux package, the Flatpak at `/app/bin/tvheadend`, and the macOS `.app`. Confirm each app starts its own binary and leaves a host Tvheadend on 9981 untouched.

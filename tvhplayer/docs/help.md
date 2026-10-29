# TVHplayer User Guide

TVHplayer is a desktop app for watching and recording live TV. It plays channels from Tvheadend, the open-source TV streaming server: either the built-in server that comes with TVHplayer on Linux, or any Tvheadend server you already run.

## Getting Started

### Installation

Install TVHplayer from [Flathub](https://flathub.org/apps/io.github.mfat.tvhplayer), or download the deb, rpm, macOS or Windows build from the [Releases](https://github.com/mfat/tvhplayer/releases) page. The Flatpak, deb and rpm include the built-in server.

### The built-in server

On Linux, TVHplayer runs its own Tvheadend. It starts when TVHplayer starts and stops when TVHplayer quits, and it is kept apart from any Tvheadend already installed on the computer. Its channels, recordings and settings stay between sessions. It is listed as **Built-in server** in the server picker above the channel list.

Click the gear button (**Manage servers**) beside the server picker to see its status, start it, open its web interface (**Open Web Interface**), or read its log (**Server Log**).

### Connecting to your own Tvheadend server

1. Choose **File → Manage Servers…**, or click the gear button (**Manage servers**) above the channel list.
2. Click **Add Server…**.
3. Enter a name and the server address, for example `192.168.1.10`. Omitted schemes default to `http://`, and HTTP defaults to port 9981. Include `https://` for HTTPS or an explicit port for a reverse proxy, for example `http://myserver:80`.
4. Choose the **Connection method**. **HTSP (recommended)** (port 9982) is the default and provides live channel and recording updates. Use **HTTP / HTTPS** when HTSP is unavailable.
5. Enter your Tvheadend username and password, if the server asks for one.
6. Click **Test Connection**, then **Apply** to save and keep editing, or **OK** to save and close. A failed connection test does not prevent saving an offline server.

**Cancel**, Escape, or closing the window discards changes since the last Apply. The built-in server's **Start with TVHplayer** setting follows the same save behavior; **Start Server** and **Stop Server** take effect immediately.

Each server in the list shows whether it can be reached. Pick a server in the picker above the channel list to load its channels; TVHplayer starts on the server you used last.

### Setting up channels

The first time the built-in server starts without channels, **Set Up Channels** opens. You can open it again from **File → Set Up Channels…**, for the built-in server or any server whose login may change its settings.

- **A TV tuner**: TVHplayer lists the tuners the server found, USB and PCIe tuners as well as SAT>IP and HDHomeRun tuners on your network (**Look Again** searches again; an HDHomeRun that was just turned on can take 15 seconds to show up). Choose the signal, the tuners to use, and your region or satellite, then **Scan**. The server tries each frequency used there and adds the channels it finds; the TV guide fills in from the broadcast within minutes. Encrypted channels are left out unless you ask for them.
- **An IPTV playlist**: goes on to **Import Playlist**, described below.

## Using TVHPlayer

### Watching live TV

Double-click a channel, press Enter on it, or press the round play button under the picture. The same button, or P, stops playback. The bar under the picture also has the volume, mute, fullscreen and Record buttons.

While a channel starts, a spinner shows what the server is doing. For tuner channels it also shows the reception, for example **Signal weak (SNR 11 dB)**. If a channel will not start or stops, the reason the server gives, such as **No free adapter**, shows on the picture and in the status bar.

Press F or F11 for fullscreen and Escape to leave it. Right-click the picture for playback, recording and channel options. **View → Go to Playing Channel** (Ctrl+J) selects the playing channel in the list.

To start the channel you watched last whenever TVHplayer starts, turn on **Settings → Playback → Play the last channel when TVHplayer starts**.

### The TV guide

**View → TV Guide** (Ctrl+G), the **TV Guide** button above the channel list, or **Show in TV Guide** on a channel's right-click menu opens the guide: every channel against time, at the selected channel and the time now. Double-click a programme or press Enter to watch its channel. Use its Record button or Ctrl+R to record a programme, or to cancel its recording. Home goes back to what is on now.

**Show EPG** on a channel's right-click menu lists that one channel's programmes.

### Sound, subtitles, and picture

The **Playback** menu, also at the bottom of the right-click menu on the picture, lists the playing channel's sound tracks (for example another language or audio description) and its subtitles, DVB and teletext subtitles included. **Deinterlace** smooths broadcasts sent as interlaced video, such as 1080i HD channels. **Automatic** does it for streams marked as interlaced, **Always** for every stream, and **Off** shows the picture as sent.

### Customizing the channel list

Besides the channel name, the list can show the channel number, the program on now (with a bar showing how far it has got), the program on next, the channel type (Radio, SD, HD, UHD, Encrypted), and a status column that says when a channel is playing or recording.

- To choose columns, right-click the column headings, or choose **View → Channel List → Columns**.
- To move a column, drag its heading.
- **View → Channel List** also turns on or off channel logos, the progress bar, recording marks, the **Group** list (the channel tags set on your server), and hiding channels that are turned off on the server.
- **Reset Channel List Layout** brings back the defaults.
- The **Reload** button above the channel list, **View → Reload Channel List** or F5 reads the channels from the server again, for example after you change them in the Tvheadend web interface.

Your choices are saved and used the next time TVHplayer starts. The program and type columns only fill in when your server has guide data and service information for the channels. Some servers only share the channel type with admin users.

### Channel logos

Channels show the logo the server has for them. For channels without one, download the picons project's logos under **Settings → Channels → Channel logos** (about 25 MB, light or dark to suit your theme). TVHplayer then picks each missing logo by the channel's name. **Update Picons** fetches the newest pack and **Remove Picons** deletes it. **Show channel logos** turns logos on or off, like **View → Channel List → Channel Logos**.

### Editing channels

Right-click a channel to change it on the server, so every app connected to that server sees the change:

- **Add to Favourites** puts the channel in a Favourites group, which you can pick above the channel list. **Remove from Favourites** takes it out.
- **Rename…** gives the channel a name of your own, kept when the server scans again.
- **Change Number…** sets its number, such as 12 or 12.1. The list is sorted by number.
- **Hide Channel** turns the channel off on the server. To bring it back, turn off **View → Channel List → Hide Disabled Channels**, then right-click it and choose **Show Channel**.

These need a login that may change the server's settings. The built-in server always has one.

### Adding channels from a playlist

You can add internet TV channels from an M3U playlist or an Xtream Codes provider.

1. Choose **File → Import Playlist…** (Ctrl+I).
2. Choose **M3U playlist** and paste its web address or pick a file, or choose **Xtream Codes** and enter the provider server, username, and password.
3. If the provider requires them, add its user agent and other HTTP headers. These are used both to fetch the channel list and to open its streams; headers attached to an individual M3U entry take precedence.
4. If you have more than one server, choose where the channels go. The built-in server is chosen for you.
5. Click **Import**.

The channels appear in the channel list when the import finishes.

The server keeps the channels, so TVHplayer does not read the playlist again by itself. When your provider adds or removes channels, or changes their addresses, refresh it. To manage your playlists, choose **File → Playlists…**:

- **Refresh** reads the playlist again now: new channels are added, channels that left the playlist are removed, and channels whose address changed are tested again.
- **Settings…** changes provider headers or an Xtream Codes password, then refreshes the same playlist without adding it twice.
- **Health…** shows the latest saved Tvheadend check result and completion time for every channel.
- **Remove** removes the playlist and its channels.

### TV guide for internet channels

Internet channels get their TV guide from XMLTV guide files. For the built-in server, and any server running on this computer, choose **File → Guide Sources…**:

- **Find Guides…** compares your channels' guide IDs (the `tvg-id` in the playlist) with the free guides of epgshare01 and iptv-epg.org, and ticks the ones that cover the most channels. A country's guide can be tens of MB, so the first search takes a few minutes.
- **Add…** takes the web address of any XMLTV guide, packed or not, or a guide file on this computer, for example one made by WebGrab+Plus.
- A playlist that names its own guide adds it here by itself.
- **Update** sets how often each guide is downloaded again while TVHplayer runs; **Update Now** downloads them all at once.

A guide that fails to download, has no programmes, or has far fewer than last time is not used; the last good copy stays.

A channel takes the guide whose channel has the same ID. **Match Channels…** shows where each channel's programmes come from. Channels without an ID, or whose ID no guide has, get suggestions by name; tick them and choose **Use Ticked Suggestions**, or pick a guide channel yourself (**Search the guides** finds one by name or ID). Names are never used without asking, because many networks share a name across regions. **Shift times by** moves a channel's programmes, for example 60 minutes for a "+1" channel. Each channel, the SD and HD versions included, gets its own copy of the programmes.

A server on another computer cannot take a guide from TVHplayer. Its own guide grabbers are set up in its web interface.

### Recording

The **Record** button under the picture records the playing channel:

- **Record on server…** (Ctrl+R) records on the Tvheadend server, for as long as you choose. The file stays on the server.
- **Record on this computer** (Ctrl+Shift+R) records with ffmpeg into your recordings folder, for as long as you choose. Several channels can record at once.

While recording, the button turns into Stop: Ctrl+E stops the server recording and Ctrl+Shift+E the one on this computer.

To schedule a programme, open the TV guide or **Show EPG** and record it from there. Recordings on the built-in server go into the same recordings folder as recordings on this computer.

### Recording settings

**Settings → Recordings**:

- **Save recordings in** sets the recordings folder, your Videos folder by default.
- **Warn when free space is below** makes the status bar warn when the folder is nearly full (5 GB by default; 0 turns it off).
- **Format** chooses MPEG-TS (the default), MP4 or Matroska for recordings on this computer. **Extra ffmpeg options** are added after the format's own.
- **Built-in server**: the built-in server starts each recording 2 minutes early and ends it 5 minutes late, in case the broadcast runs early or late. Change the margins here.

**Settings → Conversion** makes an MP4 copy that video editors seek through smoothly: a constant frame rate, a keyframe every second and AAC sound. **Convert recordings when they finish** does this for every new recording, and can delete the original once the copy is made. Any recording can also be converted from its right-click menu in Tasks.

### Tasks

**View → Tasks** shows the recordings on the server and on this computer, with their state, channel, time and size. It opens by itself when a recording starts or is scheduled. Choose **Active** (recording and scheduled), **All**, **Recording**, **Scheduled** or **Completed** to filter the list. Right-click a task to stop it, convert it, show a local recording in the file manager, or go to its channel.

**View → Server Status** shows the server's tuners and signal, and **View → DVR Status** its recordings.

### Overlapping recordings

When scheduled recordings overlap on more channels than the server has tuners, TVHplayer says so once and lets you choose the recording that must not be missed; the server then records that one first. Channels on one multiplex share a tuner, and IPTV channels need none. This needs a login that may read the server's settings.

### Sleep

While this computer is recording, TVHplayer keeps it from going to sleep. It also stays awake while a recording is scheduled on the built-in server or another server on this computer; turn that off under **Settings → Sleep**. TVHplayer has to stay open for the built-in server to record, so it asks before quitting while it records to this computer or has recordings scheduled on the built-in server.

## Appearance

**Settings → Appearance**:

- **Application style**: TVHplayer, the app's own look, or any style Qt offers on your computer, such as Breeze or Fusion.
- **Theme**: Follow System, Light or Dark.
- **Use TVHplayer's own title bar** (GNOME and KDE on Wayland, and KDE on X11): a title bar drawn by TVHplayer in place of the desktop's. Takes effect the next time TVHplayer starts.

## Playback

TVHplayer plays with **mpv** (libmpv), drawing into the window on Wayland and X11 so the interface stays sharp at fractional scale.

## Keyboard shortcuts

Press F1 (**Help → Keyboard Shortcuts**) for the full list. The most used ones:

| Key | Action |
|---|---|
| Enter | Play the selected channel |
| P | Play or stop |
| M | Mute or unmute |
| Ctrl+Up / Ctrl+Down | Volume |
| F or F11, Escape | Fullscreen, leave fullscreen |
| Ctrl+F or S | Search channels |
| Ctrl+J | Go to the playing channel |
| F5 | Reload the channel list |
| Ctrl+G | TV guide |
| Ctrl+R, Ctrl+E | Record on the server, stop it |
| Ctrl+Shift+R, Ctrl+Shift+E | Record on this computer, stop it |
| Ctrl+I | Import a playlist |
| Ctrl+, | Settings |

## Troubleshooting

- **A channel will not start**: read the reason on the picture or in the status bar. **No free adapter** means every tuner is busy; a weak signal shows while the channel starts.
- **Cannot connect to a server**: check that Tvheadend is running and reachable, and that the address includes `http://` and the port. **Test Connection** in Manage servers says what went wrong.
- **Built-in server problems**: open its log from Manage servers → **Server Log**.
- **Imported channels are missing**: channels that fail the stream test are hidden. Turn off **Settings → Channels → Hide channels that do not work** to see them all, or **Check channels now** to test them again.

**Help → Open Log Folder** opens the folder with `app.log` (TVHplayer) and `tvheadend.log` (the built-in server). Please attach both when you [report a bug](https://github.com/mfat/tvhplayer/issues/new).

## Additional Resources

- [Tvheadend documentation](https://docs.tvheadend.org/documentation)

# TVHPlayer Documentation

Welcome to the TVHPlayer help documentation. This guide will help you understand how to use the TVHPlayer app effectively.

## Overview

TVHPlayer is a user-friendly application designed to provide seamless streaming of TV content. It integrates with TVHeadend, a popular open-source TV streaming server, to deliver live TV and recorded content to your devices.

## Features

- Stream live TV channels
- View Electronic Program Guide (EPG)
- Schedule recordings
- Record locally on your computer
- User-friendly interface


## Getting Started

### Installation

To install TVHPlayer, download the app from the official website or Flathub.

### Connecting to TVHeadend

To connect TVHPlayer to your TVHeadend server:

1. Open the TVHPlayer app.
2. Click the small cog icon above channel list to add your server
3. Enter the IP address and port number of your TVHeadend server (includibg http:// or https://)
4. Enter your TVHeadend username and password.
5. Save the settings and test the connection.

### Setting up channels

The first time the built-in server starts without channels, **Set Up Channels** opens. You can open it again from **File → Set Up Channels…**, for the built-in server or any server whose login may change its settings.

- **A TV tuner**: TVHplayer lists the tuners the server found, USB and PCIe tuners as well as SAT>IP and HDHomeRun tuners on your network (**Look Again** searches again; an HDHomeRun that was just turned on can take 15 seconds to show up). Choose the signal, the tuners to use, and your region or satellite, then **Scan**. The server tries each frequency used there and adds the channels it finds; the TV guide fills in from the broadcast within minutes. Encrypted channels are left out unless you ask for them.
- **An IPTV playlist**: goes on to **Import Playlist**, described below.

## Using TVHPlayer

### Streaming Live TV

Press the play button or double-click a channel on the channel list to start playback.

### Sound, subtitles, and picture

The **Playback** menu, also at the bottom of the right-click menu on the picture, lists the playing channel's sound tracks (for example another language or audio description) and its subtitles, DVB and teletext subtitles included. **Deinterlace** smooths broadcasts sent as interlaced video, such as 1080i HD channels. **Automatic** does it for streams marked as interlaced, **Always** for every stream, and **Off** shows the picture as sent.

### Customizing the channel list

Besides the channel name, the list can show the channel number, the program on now (with a bar showing how far it has got), the program on next, the channel type (Radio, SD, HD, UHD, Encrypted), and a status column that says when a channel is playing or recording.

- To choose columns, right-click the column headings, or choose **View → Channel List → Columns**.
- To move a column, drag its heading.
- **View → Channel List** also turns on or off channel logos, the progress bar, recording marks, the **Group** list (the channel tags set on your server), and hiding channels that are turned off on the server.
- **Reset Channel List Layout** brings back the defaults.

Your choices are saved and used the next time TVHplayer starts. The program and type columns only fill in when your server has guide data and service information for the channels. Some servers only share the channel type with admin users.

### Channel logos

Channels show the logo the server has for them. For channels without one, download the picons project's logos under **Settings → General → Channel logos** (about 25 MB, light or dark to suit your theme). TVHplayer then picks each missing logo by the channel's name. **Update Picons** fetches the newest pack and **Remove Picons** deletes it.

### Editing channels

Right-click a channel to change it on the server, so every app connected to that server sees the change:

- **Add to Favourites** puts the channel in a Favourites group, which you can pick above the channel list. **Remove from Favourites** takes it out.
- **Rename…** gives the channel a name of your own, kept when the server scans again.
- **Change Number…** sets its number, such as 12 or 12.1. The list is sorted by number.
- **Hide Channel** turns the channel off on the server. To bring it back, turn off **View → Channel List → Hide Disabled Channels**, then right-click it and choose **Show Channel**.

These need a login that may change the server's settings. The built-in server always has one.

### Adding channels from a playlist

You can add internet TV channels from an M3U playlist.

1. Choose **File → Import Playlist…** (Ctrl+I).
2. Paste the playlist's web address, or click **Browse…** to pick a playlist file.
3. If you have more than one server, choose where the channels go. The built-in server is chosen for you.
4. Click **Import**.

The channels appear in the channel list when the import finishes.

Playlists on the built-in server are checked again each time TVHplayer starts, so new channels are added and channels that left the playlist are removed. To manage your playlists, choose **File → Playlists…**:

- **Refresh** reads the playlist again now.
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

### Schedule recordings

1. To record a live program using Tvheaden's DVR function, click the record button below the player. Recordings will be stored on the server.
2. To schedule recording a show, right-click on the channel name and select "Show EPG". From the EPG window you can schedule recordings
3. To record live TV locally on your computer press the local record button (the downward arrow)

The built-in server starts each recording 2 minutes early and ends it 5 minutes late, in case the broadcast runs early or late; change the margins under **Settings → Recordings**. The status bar warns when the recordings folder has less than 5 GB free; the amount is set there too.

When scheduled recordings overlap on more channels than the server has tuners, TVHplayer says so once and lets you choose the recording that must not be missed; the server then records that one first. Channels on one multiplex share a tuner, and IPTV channels need none. This needs a login that may read the server's settings.

While this computer is recording, TVHplayer keeps it from going to sleep. It also stays awake while a recording is scheduled on the built-in server or another server on this computer; turn that off under **Settings → Recordings → Sleep**. TVHplayer has to stay open for the built-in server to record.

## Troubleshooting

If you encounter any issues while using TVHPlayer, try the following steps:

1. Ensure your TVHeadend server is running and accessible.
2. Check your network connection.
3. Verify that you have entered the correct IP address, port number, username, and password in the app settings.
4. Restart the TVHPlayer app and your device.

## Additional Resources

For more information and support, refer to the official TVHeadend documentation:

- [TVHeadend Official Documentation](https://docs.tvheadend.org/documentation)

Thank you for using TVHPlayer.
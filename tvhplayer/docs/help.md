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

### Schedule recordings

1. To record a live program using Tvheaden's DVR function, click the record button below the player. Recordings will be stored on the server.
2. To schedule recording a show, right-click on the channel name and select "Show EPG". From the EPG window you can schedule recordings
3. To record live TV locally on your computer press the local record button (the downward arrow)

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
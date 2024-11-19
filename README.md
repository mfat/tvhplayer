
![tvhplayer](https://github.com/user-attachments/assets/96b567e2-3ce7-45dd-aad8-b64239a54f2c)

# TVHplayer
Desktop client for playback and recording live TV with TVheadend

![Screenshot](https://github.com/user-attachments/assets/573b6563-0915-481b-ac02-d18bc8297526)


## Features:
- Add multiple servers
- Play TV & radio channels
- Initiate instant records on your TVheadend server
- Record live TV locally
- Set custom duration for recordings
- Cross-platform - runs on linux, macOS and Windows

## Download
- Head to [releases](https://github.com/mfat/tvhplayer/releases) section to download
- tvhplayer is the linux executable.
- For windows download the exe file

## Requirements
- VLC must be installed as it's used for playback. (on linux make sure to install vlc dev packages too)
- FFMPEG (used for local recording feature if you need it)
  - On Windows follow [this guide](https://phoenixnap.com/kb/ffmpeg-windows) to add ffmpeg to windows PATH. You can also put ffmpeg.exe in the same directory as tvhplayer.
 
## Support
- For any problems or bugs [create an issue](https://github.com/user/repository/issues/new)

## Run the app from source (faster)
- You can run the code directly with python, this way the app will start faster. You may want to do this if you don't want to download the executable.
To do this:
- install python
- download the [requirements.txt](https://github.com/mfat/tvhplayer/blob/main/requirements.txt) and run this command:
  `pip install -r requirements.txt`
- Download [necessary resources](https://github.com/mfat/tvhplayer/releases/download/v2.0/v2.0.zip) and put in the same directory as tvhplayer.py
- Run the app withL
  `python3 tvhplayer.py`
  

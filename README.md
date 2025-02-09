
![tvhplayer](https://github.com/user-attachments/assets/96b567e2-3ce7-45dd-aad8-b64239a54f2c)

# TVHplayer
Desktop client for playback and recording live TV with TVheadend


![Screenshot2](https://github.com/user-attachments/assets/281563a5-54e2-4b58-a4f3-3a59c8830c24)



## Features:
- Add multiple servers
- Browse EPG for each channel and schedule recording your favorite shows
- Play live TV & radio channels
- Initiate instant records on your TVheadend server
- Record live TV locally
- Set custom duration for recordings
- Monitor your server status, signal strength and DVR right from the app
- Uses built-in VLC player for maximum compatibility 
- Cross-platform - runs on linux, macOS and Windows

## Download
- Head to [releases](https://github.com/mfat/tvhplayer/releases) section to download for your operating system
  

## Requirements
- VLC must be installed as it's used for playback. (on linux make sure to install vlc dev packages too)
- FFMPEG (used for local recording feature if you need it)
  - On Windows follow [this guide](https://phoenixnap.com/kb/ffmpeg-windows) to add ffmpeg to windows PATH. You can also put ffmpeg.exe in the same directory as tvhplayer.
 
## Support
- For any problems or bugs [create an issue](https://github.com/user/repository/issues/new)

## Run the app from source 
- You can run the code directly with python. You may want to do this if you don't want to download an executable.
To do this:
- install python
- download the [requirements.txt](https://github.com/mfat/tvhplayer/blob/main/requirements.txt) and run this command:
  `pip install -r requirements.txt`
- Download the tvhplayer zip file from the latest release and extract to a folder or clone using git:
  `git clone https://github.com/mfat/tvhplayer.git`
- cd into the folder
- Run the app with:
  `python3 tvhplayer/tvhplayer.py`
  
## Support development
Bitcoin: `bc1qqtsyf0ft85zshsnw25jgsxnqy45rfa867zqk4t`

Doge:  `DRzNb8DycFD65H6oHNLuzyTzY1S5avPHHx`

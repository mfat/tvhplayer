"""Make the store screenshots in Screenshots/ offscreen, all the same size.

    python3 video/store_screenshots.py [OUT_DIR] [--scale 1]

The real app draws each window with its own title bar and shadow, at default
settings otherwise, with the made-up channels, logos, guide and recordings
from demo_data.py. Offscreen there is no video engine, so the picture area
shows a frame of the NASA clip (demo_data.nasa_clip) the way the player
fits a picture: whole, centred on black.

The guide is a window of its own, which the app leaves to the desktop's
title bar; here it gets the app's title bar, like the main window.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'video'))

HEIGHT = 660
PLAYING = 'Science Now'
RECORDINGS = [('Sports Live', 'mp4'), ('Cinema One', 'mkv'), ('News 24', 'ts')]
SERVER = {'name': 'Living Room', 'url': 'http://192.0.2.1:9981'}
# Seconds into the clip: Earth at night with the station's solar arrays.
FRAME_AT = 8


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path, nargs='?', default=ROOT / 'Screenshots')
    parser.add_argument('--scale', type=float, default=1.0, help='device pixels per window pixel')
    args = parser.parse_args()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['QT_SCALE_FACTOR'] = str(args.scale)

    import demo_data as demo
    from demo_data import settle

    home = Path(tempfile.mkdtemp(prefix='tvhplayer-shots-'))
    frame = home / 'frame.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(FRAME_AT), '-i', str(demo.nasa_clip()),
                    '-frames:v', '1', str(frame)], check=True)

    import tvhplayer.guide_view as guide_view
    import tvhplayer.tvhplayer as ui
    from tvhplayer import ui_theme, window_frame
    from tvhplayer.core.config import ConfigStore
    from tvhplayer.core.player import Timeshift
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtWidgets import QApplication, QMainWindow, QMenuBar, QWidget

    class Picture(QWidget):
        """Stands in for the video surface: the clip's frame, fitted whole on black."""

        image = None

        def paintEvent(self, _event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor('black'))
            if Picture.image is not None:
                fitted = Picture.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)
                painter.drawImage((self.width() - fitted.width()) // 2, (self.height() - fitted.height()) // 2, fitted)
            painter.end()

    now = int(time.time()) // 1800 * 1800 + 1200
    events = demo.schedule(now)
    backend = demo.Backend(events)
    store = ConfigStore(home / 'tvhplayer.conf')
    store.data['title_bar'] = True
    ui.ConfigStore = lambda *a, **k: store
    ui.windows_backend_enabled = lambda: False
    ui.default_picon_dir = lambda: home / 'picons'
    ui.create_backend = guide_view.create_backend = lambda server: backend
    ui.TVHeadendClient._new_player = lambda self: demo.FakePlayer()
    ui.TVHeadendClient._new_video_surface = lambda self: Picture()
    ui.TVHeadendClient.fetch_channels = lambda self, keep_place=False: None
    window_frame.wants_own_title_bar = lambda *a, **k: True
    demo.fake_files()

    app = QApplication.instance() or QApplication([])
    Picture.image = QImage(str(frame))
    demo.make_logos(home / 'picons')
    ui_theme.apply(app, store.data['ui_theme'])
    channels = demo.channels()
    args.out.mkdir(parents=True, exist_ok=True)

    def main_window(mode):
        ui_theme.set_color_scheme(app, mode)
        window = ui.TVHeadendClient()
        window.get_backend = lambda: backend
        window._server_requests_ready = lambda: True
        demo.load(window, ui, channels, events, now, SERVER)
        window.show()
        settle(app)
        window.play_channel_by_data(demo.find(channels, PLAYING))
        window.player.state = Timeshift(False, 0.0, 600.0)
        window.controls_bar.set_timeshift(window.player.state)
        window.statusbar.showMessage(f'Playing: {PLAYING}')
        window.channel_list.setFocus()
        window.activateWindow()
        settle(app)
        return window

    # Every screenshot the same size: as narrow as the window can be with Tasks open.
    window = main_window('light')
    window.tasks_pane.show()
    settle(app)
    size = (max(window.minimumSizeHint().width(), window.minimumWidth(), 1340), HEIGHT)
    window.tasks_pane.hide()
    window.resize(*size)
    settle(app)

    def save(widget, name):
        image = widget.grab()
        image.save(str(args.out / name))
        print(f'{args.out / name}: {image.width()} x {image.height()}')

    save(window, 'main-window.png')

    # The guide, in a window with the app's title bar, at the same size.
    window.show_guide(demo.find(channels, PLAYING))
    guide = window._guide
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not guide.grid.data.loaded:
        settle(app, 2)
    host = QMainWindow()
    host.setWindowTitle('TV Guide — TVHplayer')
    guide.setWindowFlags(Qt.WindowType.Widget)
    host.setCentralWidget(guide)
    window_frame.WindowFrame(host, QMenuBar(host))
    host.resize(*size)
    host.show()
    host.activateWindow()
    settle(app)
    # Again at this size, so the playing channel's row is in view.
    guide.grid.focus_channel(demo.find(channels, PLAYING))
    guide.grid.setFocus()
    settle(app)
    save(host, 'tv-guide.png')
    host.close()

    window.local_jobs = demo.recordings(ui, channels, now, RECORDINGS)
    window._refresh_tasks(server=False)
    window.sync_recording_indicator()
    window._open_tasks_pane()
    window.resize(*size)
    window.activateWindow()
    settle(app)
    save(window, 'recordings.png')
    window.local_jobs = []
    window.close()

    window = main_window('dark')
    window.resize(*size)
    settle(app)
    save(window, 'dark-style.png')
    window.close()


if __name__ == '__main__':
    main()

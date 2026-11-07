"""Open the real TVHplayer on this desktop with made-up channels, for store screenshots.

    python3 video/screenshot_demo.py [CLIP.mp4] [--recordings] [--theme NAME] [--scheme light|dark]

The app starts as a new user's would, with default settings in a temporary
profile (your own settings are not read or changed). It shows the channels,
logos, programme guide and recordings from demo_data.py, and plays CLIP on
a loop as the picture of every channel. Without CLIP it fetches 30 seconds of
NASA's "Earth in 4K" from the Space Station (public domain) once, into
video/build/footage/. Take the screenshots with the
desktop's own window screenshot (Alt+Print Screen on GNOME), so each one
has the real title bar and shadow.

--recordings  adds three recordings to this computer, which open Tasks.
--theme       Organic (the default), TVHplayer or a Qt style.
--scheme      light or dark instead of following the desktop.
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'video'))

# Every window the same size, so the screenshots match: as narrow as the
# main window can be with Tasks open, which depends on the desktop's fonts,
# so it is measured on screen. (Flathub suggests 1000 by 700 at most.)
WINDOW = [1340, 660]
PLAYING = 'Science Now'
RECORDINGS = [('Sports Live', 'mp4'), ('Cinema One', 'mkv'), ('News 24', 'ts')]
SERVER = {'name': 'Living Room', 'url': 'http://192.0.2.1:9981', 'protocol': 'http'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('clip', type=Path, nargs='?', help='a video file to show as the picture')
    parser.add_argument('--recordings', action='store_true')
    parser.add_argument('--theme')
    parser.add_argument('--scheme', choices=('light', 'dark'))
    args = parser.parse_args()
    import demo_data as demo

    clip = (args.clip or demo.nasa_clip()).resolve()
    if not clip.is_file():
        parser.error(f'{clip} is not a file')

    import tvhplayer.guide_view as guide_view
    import tvhplayer.tvhplayer as ui
    from tvhplayer.core.config import ConfigStore
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    home = Path(tempfile.mkdtemp(prefix='tvhplayer-demo-'))
    store = ConfigStore(home / 'tvhplayer.conf')
    store.data.update({
        'servers': [SERVER], 'last_server': 0, 'builtin_autostart': False,
        # No first-run offers or update checks over the screenshots.
        'setup_dismissed': True, 'check_for_updates': False,
    })
    if args.theme:
        store.data['ui_theme'] = args.theme
    if args.scheme:
        store.data['color_scheme'] = args.scheme
    store.save()
    ui.ConfigStore = lambda *a, **k: store
    ui.windows_backend_enabled = lambda: False
    ui.platform_supports_builtin = lambda: False
    ui.default_picon_dir = lambda: home / 'picons'

    now = int(time.time())
    events = demo.schedule(now // 1800 * 1800 + 1200)
    backend = demo.Backend(events, stream=str(clip))
    channels = demo.channels()
    guide_view.create_backend = lambda server: backend
    # Tasks and the other parts that open their own connection to the server.
    ui.create_backend = lambda server: backend
    ui.TVHeadendClient.get_backend = lambda self: backend
    ui.TVHeadendClient._server_requests_ready = lambda self: True
    if args.recordings:
        demo.fake_files()

    new_player = ui.TVHeadendClient._new_player

    def looping_player(self):
        player = new_player(self)
        # The clip stands in for a live channel, so it never ends.
        player._mpv['loop-file'] = 'inf'
        return player

    ui.TVHeadendClient._new_player = looping_player

    def load_channels(self, keep_place=False):
        demo.load(self, ui, channels, events, now // 1800 * 1800 + 1200, SERVER)

        def start():
            # Measure with Tasks open, then use that width for every shot.
            tasks_open = self.tasks_pane.isVisible()
            self.tasks_pane.show()
            QApplication.processEvents()
            WINDOW[0] = max(WINDOW[0], self.minimumSizeHint().width(), self.minimumWidth())
            self.tasks_pane.setVisible(tasks_open)
            self.resize(*WINDOW)
            print(f'Window size for every screenshot: {WINDOW[0]} x {WINDOW[1]}')
            self.play_channel_by_data(demo.find(channels, PLAYING))
            if args.recordings:
                self.local_jobs = demo.recordings(ui, channels, now, RECORDINGS)
                self._refresh_tasks(server=False)
                self.sync_recording_indicator()
            self.channel_list.setFocus()

        QTimer.singleShot(300, start)

    ui.TVHeadendClient.fetch_channels = load_channels

    guide_init = guide_view.GuideWindow.__init__

    def guide_at_store_size(self, *a, **k):
        guide_init(self, *a, **k)
        self.resize(*WINDOW)

    guide_view.GuideWindow.__init__ = guide_at_store_size
    # The app reads the logo folder once its window is up; the logos are drawn
    # with Qt, so here, when the window is being made.
    (home / 'picons').mkdir()
    window_init = ui.TVHeadendClient.__init__

    def with_logos(self, *a, **k):
        demo.make_logos(home / 'picons')
        window_init(self, *a, **k)

    ui.TVHeadendClient.__init__ = with_logos
    sys.argv = sys.argv[:1]
    ui.main()


if __name__ == '__main__':
    main()

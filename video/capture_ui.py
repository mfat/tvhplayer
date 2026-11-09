"""Draw TVHplayer's real windows offscreen for the intro video.

Run by scripts/render-intro-video.ts as ``capture_ui.py OUT_DIR SCALE``. It
builds the main window, the TV guide and the Tasks list from the app's own
code with made-up channels, saves PNGs to OUT_DIR and prints a JSON manifest:
the files and, in window pixels, where the controls the video animates over
are. The channels, programmes and logos come from demo_data.py. No server,
network or video is used; the picture area stays black and
the video draws its own picture there.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'video'))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'video' / 'build')
SCALE = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
os.environ['QT_SCALE_FACTOR'] = str(SCALE)

WINDOW = (1440, 900)
TASKS_WINDOW = (2240, 900)
PLAYING = 'Nature HD'
RECORDINGS = [('Nature HD', 'ts'), ('Sports Live', 'mp4'), ('Cinema One', 'mkv')]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix='tvhplayer-video-'))
    import tvhplayer.tvhplayer as ui
    import tvhplayer.guide_view as guide_view
    from tvhplayer import ui_theme, window_frame
    from tvhplayer.core.config import ConfigStore
    from tvhplayer.core.player import Timeshift
    import demo_data as demo
    from demo_data import settle
    from PyQt6.QtWidgets import QApplication

    now = int(time.time()) // 1800 * 1800 + 1200
    events = demo.schedule(now)

    Backend = lambda: demo.Backend(events)  # noqa: E731

    store = ConfigStore(home / 'tvhplayer.conf')
    store.data['title_bar'] = True
    ui.ConfigStore = lambda *a, **k: store
    ui.windows_backend_enabled = lambda: False
    ui.default_picon_dir = lambda: home / 'picons'
    ui.TVHeadendClient._new_player = lambda self: demo.FakePlayer()
    ui.TVHeadendClient.fetch_channels = lambda self, keep_place=False: None
    window_frame.wants_own_title_bar = lambda *a, **k: True
    guide_view.create_backend = lambda server: Backend()

    demo.fake_files()
    app = QApplication.instance() or QApplication([])
    demo.make_logos(home / 'picons')
    ui_theme.apply(app, ui_theme.THEME_ORGANIC)
    channels = demo.channels()
    from tvhplayer.core.recorder import RECORDING_FORMATS
    manifest = {'formats': [label for label, *_rest in RECORDING_FORMATS.values()], 'scale': SCALE, 'window': list(WINDOW), 'channels': [c.name for c in channels], 'files': []}

    def save(widget, name):
        widget.grab().save(str(OUT / name))
        manifest['files'].append(name)

    for mode in ('light', 'dark'):
        # A new window for each scheme, as when the app starts in it.
        ui_theme.set_color_scheme(app, mode)
        window = ui.TVHeadendClient()
        window.get_backend = lambda: Backend()
        window._server_requests_ready = lambda: True
        window.resize(*WINDOW)
        demo.load(window, ui, channels, events, now, {'name': 'Living Room', 'url': 'http://192.0.2.1:9981'})
        window.show()
        settle(app)
        window.play_channel_by_data(demo.find(channels, PLAYING))
        window.channel_list.setFocus()
        window.activateWindow()
        settle(app)

        def rect_of(widget):
            top_left = widget.mapTo(window, widget.rect().topLeft())
            return [top_left.x(), top_left.y(), widget.width(), widget.height()]

        manifest['video'] = rect_of(window.video_frame)
        manifest['bar'] = rect_of(window.controls_bar)
        bar, player = window.controls_bar, window.player

        def state(paused, behind, recording):
            # The window reads the player's timeshift itself, so set it there too.
            player.state = Timeshift(paused, float(behind), 600.0)
            bar.set_timeshift(player.state)
            bar.set_recording(False, recording, PLAYING)
            window.statusbar.showMessage(f'Playing: {PLAYING}')
            settle(app)

        # Live, then paused, then ten seconds back, then recording from there.
        for name, args in (('live', (False, 0, False)), ('paused', (True, 0, False)),
                           ('rewound', (False, 10, False)), ('recording', (False, 10, True))):
            state(*args)
            save(window, f'main-{mode}-{name}.png')
        manifest['record'] = rect_of(bar.record_btn)
        manifest['pause'] = rect_of(bar.pause_btn)
        manifest['back'] = rect_of(bar.back_btn)
        manifest['list'] = rect_of(window.channel_list.viewport())
        manifest[f'base_{mode}'] = ui_theme.color('base').name()

        # Several channels recording to this computer at once, one per format.
        jobs = demo.recordings(ui, channels, now, RECORDINGS)
        window.local_jobs = jobs
        bar.set_recording(False, True, PLAYING)
        window._open_tasks_pane()
        window.tasks_pane.refresh(server=False)
        settle(app)
        # Wide enough for the Tasks columns beside the picture.
        window.resize(TASKS_WINDOW[0], WINDOW[1])
        settle(app)
        sizes = window.splitter.sizes()
        window.splitter.setSizes([sizes[0], sum(sizes) - sizes[0] - 1040, 1040])
        settle(app)
        manifest['tasks'] = rect_of(window.tasks_pane)
        manifest['tasks_window'] = [window.width(), window.height()]
        manifest['tasks_video'] = rect_of(window.video_frame)
        table = window.tasks_pane.task_table
        manifest['task_rows'] = []
        for row in range(table.rowCount()):
            cell = table.visualItemRect(table.item(row, 0))
            top_left = table.viewport().mapTo(window, cell.topLeft())
            channel = table.item(row, 2).text()
            manifest['task_rows'].append({'y': top_left.y(), 'height': cell.height(), 'channel': channel,
                                          'format': dict(RECORDINGS)[channel]})
        save(window, f'tasks-{mode}.png')
        window.local_jobs = []

        window.show_guide(demo.find(channels, PLAYING))
        guide = window._guide
        guide.resize(1200, 720)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not guide.grid.data.loaded:
            settle(app, 2)
        settle(app)
        save(guide, f'guide-{mode}.png')
        guide.close()
        window.close()
        settle(app)
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()

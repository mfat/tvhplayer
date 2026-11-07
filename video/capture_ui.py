"""Draw TVHplayer's real windows offscreen for the intro video.

Run by scripts/render-intro-video.ts as ``capture_ui.py OUT_DIR SCALE``. It
builds the main window, the TV guide and the Tasks list from the app's own
code with made-up channels, saves PNGs to OUT_DIR and prints a JSON manifest:
the files and, in window pixels, where the controls the video animates over
are. No server, network or video is used; the picture area stays black and
the video draws its own picture there.
"""

import json
import os
import sys
import tempfile
import time
import types
from datetime import datetime
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'video' / 'build')
SCALE = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
os.environ['QT_SCALE_FACTOR'] = str(SCALE)

WINDOW = (1440, 900)
TASKS_WINDOW = (2240, 900)
PLAYING = 'Nature HD'
# Made-up channels and programmes, as on the website: never real broadcasters.
CHANNELS = [
    ('News 24', ['Evening Headlines', 'Business Hour', 'World Tonight', 'Late Edition']),
    ('Capital TV', ['City Life', 'The Late Show', 'Night Desk', 'Replay']),
    ('Cinema One', ['The Long Voyage', 'Midnight Movie', 'Film Club']),
    ('World News', ['Global Report', 'Weather', 'Global Report', 'Markets']),
    ('Sports Live', ['Match of the Week', 'Highlights', 'Extra Time']),
    ('Nature HD', ['Wild Coasts', 'Ocean Giants', 'Night Forest', 'Rivers']),
    ('Kids Club', ['Cartoon Hour', 'Story Time', 'Puzzle Quest', 'Goodnight']),
    ('Music Hits', ['Top 40 Countdown', 'Live Sessions', 'Throwback']),
    ('Comedy Plus', ['Stand-up Night', 'Sketch Show', 'Sitcom Classics']),
    ('Science Now', ['Space Frontiers', 'How It Works', 'Big Ideas']),
    ('Travel & Taste', ['Street Food Tour', 'Island Hopping', 'Slow Trains']),
    ('Classic Films', ['Silver Screen', 'Double Feature']),
    ('Weather Today', ['Forecast', 'Climate Watch', 'Forecast', 'Outlook']),
    ('Radio Lounge', ['Chill Mix', 'Night Grooves', 'Deep Cuts']),
    ('Jazz FM', ['Late Jazz', 'Blue Notes', 'Standards']),
    ('Talk Radio', ['Phone-in', 'Night Talk', 'Morning Early']),
]


DESCRIPTIONS = {'Wild Coasts': 'Seals, puffins and winter storms along a rugged shore.'}

# Local recordings shown in Tasks: a made-up folder, sizes given here.
FOLDER = '/home/you/Videos'
RECORDINGS = [('Nature HD', 'ts'), ('Sports Live', 'mp4'), ('Cinema One', 'mkv')]
SIZES = {}


def fake_files():
    """Make the recordings' paths exist with their sizes, for the Tasks list only."""
    exists, getsize = os.path.exists, os.path.getsize
    os.path.exists = lambda path: path in SIZES or exists(path)
    os.path.getsize = lambda path: SIZES[path] if path in SIZES else getsize(path)


def settle(app, rounds=8):
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.02)


class FakePlayer:
    """Just enough of the mpv player for the window to draw."""

    def __init__(self):
        self._playing = False
        self.on_playing = None
        self.state = None

    def set_handlers(self, on_playing=None, *_args, **_kwargs):
        self.on_playing = on_playing

    def play(self, url):
        self._playing = True
        if self.on_playing:
            self.on_playing()

    def stop(self):
        self._playing = False

    def is_playing(self):
        return self._playing

    def is_muted(self):
        return False

    def audio_tracks(self):
        return []

    def subtitle_tracks(self):
        return []

    def audio_track(self):
        return -1

    def subtitle_track(self):
        return -1

    def deinterlace(self):
        return 'auto'

    def timeshift(self):
        return self.state

    def __getattr__(self, name):
        return lambda *a, **k: None


def schedule(now):
    """Each channel's programmes from an hour ago on, of varied lengths."""
    from tvhplayer.core.models import EpgEvent

    events, event_id = [], 1
    for index, (_name, titles) in enumerate(CHANNELS):
        start = now - 1800 - 600 * ((index * 5) % 4)
        lengths = [3600, 1800, 5400, 2700, 3600]
        step = 0
        while start < now + 6 * 3600:
            stop = start + lengths[(index + step) % len(lengths)]
            title = titles[step % len(titles)]
            events.append(EpgEvent(start=start, stop=stop, title=title, channel_uuid=f'c{index}',
                                   event_id=event_id, description=DESCRIPTIONS.get(title, '')))
            event_id += 1
            start, step = stop, step + 1
    return events


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix='tvhplayer-video-'))
    import tvhplayer.tvhplayer as ui
    import tvhplayer.guide_view as guide_view
    from tvhplayer import ui_theme, window_frame
    from tvhplayer.core.channel_info import NowNext
    from tvhplayer.core.config import ConfigStore
    from tvhplayer.core.models import Channel
    from tvhplayer.core.player import Timeshift
    from PyQt6.QtWidgets import QApplication

    now = int(time.time()) // 1800 * 1800 + 1200
    events = schedule(now)

    class Backend:
        def stream_url(self, channel, profile=None):
            return f'http://192.0.2.1:9981/stream/channel/{channel.uuid}'

        def query_epg(self, query):
            return [e for e in events if e.stop > query.ends_after and e.start < query.starts_before]

        def close(self):
            pass

        def __getattr__(self, name):
            return lambda *a, **k: []

    store = ConfigStore(home / 'tvhplayer.conf')
    store.data['own_title_bar'] = True
    ui.ConfigStore = lambda *a, **k: store
    ui.windows_backend_enabled = lambda: False
    ui.default_picon_dir = lambda: home / 'picons'
    ui.TVHeadendClient._new_player = lambda self: FakePlayer()
    ui.TVHeadendClient.fetch_channels = lambda self, keep_place=False: None
    window_frame.wants_own_title_bar = lambda *a, **k: True
    guide_view.create_backend = lambda server: Backend()

    fake_files()
    app = QApplication.instance() or QApplication([])
    ui_theme.apply(app, ui_theme.THEME_ORGANIC)
    channels = [Channel(uuid=f'c{i}', name=name, number=i + 1) for i, (name, _t) in enumerate(CHANNELS)]
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
        server = {'name': 'Living Room', 'url': 'http://192.0.2.1:9981'}
        window.servers = [server]
        window.current_server = lambda: server
        window.server_combo.blockSignals(True)
        window.server_combo.clear()
        window.server_combo.addItem(server['name'])
        window.server_combo.blockSignals(False)
        now_next = {}
        for channel in channels:
            mine = [e for e in events if e.channel_uuid == channel.uuid]
            current = next(e for e in mine if e.start <= now < e.stop)
            following = mine[mine.index(current) + 1]
            now_next[channel.uuid] = NowNext(current, following)
        fetch = types.SimpleNamespace(server=server, key=ui.server_key(server), backend=None,
                                      keep_place=False, _now_next=True, deleteLater=lambda: None)
        window._channel_fetch = fetch
        window._on_channels_loaded(fetch, {'channels': channels, 'tags': [], 'services': [], 'now_next': now_next})
        window.show()
        settle(app)
        window.play_channel_by_data(channels[[c.name for c in channels].index(PLAYING)])
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
        jobs = []
        for index, (name, fmt) in enumerate(RECORDINGS):
            path = f'{FOLDER}/' + ui.local_recording_name(name, datetime.fromtimestamp(now - 600), fmt)
            recorder = types.SimpleNamespace(is_running=True, file_path=path, started_at=time.time() - 300 - 170 * index,
                                             stall_count=0)
            jobs.append(ui.LocalJob(recorder, channels[[c.name for c in channels].index(name)]))
            SIZES[path] = (380 - 90 * index) * 1024 * 1024
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

        window.show_guide(channels[[c.name for c in channels].index(PLAYING)])
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

"""Made-up channels, programmes, logos and recordings for showing TVHplayer.

Shared by capture_ui.py (the intro video) and screenshot_demo.py (store
screenshots). Nothing here is a real broadcaster: the channels follow the
website's examples, and the logos are drawn here.
"""

import os
import time
import types
from datetime import datetime
from pathlib import Path

CHANNELS = [
    ('News 24', ['Evening Headlines', 'Business Hour', 'World Tonight', 'Late Edition']),
    ('Capital TV', ['City Life', 'The Late Show', 'Night Desk', 'Replay']),
    ('Cinema One', ['The Long Voyage', 'Midnight Movie', 'Film Club']),
    ('World News', ['Global Report', 'Weather', 'Global Report', 'Markets']),
    ('Sports Live', ['Match of the Week', 'Highlights', 'Extra Time']),
    ('Nature HD', ['Wild Coasts', 'Ocean Giants', 'Night Forest', 'Rivers']),
    ('Kids Club', ['Cartoon Hour', 'Story Time', 'Puzzle Quest', 'Goodnight']),
    ('Music Hits', ['Live Sessions', 'Top 40 Countdown', 'Throwback']),
    ('Comedy Plus', ['Stand-up Night', 'Sketch Show', 'Sitcom Classics']),
    ('Science Now', ['Space Frontiers', 'How It Works', 'Big Ideas']),
    ('Travel & Taste', ['Street Food Tour', 'Island Hopping', 'Slow Trains']),
    ('Classic Films', ['Silver Screen', 'Double Feature']),
    ('Weather Today', ['Forecast', 'Climate Watch', 'Forecast', 'Outlook']),
    ('Radio Lounge', ['Chill Mix', 'Night Grooves', 'Deep Cuts']),
    ('Jazz FM', ['Late Jazz', 'Blue Notes', 'Standards']),
    ('Talk Radio', ['Phone-in', 'Night Talk', 'Morning Early']),
]

DESCRIPTIONS = {
    'Wild Coasts': 'Seals, puffins and winter storms along a rugged shore.',
    'Space Frontiers': 'Earth from the International Space Station, filmed by the crews of Expeditions 67 and 68.',
    'Live Sessions': 'Tonight’s guests play their new album live on stage, with an encore from the archive.',
}

# Each channel's logo: an emblem in a 175 by 100 box, the shape of the
# channel list's 56 by 32 logo space. Bold shapes, so they read that small
# and on light and dark rows alike.
LOGOS = {
    'News 24': '''<circle cx="87.5" cy="50" r="44" fill="#d93a3a"/>
        <text x="87.5" y="68" text-anchor="middle" font-family="Noto Sans" font-weight="700" font-size="50" fill="#fff">24</text>''',
    'Capital TV': '''<path d="M120 22 A40 40 0 1 0 120 78" fill="none" stroke="#2f80ed" stroke-width="20" stroke-linecap="round"/>
        <circle cx="128" cy="50" r="11" fill="#ff8a3d"/>''',
    'Cinema One': '''<circle cx="87.5" cy="50" r="44" fill="#7c3aed"/>
        <g fill="#ede9fe"><circle cx="87.5" cy="24" r="9"/><circle cx="87.5" cy="76" r="9"/><circle cx="61.5" cy="50" r="9"/><circle cx="113.5" cy="50" r="9"/></g>
        <circle cx="87.5" cy="50" r="7" fill="#c4b5fd"/>''',
    'World News': '''<circle cx="87.5" cy="50" r="44" fill="#0f766e"/>
        <g fill="none" stroke="#ccfbf1" stroke-width="5"><ellipse cx="87.5" cy="50" rx="18" ry="44"/><path d="M43.5 50h88M50 28h75M50 72h75"/></g>''',
    'Sports Live': '''<path d="M14 34h26M8 50h30M14 66h26" stroke="#f59e0b" stroke-width="8" stroke-linecap="round"/>
        <circle cx="98" cy="50" r="42" fill="#f59e0b"/>
        <g fill="none" stroke="#fff" stroke-width="5"><path d="M98 8v84"/><path d="M58 36 q40 18 80 0"/><path d="M58 64 q40 -18 80 0"/></g>''',
    'Nature HD': '''<path d="M45 88 C45 40 85 10 135 12 C138 60 105 92 55 90 Z" fill="#16a34a"/>
        <path d="M50 86 C70 60 95 40 122 24" fill="none" stroke="#dcfce7" stroke-width="6" stroke-linecap="round"/>''',
    'Kids Club': '''<circle cx="60" cy="58" r="30" fill="#ec4899"/><circle cx="115" cy="58" r="30" fill="#22c55e"/>
        <path d="M87.5 8 l10 21 23 3 -17 16 4 23 -20 -11 -20 11 4 -23 -17 -16 23 -3z" fill="#facc15" stroke="#fff" stroke-width="4"/>''',
    'Music Hits': '''<circle cx="87.5" cy="50" r="44" fill="#db2777"/>
        <path d="M76 70V30l34-8v40" fill="none" stroke="#fff" stroke-width="7" stroke-linejoin="round"/>
        <circle cx="69" cy="70" r="10" fill="#fff"/><circle cx="103" cy="62" r="10" fill="#fff"/>''',
    'Comedy Plus': '''<circle cx="80" cy="50" r="42" fill="#f97316"/>
        <circle cx="66" cy="40" r="6" fill="#fff"/><circle cx="94" cy="40" r="6" fill="#fff"/>
        <path d="M58 58 Q80 80 102 58" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round"/>
        <path d="M138 26v24M126 38h24" stroke="#f97316" stroke-width="8" stroke-linecap="round"/>''',
    'Science Now': '''<circle cx="87.5" cy="50" r="30" fill="#0891b2"/>
        <path d="M60 46 q27 10 55 0" fill="none" stroke="#67e8f9" stroke-width="5"/>
        <ellipse cx="87.5" cy="54" rx="62" ry="15" fill="none" stroke="#f59e0b" stroke-width="7" transform="rotate(-14 87.5 54)"/>
        <path d="M58 36 a30 30 0 0 1 59 0" fill="#0891b2"/>''',
    'Travel & Taste': '''<path d="M30 52 L145 14 L105 88 L85 62 Z" fill="#ca8a04"/><path d="M85 62 L145 14 L72 58 Z" fill="#a16207"/>
        <path d="M85 62 L80 84 L96 72" fill="#ca8a04"/>''',
    'Classic Films': '''<rect x="38" y="40" width="100" height="52" rx="6" fill="#3f3f46"/>
        <path d="M38 22 L134 8 L137 26 L41 40 Z" fill="#3f3f46"/>
        <path d="M58 19 L72 35 M82 15 L96 32 M106 12 L120 28" stroke="#fafafa" stroke-width="7"/>
        <circle cx="88" cy="66" r="12" fill="#eab308"/>''',
    'Weather Today': '''<circle cx="70" cy="40" r="26" fill="#facc15"/>
        <path d="M60 86 h66 a20 20 0 0 0 0 -40 a28 28 0 0 0 -52 6 a17 17 0 0 0 -14 34z" fill="#e0f2fe" stroke="#0284c7" stroke-width="5"/>''',
    'Radio Lounge': '''<circle cx="87.5" cy="50" r="44" fill="#2e1065"/>
        <g fill="none" stroke="#7c3aed" stroke-width="3"><circle cx="87.5" cy="50" r="36"/><circle cx="87.5" cy="50" r="29"/><circle cx="87.5" cy="50" r="22"/></g>
        <circle cx="87.5" cy="50" r="13" fill="#a78bfa"/><circle cx="87.5" cy="50" r="3" fill="#2e1065"/>''',
    'Jazz FM': '''<rect x="22" y="14" width="131" height="72" rx="36" fill="#1e3a8a"/>
        <text x="87.5" y="65" text-anchor="middle" font-family="Noto Sans" font-style="italic" font-weight="700" font-size="40" fill="#fbbf24">jazz</text>''',
    'Talk Radio': '''<path d="M30 14 h115 a12 12 0 0 1 12 12 v38 a12 12 0 0 1 -12 12 h-70 l-24 18 v-18 h-21 a12 12 0 0 1 -12 -12 v-38 a12 12 0 0 1 12 -12z" fill="#475569"/>
        <g fill="#fff"><circle cx="62" cy="45" r="8"/><circle cx="87.5" cy="45" r="8"/><circle cx="113" cy="45" r="8"/></g>''',
}

# Local recordings shown in Tasks: a made-up folder, sizes given here.
FOLDER = '/home/you/Videos'
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


def make_logos(folder):
    """Draw each channel's logo as a picon, which the app finds by channel name."""
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    from tvhplayer.core.picons import picon_key

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, shapes in LOGOS.items():
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 175 100">{shapes}</svg>'
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        image = QImage(350, 200, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        image.save(str(folder / f'{picon_key(name)}.png'))
    return folder


def channels():
    from tvhplayer.core.models import Channel

    return [Channel(uuid=f'c{i}', name=name, number=i + 1) for i, (name, _t) in enumerate(CHANNELS)]


def find(channel_list, name):
    return next(c for c in channel_list if c.name == name)


class Backend:
    """The server's side: the guide, and ``stream`` as every channel's picture."""

    def __init__(self, events, stream='http://192.0.2.1:9981/stream'):
        self.events = events
        self.stream = stream

    def stream_url(self, channel, profile=None):
        return self.stream

    def query_epg(self, query):
        return [e for e in self.events if e.stop > query.ends_after and e.start < query.starts_before]

    def close(self):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: []


class DemoRecorder:
    """A recording to this computer that is going well, without ffmpeg."""

    def __init__(self, file_path, started_at):
        self.file_path = file_path
        self.started_at = started_at
        self.stall_count = 0
        self.is_running = True

    def status(self):
        from tvhplayer.core.recorder import RecorderStatus

        return RecorderStatus(file_path=self.file_path, exists=True, size=SIZES.get(self.file_path, 0),
                              elapsed=time.time() - self.started_at, running=True, stalled=False, return_code=None)

    def stop(self):
        self.is_running = False


def load(window, ui, channel_list, events, now, server):
    """Give the main window ``server``'s channels with now and next, as a channel load does."""
    from tvhplayer.core.channel_info import NowNext

    window.servers = [server]
    window.current_server = lambda: server
    window.server_combo.blockSignals(True)
    window.server_combo.clear()
    window.server_combo.addItem(server['name'])
    window.server_combo.blockSignals(False)
    now_next = {}
    for channel in channel_list:
        mine = [e for e in events if e.channel_uuid == channel.uuid]
        current = next(e for e in mine if e.start <= now < e.stop)
        following = mine[mine.index(current) + 1]
        now_next[channel.uuid] = NowNext(current, following)
    fetch = types.SimpleNamespace(server=server, key=ui.server_key(server), backend=None,
                                  keep_place=False, _now_next=True, deleteLater=lambda: None)
    window._channel_fetch = fetch
    window._on_channels_loaded(fetch, {'channels': channel_list, 'tags': [], 'services': [], 'now_next': now_next})


def recordings(ui, channel_list, now, wanted):
    """Local jobs recording ``wanted`` (channel name, format) pairs, with made-up sizes."""
    jobs = []
    for index, (name, fmt) in enumerate(wanted):
        path = f'{FOLDER}/' + ui.local_recording_name(name, datetime.fromtimestamp(now - 600), fmt)
        SIZES[path] = (380 - 90 * index) * 1024 * 1024
        jobs.append(ui.LocalJob(DemoRecorder(path, time.time() - 300 - 170 * index), find(channel_list, name)))
    return jobs

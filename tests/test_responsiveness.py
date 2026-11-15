"""Does the window keep answering while the app works?

A heartbeat timer ticks every few milliseconds on the window's thread. Any
gap between two ticks is a time the window could not repaint or take a key or
click. Each test starts an action from the event loop, as a click would, and
measures the longest gap while it runs.

Two kinds of work are measured:

* Server requests, against a fake server that takes a second to answer. A
  request made on the window's thread shows up as a gap of about a second.
* Work on a big channel list (60,000 channels): live updates from the
  server and typing in the search box.

Run with ``-s`` to see the measured pauses.
"""

import threading
import time
import types

import pytest

from test_pyqt6_ui import _make_player, _wait_until

# How long the fake server takes to answer.
SERVER_DELAY = 1.0
# The longest pause allowed while waiting for a server: well under its delay,
# well over what a busy test machine adds by itself.
SERVER_BUDGET = 0.3
# The longest pause allowed for work on the channel list. Pauses of 100 ms
# are felt when typing or scrolling; 50 ms leaves room for a slower computer.
LIST_BUDGET = 0.05
# The share of the time the window may spend on live updates to the list.
LIST_BUSY_BUDGET = 0.2
# Typing a search: most keys take under 10 ms with 60,000 channels and the
# slowest 40-100 ms, so this only catches searching getting slower.
SEARCH_BUDGET = 0.2
BIG_LIST = 60_000

BLOCKS_ON_LIST = pytest.mark.xfail(
    strict=True,
    reason='Reworks the whole channel list on the window thread (to be fixed); remove this mark when it passes',
)


class StallMeter:
    """Gaps between ticks of a timer on the window's thread."""

    def __init__(self, interval_ms=5):
        from PyQt6.QtCore import QTimer

        self.interval = interval_ms / 1000
        self.ticks = []
        self.timer = QTimer()
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(lambda: self.ticks.append(time.perf_counter()))

    def run(self, seconds, until=None):
        """Run the event loop for ``seconds``, or until ``until()`` is true after at least one tick."""
        from PyQt6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        self.ticks.append(time.perf_counter())
        self.timer.start()
        deadline = time.monotonic() + seconds
        check = QTimer()
        check.setInterval(10)

        def done():
            if time.monotonic() >= deadline or (until is not None and until()):
                loop.quit()

        check.timeout.connect(done)
        check.start()
        loop.exec()
        check.stop()
        self.timer.stop()
        self.ticks.append(time.perf_counter())

    def gaps(self):
        return sorted(b - a for a, b in zip(self.ticks, self.ticks[1:]))

    def worst(self):
        gaps = self.gaps()
        return gaps[-1] if gaps else 0.0

    def percentile(self, p):
        gaps = self.gaps()
        if not gaps:
            return 0.0
        return gaps[min(len(gaps) - 1, int(len(gaps) * p))]

    def busy(self):
        """The share of the time the window spent away from the heartbeat."""
        span = self.ticks[-1] - self.ticks[0] if len(self.ticks) > 1 else 0.0
        if span <= 0:
            return 0.0
        return max(0.0, 1.0 - (len(self.ticks) - 1) * self.interval / span)

    def report(self, what):
        print(f"\n{what}: worst pause {self.worst() * 1000:.0f} ms, busy {self.busy():.0%}, "
              f"p95 {self.percentile(0.95) * 1000:.0f} ms, "
              f"p99 {self.percentile(0.99) * 1000:.0f} ms, {len(self.ticks)} ticks")


def _later(action):
    """Start ``action`` from the event loop, as a click or key press would."""
    from PyQt6.QtCore import QTimer

    QTimer.singleShot(0, action)


class _SlowServer:
    """A remote server that takes ``SERVER_DELAY`` to answer every request."""

    def __init__(self, delay=SERVER_DELAY):
        from tvhplayer.core.models import DvrEntry

        self.delay = delay
        self.calls = []
        now = int(time.time())
        self.entries = [DvrEntry(
            uuid='run', title='News', channel_name='News', start=now - 60, duration=3600,
            status='Running', sched_status='recording', htsp_id=7,
        )]

    def _wait(self, name):
        self.calls.append(name)
        time.sleep(self.delay)

    def stream_url(self, channel, profile=None):
        self._wait('stream_url')
        return f'http://tv.example/stream/{channel.uuid}?ticket=t'

    def get_now_next(self, channels):
        self._wait('get_now_next')
        return {}

    def create_dvr_entry(self, channel, start, stop, **kwargs):
        self._wait('create_dvr_entry')
        return {'uuid': 'new'}

    def create_dvr_entry_by_event(self, event_id):
        self._wait('create_dvr_entry_by_event')
        return {'uuid': 'new'}

    def list_dvr_entries(self):
        self._wait('list_dvr_entries')
        return list(self.entries)

    def stop_dvr_entry(self, entry):
        self._wait('stop_dvr_entry')
        self.entries = []

    def get_epg(self, channel, limit=None):
        from tvhplayer.core.models import EpgEvent

        self._wait('get_epg')
        now = int(time.time())
        return [EpgEvent(start=now, stop=now + 600, title='Headlines', channel_uuid=channel.uuid, event_id=1)]

    def image_url(self, reference):
        self._wait('image_url')
        return f'http://tv.example/{reference}'

    def cancel_dvr_entry(self, entry):
        self._wait('cancel_dvr_entry')

    def create_autorec_by_series(self, event_id, config_uuid=''):
        self._wait('create_autorec_by_series')
        return 'rule'

    def query_epg(self, query):
        # The guide reads its programmes on a thread of its own already.
        return []

    def close(self):
        pass


def _remote_window(monkeypatch, tmp_path):
    """The window on a remote HTTP server that answers slowly."""
    from tvhplayer.core.models import Channel

    app, ui, window, player = _make_player(monkeypatch, tmp_path)
    backend = _SlowServer()
    server = {'name': 'tv', 'url': 'http://tv.example:9981', 'protocol': 'http'}
    window.current_server = lambda: server
    window._server_requests_ready = lambda: True
    window.get_backend = lambda: backend
    window.open_backend = lambda srv: backend
    window.tasks_pane.open_backend = lambda srv: backend
    window.tasks_pane.update_timer.stop()
    # Threads that follow the server's log and status while a channel starts:
    # not what is measured here.
    window._watch_stream_log = lambda: None
    window._watch_start = lambda: None
    window._refresh_tasks = lambda: None
    channel = Channel(uuid='news', name='News', number=1, htsp_id=7)
    window.selected_channel = lambda: channel
    window.active_channel = lambda: channel
    played = []
    play = player.play
    player.play = lambda url: (played.append(url), play(url))
    window.show()
    app.processEvents()
    return app, ui, window, backend, channel, played


def _close(app, window):
    window.close()
    app.processEvents()


# --- Waiting for the server -------------------------------------------------


def test_playing_a_channel_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    try:
        meter = StallMeter()
        _later(lambda: window.play_channel_by_data(channel))
        meter.run(SERVER_DELAY * 3, until=lambda: bool(played))
        meter.report('Play a channel, server answers in 1 s')
        assert played == ['http://tv.example/stream/news?ticket=t']
        assert meter.worst() < SERVER_BUDGET
    finally:
        _close(app, window)


def test_a_late_stream_address_for_an_earlier_channel_is_dropped(monkeypatch, tmp_path):
    # Zapping on a slow server: the first channel's address comes in after
    # the second was chosen, and must not start the first channel.
    from tvhplayer.core.models import Channel

    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    sport = Channel(uuid='sport', name='Sport', number=2, htsp_id=8)
    delays = {'news': SERVER_DELAY, 'sport': 0.1}

    def stream_url(channel, profile=None):
        time.sleep(delays[channel.uuid])
        return f'http://tv.example/stream/{channel.uuid}'

    backend.stream_url = stream_url
    try:
        window.play_channel_by_data(channel)
        window.play_channel_by_data(sport)
        _wait_until(app, lambda: bool(played), 'the second channel starting')
        assert played == ['http://tv.example/stream/sport']
        meter = StallMeter()
        meter.run(SERVER_DELAY + 0.3)
        assert played == ['http://tv.example/stream/sport']
        assert window._playback_channel is sport
    finally:
        _close(app, window)


def test_stopping_while_the_stream_address_is_on_its_way_plays_nothing(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    backend.delay = 0.3
    try:
        window.play_channel_by_data(channel)
        assert window._awaiting_playback
        window.stop_playback()
        StallMeter().run(0.6)
        assert played == []
        assert not window._awaiting_playback
        assert window._playback_channel is None
    finally:
        _close(app, window)


def test_a_server_that_cannot_give_a_stream_address_is_reported(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)

    def stream_url(channel, profile=None):
        raise ui.TvhError('Server not reachable')

    backend.stream_url = stream_url
    try:
        window.play_channel_by_data(channel)
        _wait_until(app, lambda: not window._awaiting_playback, 'the failure')
        assert played == []
        assert window._playback_channel is None
        assert window.status_label.text() == 'Playback error: Server not reachable'
        assert not window.playback_spinner.isVisible()
    finally:
        _close(app, window)


def test_starting_a_recording_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)

    class Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_duration(self):
            return 1800

        def programme_event(self):
            return None

    monkeypatch.setattr(ui, 'RecordingDurationDialog', Dialog)
    try:
        meter = StallMeter()
        _later(window.start_recording)
        meter.run(SERVER_DELAY * 4, until=lambda: window.is_recording)
        meter.report('Record, server answers in 1 s')
        assert 'create_dvr_entry' in backend.calls
        assert window.is_recording
        assert meter.worst() < SERVER_BUDGET
    finally:
        _close(app, window)


def test_stopping_a_recording_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    try:
        window.start_recording_indicator()
        meter = StallMeter()
        _later(window.stop_recording)
        meter.run(SERVER_DELAY * 4, until=lambda: not window.is_recording)
        meter.report('Stop recording, server answers in 1 s')
        assert backend.calls[:2] == ['list_dvr_entries', 'stop_dvr_entry']
        assert meter.worst() < SERVER_BUDGET
    finally:
        _close(app, window)


def test_a_server_that_cannot_record_is_reported(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)

    class Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_duration(self):
            return 1800

        def programme_event(self):
            return None

    def refuse(*_args, **_kwargs):
        raise ui.TvhError('No free tuner')

    monkeypatch.setattr(ui, 'RecordingDurationDialog', Dialog)
    backend.delay = 0.05
    backend.create_dvr_entry = refuse
    try:
        window.start_recording()
        _wait_until(app, lambda: not window._asking_to_record, 'the answer')
        assert window.status_label.text() == 'Recording error: No free tuner'
        assert not window.is_recording
        # The next try is not refused as still waiting.
        window.start_recording()
        assert window._asking_to_record
        _wait_until(app, lambda: not window._asking_to_record, 'the second answer')
    finally:
        _close(app, window)


def test_stopping_when_nothing_records_says_so(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    backend.delay = 0.05
    backend.entries = []
    try:
        window.stop_recording()
        assert window.status_label.text() == 'Stopping recording'
        _wait_until(app, lambda: not window._stopping_recording, 'the answer')
        assert window.status_label.text() == 'No active recordings to stop'
        assert backend.calls == ['list_dvr_entries']
    finally:
        _close(app, window)


def test_a_guide_the_server_cannot_give_is_reported(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)

    def refuse(*_args, **_kwargs):
        raise ui.TvhError('Server not reachable')

    backend.get_epg = refuse
    monkeypatch.setattr(ui, 'EPGDialog', lambda *a, **k: pytest.fail('showed a guide'))
    try:
        window.show_channel_epg(channel)
        _wait_until(app, lambda: 'Error' in window.status_label.text(), 'the failure')
        assert window.status_label.text() == 'Error fetching EPG: Server not reachable'
    finally:
        _close(app, window)


def test_opening_a_channel_guide_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    shown = []

    class Dialog:
        def __init__(self, channel, events, *_args, **_kwargs):
            shown.append([event.title for event in events])

        def show(self):
            pass

    monkeypatch.setattr(ui, 'EPGDialog', Dialog)
    try:
        meter = StallMeter()
        _later(lambda: window.show_channel_epg(channel))
        meter.run(SERVER_DELAY * 3, until=lambda: bool(shown))
        meter.report('Channel guide, server answers in 1 s')
        assert shown == [['Headlines']]
        assert meter.worst() < SERVER_BUDGET
    finally:
        _close(app, window)


def test_finding_a_logo_address_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    requested = []
    window.logo_loader = ui.LogoLoader(window, cache_dir=tmp_path / 'cache')
    window.logo_loader._fetch = lambda server, url: requested.append(url)
    try:
        meter = StallMeter()
        _later(lambda: window._logo_for('imagecache/1', backend))
        meter.run(SERVER_DELAY * 3, until=lambda: bool(requested))
        meter.report('Logo address, server answers in 1 s')
        assert requested == ['http://tv.example/imagecache/1']
        assert meter.worst() < SERVER_BUDGET
    finally:
        _close(app, window)



class _LocalRecorder:
    """Stand-in for ffmpeg recording a stream to a file."""

    def __init__(self):
        self.started = []
        self.is_running = False
        self.file_path = None

    def start(self, url, path, username, password, options):
        self.started.append(url)
        self.file_path = path
        self.is_running = True

    def stop(self):
        self.is_running = False


def test_recording_to_this_computer_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)

    class Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return ui.QDialog.DialogCode.Accepted

        def get_duration(self):
            return 1800

        def programme_event(self):
            return None

        def records_from_buffer(self):
            return False

    monkeypatch.setattr(ui, 'RecordingDurationDialog', Dialog)
    recorder = _LocalRecorder()
    window.new_local_recorder = lambda: recorder
    window.set_local_recording_dir(str(tmp_path / 'videos'))
    try:
        meter = StallMeter()
        _later(lambda: window.start_local_recording(channel))
        meter.run(SERVER_DELAY * 4, until=lambda: bool(window.local_jobs))
        meter.report('Record to this computer, server answers in 1 s')
        assert backend.calls == ['get_now_next', 'stream_url']
        assert recorder.started == ['http://tv.example/stream/news?ticket=t']
        assert meter.worst() < SERVER_BUDGET
    finally:
        # Closing with a recording running would ask whether to stop it.
        for job in list(window.local_jobs):
            job.timer.stop()
            job.recorder.stop()
        window.local_jobs.clear()
        if window.recording_monitor is not None:
            window.recording_monitor.stop()
        _close(app, window)


def test_scheduling_from_a_channel_guide_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    from tvhplayer.core.models import EpgEvent

    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    told = []
    monkeypatch.setattr(ui.QMessageBox, 'information', lambda *args: told.append(args[2]))
    monkeypatch.setattr(ui.QMessageBox, 'critical', lambda *args: told.append(args[2]))
    now = int(time.time())
    later = EpgEvent(start=now + 600, stop=now + 1200, title='Weather', channel_uuid='news', event_id=2)
    guide = ui.EPGDialog(channel, [later], backend, window)
    try:
        meter = StallMeter()
        _later(lambda: guide.schedule_recording(later))
        meter.run(SERVER_DELAY * 3, until=lambda: bool(told))
        meter.report('Record from the channel guide, server answers in 1 s')
        assert told == ['Recording scheduled successfully for Weather']
        assert backend.calls == ['create_dvr_entry']
        assert meter.worst() < SERVER_BUDGET
    finally:
        guide.close()
        _close(app, window)


def _tv_guide(monkeypatch, ui, window, backend):
    import tvhplayer.guide_view as guide_view
    from tvhplayer.core.models import Channel, DvrEntry, EpgEvent

    monkeypatch.setattr(guide_view, 'create_backend', lambda server: backend)
    now = int(time.time())
    channel = Channel(uuid='news', name='News', number=1, htsp_id=7)
    on_now = EpgEvent(start=now - 600, stop=now + 600, title='Headlines', channel_uuid='news',
                      event_id=1, dvr_uuid='run', serieslink_uri='crid://news')
    later = EpgEvent(start=now + 600, stop=now + 1200, title='Weather', channel_uuid='news',
                     event_id=2, serieslink_uri='crid://weather')
    window._dvr_entries = [DvrEntry(uuid='run', title='Headlines', channel_name='News', start=now - 600,
                                    duration=1200, status='Running', sched_status='recording', htsp_id=7)]
    guide = guide_view.GuideWindow(window)
    return guide_view, guide, channel, on_now, later


@pytest.mark.parametrize('action', ['record', 'stop', 'series'])
def test_recording_from_the_tv_guide_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path, action):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    guide_view, guide, channel, on_now, later = _tv_guide(monkeypatch, ui, window, backend)
    try:
        if action == 'record':
            run = lambda: guide.toggle_recording(channel, later)
            wanted, said = 'create_dvr_entry_by_event', 'Scheduled Weather on News'
        elif action == 'stop':
            guide._overrides[on_now.event_id] = guide_view.RECORDING
            run = lambda: guide.toggle_recording(channel, on_now)
            wanted, said = 'stop_dvr_entry', 'Stopped recording Headlines'
        else:
            run = lambda: guide.record_series(later)
            wanted, said = 'create_autorec_by_series', 'Recording every episode of Weather'
        meter = StallMeter()
        _later(run)
        meter.run(SERVER_DELAY * 3, until=lambda: said in window.status_label.text())
        meter.report(f'TV guide: {action}, server answers in 1 s')
        assert wanted in backend.calls
        assert said in window.status_label.text()
        assert meter.worst() < SERVER_BUDGET
    finally:
        guide.close()
        _close(app, window)


def test_pressing_record_twice_in_the_tv_guide_asks_the_server_once(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    guide_view, guide, channel, on_now, later = _tv_guide(monkeypatch, ui, window, backend)
    backend.delay = 0.3
    try:
        guide.toggle_recording(channel, later)
        guide.toggle_recording(channel, later)
        assert window.status_label.text() == 'Still waiting for the server'
        _wait_until(app, lambda: 'Scheduled Weather' in window.status_label.text(), 'the answer')
        assert backend.calls.count('create_dvr_entry_by_event') == 1
        assert guide._state(later) == guide_view.SCHEDULED
    finally:
        guide.close()
        _close(app, window)

# --- A big channel list ------------------------------------------------------


def _big_htsp_window(monkeypatch, tmp_path, count=BIG_LIST):
    """The window showing ``count`` channels from an HTSP server that sends live updates."""
    from tvhplayer.core.htsp_backend import HtspBackend
    from tvhplayer.core.models import ServerConfig

    app, ui, window, _ = _make_player(monkeypatch, tmp_path)
    backend = HtspBackend(ServerConfig(name='HTSP', url='http://127.0.0.1:9981', protocol='htsp'))
    server = {'name': 'HTSP', 'url': 'http://127.0.0.1:9981', 'protocol': 'htsp'}
    window.servers = [server]
    window.server_combo.blockSignals(True)
    window.server_combo.addItem('HTSP')
    window.server_combo.setCurrentIndex(0)
    window.server_combo.blockSignals(False)
    window.channel_options['logos'] = False
    fetch = types.SimpleNamespace(server=dict(server), backend=backend, key=ui.server_key(server),
                                  keep_place=False, _now_next=False, deleteLater=lambda: None)
    window._channel_fetch = fetch
    for number in range(1, count + 1):
        backend._on_async({'method': 'channelAdd', 'channelId': number, 'channelName': f'Channel {number}',
                           'channelNumber': number, 'eventId': number * 10, 'nextEventId': number * 10 + 1})
    backend._on_async({'method': 'initialSyncCompleted'})
    window._on_channels_loaded(fetch, {'channels': [], 'tags': [], 'services': [], 'now_next': None})
    assert window.channel_model.rowCount() == count
    window.show()
    app.processEvents()
    return app, ui, window, backend


@BLOCKS_ON_LIST
def test_programme_changes_on_a_big_list_keep_the_window_answering(monkeypatch, tmp_path):
    # Tvheadend sends a channelUpdate whenever a channel's programme changes.
    # With tens of thousands of channels that is a steady stream; none of
    # them moves a row.
    from PyQt6.QtCore import QTimer

    app, ui, window, backend = _big_htsp_window(monkeypatch, tmp_path)
    try:
        sent = [0]

        def send():
            for _ in range(5):
                sent[0] += 1
                number = sent[0] * 97 % BIG_LIST + 1
                backend._on_async({'method': 'channelUpdate', 'channelId': number,
                                   'eventId': number * 10 + sent[0], 'nextEventId': number * 10 + sent[0] + 1})

        feeder = QTimer()
        feeder.setInterval(100)
        feeder.timeout.connect(send)
        feeder.start()
        meter = StallMeter()
        meter.run(3.0)
        feeder.stop()
        meter.report(f'Programme changes, {BIG_LIST:,} channels, 50 a second')
        assert sent[0] >= 100
        assert backend.take_channel_changes()[0] == {}
        assert meter.busy() < LIST_BUSY_BUDGET
        assert meter.worst() < LIST_BUDGET
    finally:
        window._channel_fetch = None
        backend.close()
        _close(app, window)


def test_typing_a_search_on_a_big_list_keeps_the_window_answering(monkeypatch, tmp_path):
    from PyQt6.QtCore import QTimer

    app, ui, window, backend = _big_htsp_window(monkeypatch, tmp_path)
    try:
        word = 'channel 47111'
        typed = [0]

        def type_one():
            typed[0] += 1
            window.search_box.setText(word[:typed[0]])
            if typed[0] == len(word):
                keys.stop()

        keys = QTimer()
        keys.setInterval(120)
        keys.timeout.connect(type_one)
        keys.start()
        meter = StallMeter()
        meter.run(len(word) * 0.12 + 1.0)
        meter.report(f'Typing a search, {BIG_LIST:,} channels')
        assert typed[0] == len(word)
        assert window.channel_model.rowCount() == 1
        assert meter.worst() < SEARCH_BUDGET
    finally:
        window._channel_fetch = None
        backend.close()
        _close(app, window)


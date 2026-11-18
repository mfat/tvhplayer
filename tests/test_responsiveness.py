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

from test_pyqt6_ui import _load_channels, _make_player, _wait_until

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
# Thousands of changes at once, as on the hour: rare, so a longer pause is
# allowed. They take 35-115 ms alone and up to 160 ms during the whole test
# run; looking through every row for each change took over a second.
LIST_BURST_BUDGET = 0.25
BIG_LIST = 60_000



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


def test_background_guide_scan_keeps_the_window_answering(tmp_path):
    # An unwanted ID sharing a prefix with thousands of wanted IDs made
    # the regex hold the GIL for seconds, blocking the Qt thread too.
    from tvhplayer.core.guide_feeds import wanted_programmes

    path = tmp_path / 'guide.xml'
    path.write_bytes(
        b'<tv>'
        + b'<programme channel="Channel09999.test"><title>Skip</title></programme>' * 30_000
        + b'<programme channel="Channel00000.test"><title>Keep</title></programme></tv>'
    )
    wanted = {f'Channel{i:05d}.test' for i in range(9_999)}
    titles = []
    done = threading.Event()

    def scan():
        try:
            titles.extend(el.findtext('title') for el in wanted_programmes(str(path), wanted))
        finally:
            done.set()

    worker = threading.Thread(target=scan)
    meter = StallMeter()
    _later(worker.start)
    try:
        meter.run(10, until=done.is_set)
    finally:
        worker.join()
    meter.report('Background guide scan with 9,999 wanted channels')
    assert titles == ['Keep']
    assert meter.worst() < SERVER_BUDGET


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
        # The ring stops; the reason stays over the player, where it shows in fullscreen too.
        assert not window.playback_spinner._timer.isActive()
        assert window.playback_spinner.accessibleName() == 'Playback error: Server not reachable'
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

class _SlowStatusServer(_SlowServer):
    """The slow server, with what the Server Status window asks for."""

    def __init__(self, delay=SERVER_DELAY):
        super().__init__(delay)
        self.server = types.SimpleNamespace(to_dict=lambda: {
            'name': 'tv', 'url': 'http://tv.example:9981', 'protocol': 'http',
        })

    def get_server_info(self):
        self._wait('get_server_info')
        return types.SimpleNamespace(version='4.3', api_version=19, name='tv', capabilities=[])

    def get_inputs(self):
        self._wait('get_inputs')
        return [{'input': 'Tuner 1', 'signal': 52428, 'signal_scale': 1,
                 'snr': 30000, 'snr_scale': 2, 'stream': 'News', 'weight': 1}]

    def get_connections(self):
        self._wait('get_connections')
        return [{'peer': '10.0.0.2', 'user': 'tv', 'started': int(time.time()) - 5}]

    def get_subscriptions(self):
        self._wait('get_subscriptions')
        return [{'channel': 'News', 'username': 'tv', 'start': int(time.time()) - 5, 'state': 'Running'}]


def test_opening_dvr_status_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    dialogs = []
    try:
        meter = StallMeter()
        _later(lambda: dialogs.append(ui.DVRStatusDialog(backend, window, server=window.current_server())))
        meter.run(SERVER_DELAY * 3, until=lambda: dialogs and dialogs[0].upcoming_table.rowCount() == 1)
        meter.report('Open DVR Status, server answers in 1 s')
        assert dialogs[0].upcoming_table.item(0, 1).text() == 'News'
        assert meter.worst() < SERVER_BUDGET

        # Its refresh every 5 seconds does not wait for the server either.
        calls = len(backend.calls)
        meter = StallMeter()
        _later(dialogs[0].update_timer.timeout.emit)
        meter.run(SERVER_DELAY * 3, until=lambda: len(backend.calls) > calls and not dialogs[0]._fetching)
        meter.report('Refresh DVR Status, server answers in 1 s')
        assert meter.worst() < SERVER_BUDGET
    finally:
        for dialog in dialogs:
            dialog.update_timer.stop()
            dialog.close()
        _close(app, window)


def test_refreshing_dvr_status_while_the_server_answers_asks_once(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    backend.delay = 0.3
    dialog = ui.DVRStatusDialog(backend, window, server=window.current_server())
    dialog.update_timer.stop()
    try:
        dialog.update_status()
        dialog.update_status()
        StallMeter().run(1.5, until=lambda: not dialog._fetching)
        # The first ask, then one more for the refreshes that came while it was out.
        assert backend.calls == ['list_dvr_entries', 'list_dvr_entries']
    finally:
        dialog.close()
        _close(app, window)


def test_opening_server_status_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    backend = _SlowStatusServer(delay=0.3)
    dialogs = []
    try:
        meter = StallMeter()
        _later(lambda: dialogs.append(ui.ServerStatusDialog(backend, window)))
        meter.run(3, until=lambda: dialogs and dialogs[0].subscriptions_table.rowCount() == 2)
        meter.report('Open Server Status, server answers each request in 0.3 s')
        dialog = dialogs[0]
        assert 'Server Version: 4.3' in dialog.info_text.toPlainText()
        assert dialog.signal_table.item(0, 1).text() == '80.0% (good)'
        assert dialog.subscriptions_table.item(1, 4).text() == 'Subscription (Running)'
        assert meter.worst() < SERVER_BUDGET
    finally:
        for dialog in dialogs:
            dialog.update_timer.stop()
            dialog.close()
        _close(app, window)


def test_choosing_the_recording_to_keep_on_a_slow_server_keeps_the_window_answering(monkeypatch, tmp_path):
    from tvhplayer.core.models import DvrEntry

    app, ui, window, backend, channel, played = _remote_window(monkeypatch, tmp_path)
    updates = []

    def update_dvr_entry(entry, update):
        backend._wait('update_dvr_entry')
        updates.append((entry.uuid, update.priority))

    backend.update_dvr_entry = update_dvr_entry
    entries = [
        DvrEntry(uuid='a', title='News', channel_name='BBC ONE', start=1_800_000_000, duration=3600),
        DvrEntry(uuid='b', title='Film', channel_name='ITV', start=1_800_001_800, duration=7200),
    ]
    dialog = ui.RecordingConflictDialog(entries, 1, window)
    dialog.list.setCurrentRow(1)
    try:
        meter = StallMeter()
        _later(lambda: window._conflict_answered(dialog, ui.QDialog.DialogCode.Accepted))
        meter.run(SERVER_DELAY * 3, until=lambda: 'most important' in window.statusbar.currentMessage())
        meter.report('Keep a recording, server answers in 1 s')
        assert updates == [('b', 0)]
        assert meter.worst() < SERVER_BUDGET
    finally:
        dialog.close()
        _close(app, window)


def test_quitting_while_the_builtin_server_is_slow_keeps_the_window_answering(monkeypatch, tmp_path):
    from tvhplayer.core.models import DvrEntry

    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    window.servers = [{
        'name': 'Built-in Server', 'url': 'http://127.0.0.1:24111', 'protocol': 'htsp',
        'username': 'tvhplayer', 'password': 'secret', 'builtin': True,
    }]
    window.builtin = types.SimpleNamespace(
        is_running=lambda: True, username='tvhplayer', password='secret',
        stop=lambda: None, shut_down=lambda: None,
    )

    class Backend:
        def __init__(self, server):
            pass

        def list_dvr_entries(self):
            time.sleep(SERVER_DELAY)
            return [DvrEntry(uuid='1', title='News Hour', channel_name='One', start=0, duration=60,
                             status='Running', sched_status='recording')]

        def close(self):
            pass

    monkeypatch.setattr(ui, 'create_backend', Backend)
    asked = []
    monkeypatch.setattr(
        ui.QMessageBox, 'question',
        lambda _parent, _title, text, *a: asked.append(text) or ui.QMessageBox.StandardButton.No,
    )
    window.show()
    app.processEvents()
    try:
        meter = StallMeter()
        _later(window.close)
        meter.run(SERVER_DELAY * 3, until=lambda: bool(asked))
        meter.report('Quit, built-in server answers in 1 s')
        assert 'News Hour' in asked[0]
        assert window.isVisible()
        assert meter.worst() < SERVER_BUDGET
    finally:
        window.builtin = None
        _close(app, window)


def test_removing_picons_keeps_the_window_answering(monkeypatch, tmp_path):
    # A full pack is some 44,000 files; deleting them on a slow disk takes seconds.
    import shutil

    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    folder = tmp_path / 'picons'
    folder.mkdir(exist_ok=True)
    (folder / 'bbcone.png').write_bytes(b'png')
    delete = shutil.rmtree

    def slow_delete(path, *args, **kwargs):
        time.sleep(SERVER_DELAY)
        delete(path, *args, **kwargs)

    monkeypatch.setattr(ui.shutil, 'rmtree', slow_delete)
    try:
        meter = StallMeter()
        _later(window.remove_picons)
        meter.run(SERVER_DELAY * 3, until=lambda: not any(tmp_path.glob('picons*')))
        meter.report('Remove picons, disk takes 1 s')
        assert not folder.exists()
        assert window.picons is None
        assert not any(tmp_path.glob('picons*'))
        assert meter.worst() < SERVER_BUDGET
    finally:
        _close(app, window)


def test_a_recordings_folder_on_a_slow_disk_keeps_the_window_answering(monkeypatch, tmp_path):
    # A network share that has gone away can take seconds, or for ever, to say how full it is.
    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    asked = []
    at_once = [0, 0]

    def slow_free_bytes(folder):
        asked.append(folder)
        at_once[0] += 1
        at_once[1] = max(at_once)
        time.sleep(SERVER_DELAY)
        at_once[0] -= 1
        return 1024 ** 3 // 2

    monkeypatch.setattr(ui, 'free_bytes', slow_free_bytes)
    window.config['local_recording_dir'] = str(tmp_path)
    window.show()
    app.processEvents()
    try:
        meter = StallMeter()
        _later(window._check_disk_space)
        meter.run(SERVER_DELAY * 3, until=lambda: window.space_warning.isVisible())
        meter.report('Check free space, disk answers in 1 s')
        assert 'GB' in window.space_warning.text() or 'MB' in window.space_warning.text()
        assert meter.worst() < SERVER_BUDGET

        # Asked again while the disk has not answered: still one question at a time.
        StallMeter().run(SERVER_DELAY * 3, until=lambda: not window._space_checking)
        asked.clear()
        window._check_disk_space()
        window._check_disk_space()
        window._check_disk_space()
        StallMeter().run(SERVER_DELAY * 4, until=lambda: len(asked) == 2 and not window._space_checking)
        assert len(asked) == 2
        assert at_once[1] == 1
    finally:
        _close(app, window)


def _finished_recordings(count):
    from tvhplayer.core.models import DvrEntry

    now = int(time.time())
    return [DvrEntry(uuid=f'u{i}', title=f'Show {i}', channel_name='One', start=now - 86400 * (i % 300) - 7200,
                     duration=3600, status='Completed OK', sched_status='completed', htsp_id=i,
                     raw={'filesize': 1_000_000 + i})
            for i in range(count)]


def test_refreshing_tasks_with_thousands_of_recordings_keeps_the_window_answering(monkeypatch, tmp_path):
    # Tasks refreshes every 5 seconds, open or not. Writing out the dates and
    # sizes of 3,000 finished recordings each time took over 100 ms.
    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    pane = window.tasks_pane
    pane.update_timer.stop()
    window.show()
    app.processEvents()

    entries = _finished_recordings(3000)

    def refresh():
        pane._apply_server_entries(entries)
        pane._redraw()

    try:
        refresh()
        # The window settles after showing before anything is measured.
        StallMeter().run(1.0)
        meter = StallMeter()
        for delay in (0, 300, 600):
            QTimer_single(delay, refresh)
        meter.run(1.0)
        meter.report('Tasks refresh, 3,000 finished recordings')
        # About 40 ms alone and up to 110 ms during the whole test run;
        # 270-300 ms when every line was written out again.
        assert meter.worst() < 0.15
    finally:
        _close(app, window)


def QTimer_single(delay, action):
    from PyQt6.QtCore import QTimer

    QTimer.singleShot(delay, action)


def test_tasks_show_a_finished_recording_again_when_it_changes(monkeypatch, tmp_path):
    from tvhplayer.core.models import DvrEntry

    app, ui, window, _player = _make_player(monkeypatch, tmp_path)
    pane = window.tasks_pane
    pane.update_timer.stop()
    try:
        entries = _finished_recordings(2)
        pane._apply_server_entries(entries)
        assert [task['title'] for task in pane._server_tasks] == ['Show 0', 'Show 1']
        assert pane._server_tasks[0]['size'] == '976.6 KB'
        renamed = DvrEntry(**{**entries[0].__dict__, 'title': 'Renamed', 'raw': {'filesize': 5_000_000}})
        pane._apply_server_entries([renamed, entries[1]])
        assert pane._server_tasks[0]['title'] == 'Renamed'
        assert pane._server_tasks[0]['size'] == '4.8 MB'
        assert pane._server_tasks[0]['entry'] is renamed

        # "today" becomes "yesterday" once the day is over.
        finished = entries[1].start + entries[1].duration
        monkeypatch.setattr(ui, 'datetime', _Clock(ui.datetime, finished + 86400 * 2))
        pane._apply_server_entries([renamed, entries[1]])
        assert 'today' not in pane._server_tasks[1]['line']
    finally:
        _close(app, window)


class _Clock:
    """``datetime`` with ``now()`` fixed at ``stamp``."""

    def __init__(self, real, stamp):
        self._real = real
        self._stamp = stamp

    def now(self, *args):
        return self._real.fromtimestamp(self._stamp)

    def __getattr__(self, name):
        return getattr(self._real, name)


# --- A big channel list ------------------------------------------------------


def _big_htsp_window(monkeypatch, tmp_path, count=BIG_LIST, groups=0):
    """The window showing ``count`` channels, in ``groups`` groups, from an HTSP server that sends live updates."""
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
        message = {'method': 'channelAdd', 'channelId': number, 'channelName': f'Channel {number}',
                   'channelNumber': number, 'eventId': number * 10, 'nextEventId': number * 10 + 1}
        if groups:
            message['tags'] = [(number - 1) % groups + 1]
        backend._on_async(message)
    for tag in range(1, groups + 1):
        backend._on_async({'method': 'tagAdd', 'tagId': tag, 'tagName': f'Group {tag}',
                           'members': list(range(tag, count + 1, groups))})
    backend._on_async({'method': 'initialSyncCompleted'})
    _load_channels(window, fetch, {'channels': [], 'tags': [], 'services': [], 'now_next': None})
    assert window.channel_model.rowCount() == count
    if groups:
        assert window.tag_combo.count() == groups + 1
    window.show()
    app.processEvents()
    return app, ui, window, backend


@pytest.mark.parametrize('groups', [0, 1_034])
def test_programme_changes_on_a_big_list_keep_the_window_answering(monkeypatch, tmp_path, groups):
    # Tvheadend sends a channelUpdate whenever a channel's programme changes.
    # With tens of thousands of channels that is a steady stream; none of
    # them moves a row, nor changes how many channels a group has. Counting
    # every group's channels again for each took 225-350 ms on a real server.
    from PyQt6.QtCore import QTimer

    app, ui, window, backend = _big_htsp_window(monkeypatch, tmp_path, groups=groups)
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
        meter.report(f'Programme changes, {BIG_LIST:,} channels in {groups:,} groups, 50 a second')
        assert sent[0] >= 100
        assert backend.take_channel_changes()[0] == {}
        assert meter.busy() < LIST_BUSY_BUDGET
        assert meter.worst() < LIST_BUDGET
    finally:
        window._channel_fetch = None
        backend.close()
        _close(app, window)


@pytest.mark.parametrize('search', ['', 'channel 1'])
def test_a_burst_of_programme_changes_on_a_big_list_keeps_the_window_answering(monkeypatch, tmp_path, search):
    # On the hour, thousands of channels change programme at once; the window
    # takes up to 2,000 changes at a time. Finding each one's row looked
    # through every row, close to a second for 2,000 on 60,000 channels,
    # longer still for a channel a search leaves out.
    app, ui, window, backend = _big_htsp_window(monkeypatch, tmp_path)
    try:
        window.search_box.setText(search)
        StallMeter().run(1.0)
        for number in range(1, 2001):
            number = number * 29 % BIG_LIST + 1
            backend._on_async({'method': 'channelUpdate', 'channelId': number,
                               'eventId': number * 10 + 5, 'nextEventId': number * 10 + 6})
        meter = StallMeter()
        meter.run(1.0, until=lambda: backend.take_channel_changes()[0] == {} and len(meter.ticks) > 20)
        meter.report(f'2,000 programme changes at once, {BIG_LIST:,} channels, search {search!r}')
        assert meter.worst() < LIST_BURST_BUDGET
    finally:
        window._channel_fetch = None
        backend.close()
        _close(app, window)


def test_a_big_list_arriving_keeps_the_window_answering(monkeypatch, tmp_path):
    # 58,868 channels in 1,034 groups, as on a real built-in server: counting
    # the groups and finding each channel's kind took 700 ms on the window's
    # thread, so a menu clicked meanwhile opened only after it.
    from tvhplayer.core.htsp_backend import HtspBackend
    from tvhplayer.core.models import ServerConfig

    count, groups = 58_868, 1_034
    app, ui, window, _ = _make_player(monkeypatch, tmp_path)
    backend = HtspBackend(ServerConfig(name='HTSP', url='http://127.0.0.1:9981', protocol='htsp'))
    server = {'name': 'HTSP', 'url': 'http://127.0.0.1:9981', 'protocol': 'htsp'}
    window.servers = [server]
    window.server_combo.blockSignals(True)
    window.server_combo.addItem('HTSP')
    window.server_combo.setCurrentIndex(0)
    window.server_combo.blockSignals(False)
    fetch = types.SimpleNamespace(server=dict(server), backend=backend, key=ui.server_key(server),
                                  keep_place=False, _now_next=False, deleteLater=lambda: None)
    window._channel_fetch = fetch
    for number in range(1, count + 1):
        backend._on_async({'method': 'channelAdd', 'channelId': number, 'channelName': f'Channel {number}',
                           'channelNumber': number, 'eventId': number * 10, 'nextEventId': number * 10 + 1,
                           'tags': [number % groups + 1], 'channelIcon': f'imagecache/{number}',
                           'services': [{'id': number, 'type': 'HDTV'}]})
    for tag in range(1, groups + 1):
        backend._on_async({'method': 'tagAdd', 'tagId': tag, 'tagName': f'Group {tag}',
                           'members': list(range(tag, count + 1, groups))})
    backend._on_async({'method': 'initialSyncCompleted'})
    window.show()
    StallMeter().run(1.0)
    try:
        meter = StallMeter()
        _later(lambda: window._on_channels_loaded(
            fetch, {'channels': [], 'tags': [], 'services': [], 'now_next': None}))
        meter.run(5.0, until=lambda: window.channel_model.rowCount() == count)
        meter.report(f'{count:,} channels in {groups:,} groups arriving')
        assert window.channel_model.rowCount() == count
        assert window._channel_fetch is None
        assert window.tag_combo.count() == groups + 1
        first = ui.tag_channel_counts(window._channels, window._channel_tags[:1])[0]
        assert window.tag_combo.itemText(1) == f'{window._channel_tags[0].name} ({first})'
        assert window._channel_kinds[ui.channel_key(window._channels[0])].kind == 'HD'
        assert meter.worst() < LIST_BURST_BUDGET
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



def test_a_channel_moving_group_still_updates_the_group_counts(monkeypatch, tmp_path):
    app, ui, window, backend = _big_htsp_window(monkeypatch, tmp_path, count=10, groups=2)
    try:
        texts = lambda: [window.tag_combo.itemText(i) for i in range(1, window.tag_combo.count())]
        assert texts() == ['Group 1 (5)', 'Group 2 (5)']
        # Only the programme changes: the counts stay.
        backend._on_async({'method': 'channelUpdate', 'channelId': 1, 'eventId': 999, 'nextEventId': 1000})
        window._poll_channel_metadata()
        assert texts() == ['Group 1 (5)', 'Group 2 (5)']
        # Channel 2 is in group 2; given group 1 in its tags, it counts there too
        # (group 2 still lists it as a member).
        backend._on_async({'method': 'channelUpdate', 'channelId': 2, 'tags': [1]})
        window._poll_channel_metadata()
        assert texts() == ['Group 1 (6)', 'Group 2 (5)']
        backend._on_async({'method': 'channelDelete', 'channelId': 4})
        window._poll_channel_metadata()
        assert texts() == ['Group 1 (6)', 'Group 2 (4)']
    finally:
        window._channel_fetch = None
        backend.close()
        _close(app, window)

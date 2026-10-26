import os
import time
import types


def _app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return condition()


class _Backend:
    def __init__(self, events):
        self.events = events
        self.queries = []
        self.calls = []

    def query_epg(self, query):
        self.queries.append(query)
        return [
            event for event in self.events
            if event.stop > query.ends_after and event.start < query.starts_before
        ]

    def create_dvr_entry_by_event(self, event_id):
        self.calls.append(('create', event_id))
        return 'new'

    def cancel_dvr_entry(self, entry):
        self.calls.append(('cancel', entry.uuid))

    def stop_dvr_entry(self, entry):
        self.calls.append(('stop', entry.uuid))

    def create_autorec_by_series(self, event_id):
        self.calls.append(('series', event_id))
        return 'rule'

    def close(self):
        pass


class _Host:
    def __init__(self, channels, tags, backend):
        self._channels = channels
        self._channel_tags = tags
        self.channel_options = {'logos': True, 'hide_disabled': True, 'tag_filter': False, 'tag': ''}
        self._dvr_entries = None
        self.backend = backend
        self.config = {}
        self.played = []
        self.refreshed = 0
        self.statusbar = types.SimpleNamespace(messages=[])
        self.statusbar.showMessage = self.statusbar.messages.append

    def current_server(self):
        return {'name': 'box', 'url': 'http://127.0.0.1:9981'}

    def _server_requests_ready(self):
        return True

    def _logo_for(self, reference, backend):
        return None

    def _playing_channel(self):
        return self.played[-1] if self.played else None

    def get_backend(self):
        return self.backend

    def _refresh_tasks(self):
        self.refreshed += 1

    def play_channel_by_data(self, channel):
        self.played.append(channel)

    def show_channel_epg(self, channel):
        pass

    def save_config(self):
        pass


def _key(widget, key, text='', modifiers=None):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers or Qt.KeyboardModifier.NoModifier, text)
    QApplication.sendEvent(widget, event)


def test_guide_window_reads_spans_moves_by_keyboard_and_records(monkeypatch):
    app = _app()
    from PyQt6.QtCore import Qt

    import tvhplayer.guide_view as guide_view
    from tvhplayer.core.guide_grid import SPAN_SECONDS, slot_start
    from tvhplayer.core.models import Channel, ChannelTag, DvrEntry, EpgEvent

    origin = slot_start(int(time.time()))
    alpha = Channel(uuid='a', name='Alpha', number=1)
    bravo = Channel(uuid='b', name='Bravo', number=2)
    charlie = Channel(uuid='c', name='Charlie', number=3, tag_ids=['news'])
    hidden = Channel(uuid='d', name='Disabled', number=4, enabled=False)
    events = [
        EpgEvent(start=origin - 600, stop=origin + 3600, title='Morning', channel_uuid='a', event_id=1),
        EpgEvent(start=origin + 3600, stop=origin + 7200, title='Midday', channel_uuid='a', event_id=2,
                 serieslink_uri='crid://series', description='A long chat.'),
        EpgEvent(start=origin - 600, stop=origin + 7200, title='Bravo Show', channel_uuid='b', event_id=3),
    ]
    backend = _Backend(events)
    monkeypatch.setattr(guide_view, 'create_backend', lambda server: backend)
    host = _Host([alpha, bravo, charlie, hidden], [ChannelTag(uuid='news', name='News')], backend)

    window = guide_view.GuideWindow(host)
    grid = window.grid
    try:
        window.show_channel(alpha)
        assert _wait(app, lambda: origin in grid.data.loaded)
        first = backend.queries[0]
        assert (first.ends_after, first.starts_before) == (origin, origin + SPAN_SECONDS)
        # Disabled channels stay out, as in the channel list.
        assert [channel.name for channel in grid.channels] == ['Alpha', 'Bravo', 'Charlie']
        assert grid.current_event().title == 'Morning'
        assert window.title_label.text() == 'Morning'
        assert window.timing_label.text().startswith('On now')
        assert window.tag_combo.isVisibleTo(window)
        assert window.tag_combo.itemText(1) == 'News (1)'
        assert grid.accessibleName().startswith('Morning, Alpha, On now')
        grid.grab()

        _key(grid, Qt.Key.Key_Right)
        assert grid.current_event().title == 'Midday'
        assert window.description_label.text() == 'A long chat.'
        assert window.series_btn.isEnabled()
        _key(grid, Qt.Key.Key_Down)
        assert grid.current_channel().name == 'Bravo'
        assert grid.current_event().title == 'Bravo Show'
        _key(grid, Qt.Key.Key_Down)
        assert grid.current_event() is None
        assert window.title_label.text() == 'No programme information'
        assert not window.record_btn.isEnabled()
        _key(grid, Qt.Key.Key_Up)
        _key(grid, Qt.Key.Key_Up)
        # Up and down keep the time of the programme left behind.
        assert grid.current_event().title == 'Midday'

        _key(grid, Qt.Key.Key_R, modifiers=Qt.KeyboardModifier.ControlModifier)
        assert backend.calls == [('create', 2)]
        assert window.record_btn.text() == '&Cancel Recording'
        assert host.refreshed == 1
        assert 'Recording scheduled' in window.timing_label.text()

        entry = DvrEntry(uuid='dvr-2', title='Midday', channel_name='Alpha', start=origin + 3600,
                         duration=3600, sched_status='scheduled', raw={'broadcast': 2})
        window.recordings_changed([entry])
        assert window.record_btn.text() == '&Cancel Recording'
        _key(grid, Qt.Key.Key_R, modifiers=Qt.KeyboardModifier.ControlModifier)
        assert backend.calls[-1] == ('cancel', 'dvr-2')
        assert window.record_btn.text() == 'Re&cord'

        window.series_btn.click()
        assert backend.calls[-1] == ('series', 2)

        _key(grid, Qt.Key.Key_Return)
        assert host.played == [alpha]
        grid.grab()

        window.find_box.setText('char')
        assert [channel.name for channel in grid.channels] == ['Charlie']
        window.find_box.setText('zzz')
        assert grid.channels == [] and grid.message == 'No channels match.'
        grid.grab()
        window.find_box.clear()
        assert len(grid.channels) == 3

        grid.setFocus()
        _key(grid, Qt.Key.Key_B, 'b')
        assert grid.current_channel().name == 'Bravo'
        _key(grid, Qt.Key.Key_Home)
        assert grid.current_event().title == 'Bravo Show'

        window.tag_combo.setCurrentIndex(1)
        assert [channel.name for channel in grid.channels] == ['Charlie']

        window.close()
        assert 'geometry' in host.config['guide_window']
    finally:
        window.shutdown()
        window.deleteLater()
        app.processEvents()


def test_guide_window_reports_a_failed_read_until_reload(monkeypatch):
    app = _app()
    import tvhplayer.guide_view as guide_view
    from tvhplayer.core.models import Channel

    class _Broken(_Backend):
        def query_epg(self, query):
            raise RuntimeError('server said no')

    backend = _Broken([])
    monkeypatch.setattr(guide_view, 'create_backend', lambda server: backend)
    host = _Host([Channel(uuid='a', name='Alpha', number=1)], [], backend)
    window = guide_view.GuideWindow(host)
    try:
        window.show_channel(None)
        assert _wait(app, lambda: window._error)
        assert 'server said no' in window.status_label.text()
        assert 'server said no' in host.statusbar.messages[-1]
        window.grid.grab()

        backend.events = []
        monkeypatch.setattr(guide_view, 'create_backend', lambda server: _Backend([]))
        window.reload()
        assert not window._error
        assert _wait(app, lambda: window.grid.data.loaded)
        assert window.title_label.text() == 'No programme information'
    finally:
        window.shutdown()
        window.deleteLater()
        app.processEvents()

from types import SimpleNamespace
from uuid import UUID

import pytest

from tvhplayer.core.chromecast import CastManager, cast_media_type, cast_url_error


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)

    def shutdown(self, **_kwargs):
        pass


class FakeBrowser:
    def __init__(self):
        self.stopped = False

    def stop_discovery(self):
        self.stopped = True


class FakeMediaController:
    def __init__(self):
        self.listener = None
        self.played = []
        self.stops = 0

    def register_status_listener(self, listener):
        self.listener = listener

    def play_media(self, url, content_type, **options):
        self.played.append((url, content_type, options))
        self.listener.new_media_status(SimpleNamespace(player_state='PLAYING', content_id=url, idle_reason=None))

    def stop(self):
        self.stops += 1


class FakeDefaultMediaReceiver:
    def __init__(self):
        self.played = []

    def play_media(self, url, content_type, **options):
        self.played.append((url, content_type, options))
        callback = options.get('callback_function')
        if callback is not None:
            callback(True, {'type': 'MEDIA_STATUS'})


class FakeCast:
    def __init__(self, uuid, name, cast_type='cast', model='TV'):
        self.cast_info = SimpleNamespace(
            uuid=uuid,
            friendly_name=name,
            cast_type=cast_type,
            model_name=model,
            host='192.168.1.30',
            port=8009,
        )
        self.media_controller = FakeMediaController()
        self.status = SimpleNamespace(volume_muted=False, volume_level=0.5)
        self.socket_client = SimpleNamespace(is_connected=True)
        self.waited = False
        self.disconnected = False
        self.volumes = []
        self.mutes = []
        self.handlers = []

    def wait(self, timeout=None):
        self.waited = timeout

    def set_volume(self, value):
        self.volumes.append(value)

    def set_volume_muted(self, muted):
        self.mutes.append(muted)

    def register_status_listener(self, listener):
        self.receiver_listener = listener

    def register_connection_listener(self, listener):
        self.connection_listener = listener

    def register_handler(self, handler):
        self.handlers.append(handler)

    def disconnect(self, timeout=None):
        self.disconnected = True


def test_cast_urls_must_be_fetchable_by_the_receiver():
    assert 'LAN address' in cast_url_error('http://127.0.0.1:9981/stream/channel/one')
    assert 'LAN address' in cast_url_error('http://localhost:9981/stream/channel/one')
    assert 'username or password' in cast_url_error('http://user:pass@tv.local/stream/channel/one')
    assert cast_url_error('http://192.168.1.20:9981/playlist/ticket/channel/one?ticket=abc') == ''


def test_cast_media_types_cover_live_and_adaptive_streams():
    assert cast_media_type('http://tv/stream.ts?ticket=one') == 'video/mp2t'
    assert cast_media_type('http://tv/live/index.m3u8') == 'application/vnd.apple.mpegurl'
    assert cast_media_type('https://tv/video.mp4') == 'video/mp4'


def test_manager_discovers_video_devices_and_controls_one(qapp, caplog):
    caplog.set_level('INFO', logger='tvhplayer.core.chromecast')
    ident = '00000000-0000-0000-0000-000000000001'
    living = FakeCast(ident, 'Living room')
    kitchen = FakeCast('00000000-0000-0000-0000-000000000002', 'Kitchen display', model='Nest Hub')
    speaker = FakeCast('00000000-0000-0000-0000-000000000003', 'Speaker', cast_type='audio')
    browser = FakeBrowser()
    backend = SimpleNamespace(
        discovery=SimpleNamespace(discover_chromecasts=lambda **_kwargs: (
            [living.cast_info, speaker.cast_info, kitchen.cast_info], browser)),
        get_chromecast_from_host=lambda *_args, **_kwargs: living,
    )
    manager = CastManager(backend=backend, executor=ImmediateExecutor(), relay_factory=FakeRelay)
    devices = []
    connections = []
    playing = []
    manager.devices_changed.connect(lambda found: devices.extend(found))
    manager.connected.connect(lambda uuid, name: connections.append((uuid, name)))
    manager.playing.connect(lambda: playing.append(True))

    manager.discover()

    assert [device.name for device in devices] == ['Kitchen display', 'Living room']
    manager.connect_to(ident)
    assert living.waited == 10
    assert connections == [(ident, 'Living room')]

    assert manager.play('http://tv.local/live.ts?ticket=one', 'News') is True
    assert living.media_controller.played == [(
        manager._expected_url,
        'video/mp2t',
        {'title': 'News', 'stream_type': 'LIVE',
         'callback_function': living.media_controller.played[0][2]['callback_function']},
    )]
    assert playing == [True]
    assert manager.is_playing is True

    manager.set_volume(35)
    manager.set_muted(True)
    assert living.volumes == [0.35]
    assert living.mutes == [True]

    manager.stop()
    assert living.media_controller.stops == 1
    manager.disconnect()
    assert living.disconnected is True
    text = caplog.text
    assert 'Searching for Chromecast devices' in text
    assert 'Living room at 192.168.1.30' in text
    assert 'Connecting to Living room at 192.168.1.30' in text
    assert 'Connected to Living room at 192.168.1.30' in text
    assert 'Loading News as video/mp2t from http://192.168.1.2:40000/token/' in text
    assert 'Player PLAYING' in text
    assert 'Disconnecting from Living room' in text
    manager.close()
    assert browser.stopped is True


class FakeRelay:
    counter = 0

    def __init__(self, source, receiver):
        type(self).counter += 1
        self.source = source
        self.url = f'http://192.168.1.2:40000/token/{self.counter}'
        self.closed = False

    def inspect(self):
        return 'video/mp2t'

    def close(self):
        self.closed = True


@pytest.fixture
def casting(qapp):
    info = FakeCast(str(UUID(int=1)), 'TV').cast_info
    clients = []

    def factory(*_args, **_kwargs):
        client = FakeCast(info.uuid, info.friendly_name)
        clients.append(client)
        return client

    backend = SimpleNamespace(
        discovery=SimpleNamespace(discover_chromecasts=lambda **_kwargs: ([info], FakeBrowser())),
        get_chromecast_from_host=factory,
    )
    manager = CastManager(backend=backend, executor=ImmediateExecutor(), relay_factory=FakeRelay)
    manager.discover()
    manager.connect_to(info.uuid)
    yield manager, clients
    manager.close()


def status(state, url=None):
    return SimpleNamespace(player_state=state, content_id=url, idle_reason=None)


def test_disconnect_and_reconnect_constructs_a_new_socket_client(casting):
    manager, clients = casting
    uuid = manager.connected_uuid
    manager.disconnect()
    manager.connect_to(uuid)
    assert len(clients) == 2
    assert clients[0].disconnected
    assert not clients[1].disconnected


def test_late_receiver_status_cannot_revive_disconnected_playback(casting):
    manager, clients = casting
    manager.play('http://127.0.0.1:9981/live', 'News')
    url = manager._expected_url
    listener = clients[-1].media_controller.listener
    relay = manager._relay
    manager.disconnect()
    listener.new_media_status(status('PLAYING', url))
    assert not manager.is_playing
    assert relay.closed


def test_old_channel_status_and_load_failure_do_not_change_new_channel(casting):
    manager, clients = casting
    manager.play('http://127.0.0.1:9981/one', 'One')
    old_url = manager._expected_url
    callback = clients[-1].media_controller.played[-1][2]['callback_function']
    manager.play('http://127.0.0.1:9981/two', 'Two')
    url = manager._expected_url
    clients[-1].media_controller.listener.new_media_status(status('IDLE', old_url))
    callback(False, None)
    assert manager.is_playing
    assert manager._expected_url == url


def test_idle_without_new_content_during_startup_is_ignored(casting):
    manager, clients = casting
    clients[-1].media_controller.play_media = lambda *_args, **_kwargs: None
    manager.play('http://localhost:9981/live', 'News')
    clients[-1].media_controller.listener.new_media_status(status('IDLE'))
    assert manager._watchdog.isActive()
    assert manager._expected_url
    assert not manager.is_playing


def test_load_timeout_closes_relay_and_reports_failure(casting):
    manager, clients = casting
    clients[-1].media_controller.play_media = lambda *_args, **_kwargs: None
    errors = []
    manager.failed.connect(errors.append)
    manager.play('http://localhost:9981/live', 'News')
    relay = manager._relay
    manager._load_timeout()
    assert errors and 'did not start' in errors[0]
    assert relay.closed
    assert not manager._expected_url


def test_receiver_volume_and_mute_updates_are_reported_without_commands(casting):
    manager, clients = casting
    updates = []
    manager.audio_changed.connect(lambda volume, muted: updates.append((volume, muted)))
    clients[-1].receiver_listener.new_cast_status(SimpleNamespace(volume_level=0.27, volume_muted=True))
    assert updates == [(27, True)]
    assert manager.is_muted
    assert manager.volume == 27
    assert not clients[-1].volumes


class QueuedExecutor:
    def __init__(self):
        self.pending = []

    def submit(self, fn, *args):
        self.pending.append((fn, args))

    def drain(self):
        while self.pending:
            fn, args = self.pending.pop(0)
            fn(*args)

    def shutdown(self, **_kwargs):
        self.drain()


def test_stop_cancels_a_load_still_in_the_worker_queue(casting):
    manager, clients = casting
    executor = QueuedExecutor()
    manager._executor = executor
    manager.play('http://localhost:9981/live', 'News')
    manager.stop()
    executor.drain()
    assert not clients[-1].media_controller.played
    assert not manager._expected_url


def test_switching_receiver_invalidates_the_old_receiver_callbacks(casting):
    manager, clients = casting
    manager.play('http://localhost:9981/live', 'News')
    listener = clients[0].media_controller.listener
    old_url = manager._expected_url
    manager.connect_to(manager.connected_uuid)
    listener.new_media_status(status('PLAYING', old_url))
    assert len(clients) == 2
    assert clients[0].disconnected
    assert not manager.is_playing


def test_socket_callbacks_update_state_only_on_the_qt_thread(casting, qapp):
    import threading

    manager, clients = casting
    clients[-1].media_controller.play_media = lambda *_args, **_kwargs: None
    manager.play('http://localhost:9981/live', 'News')
    listener = clients[-1].media_controller.listener
    thread = threading.Thread(target=lambda: listener.new_media_status(status('PLAYING', manager._expected_url)))
    thread.start()
    thread.join(timeout=1)
    assert not manager.is_playing
    qapp.processEvents()
    assert manager.is_playing


def test_shutdown_closes_a_relay_waiting_for_qt_delivery(casting):
    manager, clients = casting
    manager._post = lambda fn, cleanup=None: None
    manager.play('http://localhost:9981/live', 'News')
    pending = [resource for kind, resource in manager._pending_resources if kind == 'relay']
    assert len(pending) == 1
    manager.close()
    assert pending[0].closed


def test_current_load_failure_clears_watchdog_and_stream(casting):
    manager, clients = casting
    errors = []
    manager.failed.connect(errors.append)
    manager.play('http://localhost:9981/live', 'News')
    callback = clients[-1].media_controller.played[-1][2]['callback_function']
    callback(True, {'type': 'LOAD_FAILED'})
    assert errors
    assert not manager.is_playing
    assert not manager._watchdog.isActive()


def test_idle_from_an_old_media_session_does_not_stop_current_stream(casting):
    manager, clients = casting
    clients[-1].media_controller.play_media = lambda *_args, **_kwargs: None
    manager.play('http://localhost:9981/live', 'News')
    listener = clients[-1].media_controller.listener
    current = status('PLAYING', manager._expected_url)
    current.media_session_id = 20
    listener.new_media_status(current)
    stale = status('IDLE', manager._expected_url)
    stale.media_session_id = 19
    listener.new_media_status(stale)
    assert manager.is_playing


def test_automatic_profile_falls_back_and_remembers_working_receiver_choice(casting, monkeypatch):
    from tvhplayer.core import backend
    from tvhplayer.core.models import Channel, StreamProfile

    manager, clients = casting
    requested = []
    profiles = [StreamProfile('ts', 'webtv-h264-aac-mpegts'),
                StreamProfile('webm', 'webtv-vp8-vorbis-webm'),
                StreamProfile('silent', 'webtv-h264-vorbis-mp4')]
    source = SimpleNamespace(
        list_profiles=lambda: profiles,
        stream_url=lambda _channel, profile=None: requested.append(profile) or f'http://localhost/{profile}',
        close=lambda: None,
    )
    monkeypatch.setattr(backend, 'create_backend', lambda _server: source)
    original_play = clients[-1].media_controller.play_media

    def receiver_play(url, kind, **options):
        if kind == 'video/mp2t':
            options['callback_function'](True, {'type': 'LOAD_FAILED'})
        else:
            original_play(url, kind, **options)

    clients[-1].media_controller.play_media = receiver_play
    learned = []
    manager.automatic_profile_worked.connect(lambda key, profile: learned.append((key, profile)))
    channel = Channel(uuid='channel', name='TV')
    manager.play_channel({'url': 'http://localhost:9981'}, channel)
    assert requested == ['ts', 'webm']
    assert manager.is_playing
    assert learned[-1][1] == 'webm'
    assert clients[-1].media_controller.played[-1][1] == 'video/webm'

    requested.clear()
    manager.stop()
    manager.play_channel({'url': 'http://localhost:9981'}, channel)
    assert requested == ['webm']

    # A choice learned on one server does not reorder another server's profiles.
    requested.clear()
    manager.play_channel({'url': 'http://other:9981'}, channel)
    assert requested == ['ts', 'webm']


def test_manual_cast_profile_is_respected_without_automatic_fallback(casting, monkeypatch):
    from tvhplayer.core import backend
    from tvhplayer.core.models import Channel, StreamProfile

    manager, clients = casting
    requested = []
    source = SimpleNamespace(
        list_profiles=lambda: [StreamProfile('chosen', 'webtv-h264-aac-matroska')],
        stream_url=lambda _channel, profile=None: requested.append(profile) or 'http://localhost/live',
        close=lambda: None,
    )
    monkeypatch.setattr(backend, 'create_backend', lambda _server: source)
    errors = []
    manager.failed.connect(errors.append)
    clients[-1].media_controller.play_media = lambda _url, _kind, **options: options['callback_function'](False, None)
    manager.play_channel({'url': 'http://localhost:9981'}, Channel(uuid='c', name='TV'), 'chosen')
    assert requested == ['chosen']
    assert len(errors) == 1


def test_load_uses_default_media_receiver_instead_of_active_cast_app(qapp):
    # YouTube and similar apps expose the media namespace; without forcing the
    # Default Media Receiver, LOAD would target that app instead of CC1AD845.
    living = FakeCast('00000000-0000-0000-0000-000000000001', 'Living room')
    backend = SimpleNamespace(
        discovery=SimpleNamespace(discover_chromecasts=lambda **_kwargs: ([living.cast_info], FakeBrowser())),
        get_chromecast_from_host=lambda *_args, **_kwargs: living,
        controllers=SimpleNamespace(media=SimpleNamespace(
            DefaultMediaReceiverController=FakeDefaultMediaReceiver)),
        config=SimpleNamespace(APP_MEDIA_RECEIVER='CC1AD845'),
    )
    manager = CastManager(backend=backend, executor=ImmediateExecutor(), relay_factory=FakeRelay)
    manager.discover()
    manager.connect_to(living.cast_info.uuid)

    assert manager.play('http://tv.local/live.ts?ticket=one', 'News') is True

    assert len(living.handlers) == 1
    dmr = living.handlers[0]
    assert isinstance(dmr, FakeDefaultMediaReceiver)
    assert living._tvhplayer_dmr is dmr
    assert dmr.played[0][0] == manager._expected_url
    assert dmr.played[0][1] == 'video/mp2t'
    assert dmr.played[0][2]['title'] == 'News'
    assert dmr.played[0][2]['stream_type'] == 'LIVE'
    assert living.media_controller.played == []
    manager.close()


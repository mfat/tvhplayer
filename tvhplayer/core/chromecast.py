"""Google Cast discovery and playback with Qt-owned state and scoped loads."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID
import ipaddress
import threading
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .cast_relay import CastRelay, media_type
from .cast_profiles import AUTO_PROFILE, profile_media_type, ranked_cast_profiles

try:
    import pychromecast as _pychromecast
except ImportError as exc:
    _pychromecast = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ''


@dataclass(frozen=True)
class CastDevice:
    uuid: str
    name: str
    model: str = ''
    host: str = ''
    port: int = 8009


def cast_url_error(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
    except ValueError:
        return 'The stream URL is invalid.'
    if parsed.scheme not in ('http', 'https') or not host:
        return 'Chromecast needs an HTTP or HTTPS stream URL.'
    if parsed.username is not None or parsed.password is not None:
        return 'The stream must pass through the relay to keep its username or password private.'
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower().rstrip('.') == 'localhost' or host.lower().endswith('.localhost')
    if loopback:
        return 'Chromecast needs the stream relay for a loopback address, rather than a LAN address change.'
    return ''


def cast_media_type(url):
    return media_type('', url)


class _ReceiverListener:
    def __init__(self, manager, connection):
        self.manager, self.connection = manager, connection

    def new_cast_status(self, status):
        volume = int(round(float(getattr(status, 'volume_level', 0.5)) * 100))
        muted = bool(getattr(status, 'volume_muted', False))
        self.manager._post(lambda: self.manager._audio_status(self.connection, volume, muted))

    def new_connection_status(self, status):
        state = getattr(status, 'status', '')
        if state in ('DISCONNECTED', 'LOST', 'FAILED'):
            self.manager._post(lambda: self.manager._connection_lost(self.connection))


class _MediaListener:
    def __init__(self, manager, connection):
        self.manager, self.connection = manager, connection

    def new_media_status(self, status):
        # PyChromecast mutates its status on the socket thread. Copy what the
        # UI needs before queuing delivery to Qt's main thread.
        snapshot = SimpleNamespace(**{
            field: getattr(status, field, None)
            for field in ('player_state', 'content_id', 'media_session_id', 'idle_reason')
        })
        self.manager._post(lambda: self.manager._media_status(self.connection, snapshot))

    def load_media_failed(self, _queue_item_id, error_code, error_description=None):
        # This event has no content URL. The scoped LOAD response handles the
        # failure; otherwise the watchdog expires without blaming a newer load.
        pass


class CastManager(QObject):
    devices_changed = pyqtSignal(object)
    discovery_failed = pyqtSignal(str)
    connected = pyqtSignal(str, str)
    disconnected = pyqtSignal()
    playing = pyqtSignal()
    stopped = pyqtSignal()
    failed = pyqtSignal(str)
    audio_changed = pyqtSignal(int, bool)
    operation_failed = pyqtSignal(str)
    profiles_ready = pyqtSignal(str, object, str)
    profile_selected = pyqtSignal(str)
    automatic_profile_worked = pyqtSignal(str, str)
    _dispatch = pyqtSignal(object)
    START_TIMEOUT_MS = 30000

    def __init__(self, parent=None, backend=None, executor=None, relay_factory=CastRelay, known_profiles=None):
        super().__init__(parent)
        self._backend = _pychromecast if backend is None else backend
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='tvh-cast')
        self._relay_factory = relay_factory
        self._devices = []
        self._cast = self._device = self._relay = None
        self._discovering = self._playing = self._muted = self._closed = False
        self._connection = self._request = 0
        self._expected_url = ''
        self._session_id = None
        self._volume = 50
        self._working_profiles = dict(known_profiles or {})
        self._auto_context = None
        self._resource_lock = threading.Lock()
        self._pending_resources = set()
        self._dispatch.connect(lambda function: function())
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._load_timeout)

    @property
    def available(self):
        return self._backend is not None

    @property
    def unavailable_reason(self):
        return '' if self.available else f'Chromecast support is unavailable: {_IMPORT_ERROR}'

    @property
    def devices(self):
        return list(self._devices)

    @property
    def discovering(self):
        return self._discovering

    @property
    def is_connected(self):
        return self._cast is not None

    @property
    def connected_name(self):
        return self._device.name if self._device else ''

    @property
    def connected_uuid(self):
        return self._device.uuid if self._device else ''

    @property
    def is_playing(self):
        return self._playing

    @property
    def is_muted(self):
        return self._muted

    @property
    def volume(self):
        return self._volume

    def _post(self, function, cleanup=None):
        if self._closed:
            if cleanup is not None:
                cleanup()
            return
        if QThread.currentThread() == self.thread():
            function()
        else:
            self._dispatch.emit(lambda: cleanup() if self._closed and cleanup else
                                (None if self._closed else function()))

    def _submit(self, function, *args):
        if not self._closed:
            self._executor.submit(function, *args)

    def discover(self, force=False):
        if not self.available:
            self.discovery_failed.emit(self.unavailable_reason)
            return
        if self._discovering or (self._devices and not force):
            return
        self._discovering = True
        self._submit(self._discover)

    def _discover(self):
        browser = None
        try:
            infos, browser = self._backend.discovery.discover_chromecasts(timeout=5)
            devices = [CastDevice(str(info.uuid), info.friendly_name or 'Chromecast',
                                  info.model_name or '', info.host, info.port or 8009)
                       for info in infos if info.cast_type not in ('audio', 'group')]
            self._post(lambda: self._discovered(devices))
        except Exception:
            self._post(lambda: self._discovery_error('Could not search for Chromecast devices.'))
        finally:
            if browser is not None:
                browser.stop_discovery()

    def _discovered(self, devices):
        self._discovering = False
        self._devices = sorted(devices, key=lambda device: device.name.casefold())
        self.devices_changed.emit(self.devices)

    def _discovery_error(self, message):
        self._discovering = False
        self.discovery_failed.emit(message)

    def connect_to(self, uuid):
        device = next((item for item in self._devices if item.uuid == str(uuid)), None)
        if device is None:
            self.operation_failed.emit('That Chromecast is no longer available. Search again.')
            return
        self._begin_connect(device)

    def connect_host(self, host):
        try:
            host = str(ipaddress.ip_address(host.strip()))
        except ValueError:
            self.operation_failed.emit('Enter the Chromecast’s IP address.')
            return
        self._begin_connect(CastDevice('', host, host=host))

    def _begin_connect(self, device):
        self._connection += 1
        connection = self._connection
        old = self._cast
        self._cast = self._device = None
        self._cancel_load()
        self._submit(self._connect, connection, device, old)

    def _connect(self, connection, device, old):
        cast = None
        try:
            if old is not None:
                self._release(old, stop=True)
            if self._closed or connection != self._connection:
                return
            if not device.uuid:
                info = self._backend.discovery.get_device_info(device.host, timeout=5)
                if info is None or info.cast_type in ('audio', 'group'):
                    raise ValueError('No video receiver found')
                device = CastDevice(str(info.uuid), info.friendly_name, info.model_name, device.host)
            # A stopped socket thread cannot be restarted. Only device
            # descriptions are cached; every connection gets a fresh client.
            host = (device.host, device.port, UUID(device.uuid), device.model, device.name)
            cast = self._backend.get_chromecast_from_host(host, tries=1, timeout=5)
            with self._resource_lock:
                self._pending_resources.add(('cast', cast))
            cast.wait(timeout=10)
            if not cast.socket_client.is_connected:
                raise OSError('Receiver did not connect')
            if self._closed or connection != self._connection:
                self._release(cast)
                return
            cast.media_controller.register_status_listener(_MediaListener(self, connection))
            receiver = _ReceiverListener(self, connection)
            cast.register_status_listener(receiver)
            cast.register_connection_listener(receiver)
            self._post(lambda: self._connected(connection, cast, device),
                       lambda: self._release(cast))
        except Exception:
            if cast is not None:
                self._release(cast)
            self._post(lambda: self._connect_failed(connection, device.name))

    def _connect_failed(self, connection, name):
        if connection == self._connection:
            self.disconnected.emit()
            self.operation_failed.emit(f'Could not connect to {name}. Check the receiver and network.')

    def _connected(self, connection, cast, device):
        with self._resource_lock:
            self._pending_resources.discard(('cast', cast))
        if connection != self._connection:
            self._submit(self._release, cast)
            return
        self._cast, self._device = cast, device
        status = cast.status
        self._audio_status(connection, int(round(status.volume_level * 100)), status.volume_muted)
        self.connected.emit(device.uuid, device.name)

    def play(self, url, title):
        if self._cast is None:
            self.failed.emit('Choose a Chromecast first.')
            return False
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            self.failed.emit('This stream does not have a valid HTTP address.')
            return False
        self._cancel_load()
        request, connection = self._request, self._connection
        self._expected_url = 'pending'
        self._watchdog.start(self.START_TIMEOUT_MS)
        self._submit(self._prepare, connection, request, self._cast, self._device, url, title)
        return True

    def play_channel(self, server, channel, profile=AUTO_PROFILE):
        """Resolve the Cast profile and ticket on a worker before sharing it."""
        if self._cast is None:
            self.failed.emit('Choose a Chromecast first.')
            return False
        self._cancel_load()
        self._expected_url = 'pending'
        self._watchdog.start(self.START_TIMEOUT_MS)
        self._submit(self._prepare_channel, self._connection, self._request,
                     self._cast, self._device, dict(server), channel, profile)
        return True

    def _prepare_channel(self, connection, request, cast, device, server, channel, profile, candidates=None):
        from .backend import create_backend
        from .playlist_sync import server_key
        backend = None
        try:
            if not self._current(connection, request):
                return
            backend = create_backend(server)
            name = 'Server default'
            context = None
            hint = None
            if profile == AUTO_PROFILE:
                key = f'{device.uuid}|{server_key(server)}'
                if candidates is None:
                    try:
                        ranked = ranked_cast_profiles(backend.list_profiles())
                        candidates = [(item.uuid or item.name, item.name, profile_media_type(item)) for item in ranked]
                    except Exception:
                        candidates = []
                    candidates = candidates or [('', 'Server default', None)]
                    preferred = self._working_profiles.get(key)
                    candidates.sort(key=lambda item: item[0] != preferred)
                profile, name, hint = candidates[0]
                context = (server, channel, candidates, key)
            elif profile:
                name = profile
                try:
                    selected = next((item for item in backend.list_profiles()
                                     if profile in (item.uuid, item.name)), None)
                    if selected:
                        hint = profile_media_type(selected)
                        name = selected.name
                except Exception:
                    pass
            self._post(lambda: self._profile_chosen(connection, request, name, context))
            url = backend.stream_url(channel, profile=profile or None)
            if not self._current(connection, request):
                return
            self._prepare(connection, request, cast, device, url, channel.name, hint)
        except Exception:
            self._post(lambda: self._load_failed(connection, request,
                       'Could not open this channel using the selected Cast profile.'))
        finally:
            if backend is not None:
                backend.close()

    def _profile_chosen(self, connection, request, name, context=None):
        if self._current(connection, request):
            self._auto_context = context
            self.profile_selected.emit(name)

    def _current(self, connection, request):
        return not self._closed and connection == self._connection and request == self._request

    def _prepare(self, connection, request, cast, device, url, title, content_hint=None):
        relay = None
        try:
            if not self._current(connection, request):
                return
            relay = self._relay_factory(url, device.host)
            with self._resource_lock:
                self._pending_resources.add(('relay', relay))
            kind = relay.inspect()
            kind = getattr(relay, 'detected_content_type', '') or content_hint or kind
            if not self._current(connection, request):
                relay.close()
                with self._resource_lock:
                    self._pending_resources.discard(('relay', relay))
                return
            self._post(lambda: self._prepared(connection, request, cast, relay, kind, title), relay.close)
        except Exception:
            if relay is not None:
                relay.close()
                with self._resource_lock:
                    self._pending_resources.discard(('relay', relay))
            self._post(lambda: self._load_failed(connection, request,
                       'Could not share this stream with the Chromecast. Check the network connection.'))

    def _prepared(self, connection, request, cast, relay, kind, title):
        with self._resource_lock:
            self._pending_resources.discard(('relay', relay))
        if not self._current(connection, request):
            relay.close()
            return
        self._relay = relay
        self._expected_url = relay.url
        self._submit(self._send_load, connection, request, cast, relay.url, kind, title)

    def _default_media_receiver_class(self):
        backend = self._backend
        if backend is None:
            return None
        try:
            return backend.controllers.media.DefaultMediaReceiverController
        except AttributeError:
            return None

    def _default_media_receiver_id(self):
        backend = self._backend
        try:
            return backend.config.APP_MEDIA_RECEIVER
        except AttributeError:
            return 'CC1AD845'

    def _default_media_player(self, cast):
        # MediaController uses app_must_match=False, so LOAD goes into YouTube
        # (and similar) when they already expose the media namespace. Prefer the
        # Default Media Receiver controller, which launches CC1AD845 first.
        player = getattr(cast, '_tvhplayer_dmr', None)
        if player is not None:
            return player
        dmr_cls = self._default_media_receiver_class()
        if dmr_cls is not None and hasattr(cast, 'register_handler'):
            player = dmr_cls()
            cast.register_handler(player)
            cast._tvhplayer_dmr = player
            return player
        start_app = getattr(cast, 'start_app', None)
        app_id = self._default_media_receiver_id()
        if start_app is not None and app_id:
            start_app(app_id)
        return cast.media_controller

    def _send_load(self, connection, request, cast, url, kind, title):
        if not self._current(connection, request):
            return

        def loaded(sent, response):
            if not sent or (response or {}).get('type') in ('LOAD_FAILED', 'INVALID_REQUEST'):
                self._post(lambda: self._load_failed(connection, request,
                           'The Chromecast could not load this stream. Try a compatible stream profile.'))

        try:
            self._default_media_player(cast).play_media(
                url, kind, title=title, stream_type='LIVE', callback_function=loaded)
        except Exception:
            self._post(lambda: self._load_failed(connection, request, 'Could not send the stream to Chromecast.'))

    def _media_status(self, connection, status):
        if connection != self._connection or not self.is_connected or not self._expected_url:
            return
        # Each load gets a unique URL: an earlier channel cannot change the
        # state of a newer request on the same receiver.
        if status.content_id != self._expected_url:
            return
        session = getattr(status, 'media_session_id', None)
        if self._session_id is not None and session is not None and session != self._session_id:
            return
        state = (status.player_state or '').upper()
        if state in ('PLAYING', 'PAUSED'):
            first = not self._playing
            self._playing = True
            self._session_id = session
            self._watchdog.stop()
            if first:
                if self._auto_context is not None:
                    _, _, candidates, key = self._auto_context
                    profile = candidates[0][0]
                    self._working_profiles[key] = profile
                    self.automatic_profile_worked.emit(key, profile)
                self.playing.emit()
        elif state == 'IDLE':
            if (status.idle_reason or '').upper() == 'ERROR':
                self._load_failed(connection, self._request,
                                  'The Chromecast could not decode this stream. Try another stream profile.')
            elif self._playing:
                self._cancel_load()
                self.stopped.emit()

    def _load_timeout(self):
        self._load_failed(self._connection, self._request,
                          'Chromecast playback did not start. Check connectivity and the stream profile.')

    def _load_failed(self, connection, request, message):
        if self._current(connection, request) and self._expected_url:
            cast = self._cast
            context = self._auto_context
            self._cancel_load()
            if cast is not None:
                self._submit(self._command, connection, cast.media_controller.stop)
            if cast is not None and context is not None and len(context[2]) > 1:
                server, channel, candidates, _key = context
                self._expected_url = 'pending'
                self._watchdog.start(self.START_TIMEOUT_MS)
                self._submit(self._prepare_channel, connection, self._request, cast,
                             self._device, server, channel, AUTO_PROFILE, candidates[1:])
                return
            self.failed.emit(message)

    def _cancel_load(self):
        self._request += 1
        self._watchdog.stop()
        self._playing = False
        self._expected_url = ''
        self._session_id = None
        self._auto_context = None
        relay, self._relay = self._relay, None
        if relay is not None:
            relay.close()

    def stop(self):
        self._cancel_load()
        if self._cast is not None:
            self._submit(self._command, self._connection, self._cast.media_controller.stop)

    def _audio_status(self, connection, volume, muted):
        if connection != self._connection or self._cast is None:
            return
        self._volume = max(0, min(100, volume))
        self._muted = bool(muted)
        self.audio_changed.emit(self._volume, self._muted)

    def request_profiles(self, server, key):
        self._submit(self._read_profiles, server, key)

    def _read_profiles(self, server, key):
        from .backend import create_backend
        backend = None
        try:
            backend = create_backend(server)
            profiles = backend.list_profiles()
            self._post(lambda: self.profiles_ready.emit(key, profiles, ''))
        except Exception:
            self._post(lambda: self.profiles_ready.emit(key, [], 'Could not read the server’s stream profiles.'))
        finally:
            if backend is not None:
                backend.close()

    def _command(self, connection, function, *args):
        if connection != self._connection or self._closed:
            return
        try:
            function(*args)
        except Exception:
            self._post(lambda: self._control_failed(connection))

    def _control_failed(self, connection):
        if connection == self._connection and self.is_connected:
            self.operation_failed.emit('The Chromecast did not respond to the control command.')

    def set_volume(self, value):
        if self._cast is not None:
            self._submit(self._command, self._connection, self._cast.set_volume,
                         max(0, min(100, int(value))) / 100.0)

    def set_muted(self, muted):
        if self._cast is not None:
            self._submit(self._command, self._connection, self._cast.set_volume_muted, bool(muted))

    def _connection_lost(self, connection):
        if connection == self._connection and self.is_connected:
            self.disconnect()
            self.operation_failed.emit('The Chromecast connection was lost.')

    def disconnect(self):
        self._connection += 1
        self._cancel_load()
        cast, self._cast = self._cast, None
        self._device = None
        if cast is not None:
            self._submit(self._release, cast, True)
        self.disconnected.emit()

    def _release(self, cast, stop=False):
        with self._resource_lock:
            self._pending_resources.discard(('cast', cast))
        if stop:
            try:
                cast.media_controller.stop()
            except Exception:
                pass
        try:
            cast.disconnect(timeout=2)
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        self.disconnect()
        self._closed = True
        with self._resource_lock:
            resources = list(self._pending_resources)
            self._pending_resources.clear()
        for kind, resource in resources:
            if kind == 'relay':
                resource.close()
            else:
                self._executor.submit(self._release, resource)
        self._executor.shutdown(wait=False)


__all__ = ['CastDevice', 'CastManager', 'cast_media_type', 'cast_url_error']

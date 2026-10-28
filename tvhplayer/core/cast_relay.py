"""Temporary, single-stream HTTP URLs for a Cast receiver on the LAN."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import secrets
import socket
import threading
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests

from .proxy import configure_session
from .urls import TvhHttpAuth


def local_address(receiver):
    """Ask the routing table which local interface reaches this receiver."""
    for family, kind, protocol, _, address in socket.getaddrinfo(receiver, 8009, type=socket.SOCK_DGRAM):
        try:
            with socket.socket(family, kind, protocol) as sock:
                sock.connect(address)
                return sock.getsockname()[0]
        except OSError:
            continue
    raise OSError('No network route to the Chromecast')


def media_type(value, url):
    value = (value or '').split(';', 1)[0].strip().lower()
    if value and value not in ('application/octet-stream', 'binary/octet-stream'):
        return value
    path = urlsplit(url).path.lower()
    if path.endswith('.m3u8'):
        return 'application/vnd.apple.mpegurl'
    if path.endswith(('.mp4', '.m4v')):
        return 'video/mp4'
    if path.endswith('.webm'):
        return 'video/webm'
    return 'video/mp2t'


class CastRelay:
    """Expose only explicitly registered media URLs until playback stops.

    No file browsing or arbitrary URL parameter is exposed. Each playback has
    an unguessable path, a selected LAN interface, and its own HTTP server.
    HLS playlists register their referenced segments, keys and sub-playlists.
    """

    def __init__(self, source, receiver, bind_address=None):
        self.source = source
        self.address = bind_address or local_address(receiver)
        self._paths = {}
        self._lock = threading.Lock()
        self._responses = set()
        self._closed = threading.Event()
        self._root = '/' + secrets.token_urlsafe(24) + '/'
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                relay._serve(self, False)

            def do_HEAD(self):
                relay._serve(self, True)

            def do_OPTIONS(self):
                with relay._lock:
                    allowed = self.path in relay._paths and not relay._closed.is_set()
                if not allowed:
                    self.send_error(404)
                    return
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Range')
                self.end_headers()

            def log_message(self, *_args):
                pass  # Neither upstream credentials nor playback tokens enter logs.

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            address_family = socket.AF_INET6 if ':' in relay.address else socket.AF_INET

        self._server = Server((self.address, 0), Handler)
        host = f'[{self.address}]' if ':' in self.address else self.address
        self.origin = f'http://{host}:{self._server.server_port}'
        self.url = self._register(source)
        self.content_type = media_type('', source)
        self.detected_content_type = ''
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={'poll_interval': 0.05}, daemon=True)
        self._thread.start()

    def _register(self, url):
        if urlsplit(url).scheme not in ('http', 'https'):
            raise ValueError('The stream references an unsupported URL')
        with self._lock:
            if len(self._paths) >= 10000:
                raise ValueError('The stream playlist has too many resources')
            # Reuse live playlist entries rather than growing for each refresh.
            for path, existing in self._paths.items():
                if existing == url:
                    return self.origin + path
            path = self._root + secrets.token_urlsafe(12)
            self._paths[path] = url
        return self.origin + path

    def _session(self, url):
        session = requests.Session()
        configure_session(session, url)
        parsed = urlsplit(url)
        if parsed.username is not None:
            session.auth = TvhHttpAuth(unquote(parsed.username), unquote(parsed.password or ''))
            host = parsed.netloc.rsplit('@', 1)[-1]
            url = urlunsplit(parsed._replace(netloc=host))
        else:
            original = urlsplit(self.source)
            if (original.username is not None
                    and (original.scheme, original.hostname, original.port)
                    == (parsed.scheme, parsed.hostname, parsed.port)):
                session.auth = TvhHttpAuth(unquote(original.username), unquote(original.password or ''))
        return session, url

    def inspect(self):
        """Use HEAD for metadata without opening a second live subscription."""
        session, url = self._session(self.source)
        try:
            with session.head(url, timeout=(3, 3), allow_redirects=True) as response:
                if response.ok:
                    value = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                    if value and value not in ('application/octet-stream', 'binary/octet-stream'):
                        self.detected_content_type = value
                    self.content_type = media_type(value, response.url)
        except requests.RequestException:
            pass  # Some TV servers implement GET only.
        finally:
            session.close()
        return self.content_type

    def _playlist(self, body, base):
        text = body.decode('utf-8-sig')
        lines = []
        for line in text.splitlines():
            if line and not line.startswith('#'):
                line = self._register(urljoin(base, line.strip()))
            elif line.startswith('#'):
                line = re.sub(r'URI="([^"]+)"',
                              lambda match: 'URI="' + self._register(urljoin(base, match[1])) + '"', line)
            lines.append(line)
        return ('\n'.join(lines) + '\n').encode('utf-8')

    def _serve(self, handler, head):
        with self._lock:
            source = self._paths.get(handler.path)
        if source is None or self._closed.is_set():
            handler.send_error(404)
            return
        session, url = self._session(source)
        response = None
        sent = False
        try:
            headers = {'Accept-Encoding': 'identity'}
            if handler.headers.get('Range'):
                headers['Range'] = handler.headers['Range']
            response = session.request('HEAD' if head else 'GET', url, headers=headers,
                                       stream=True, timeout=(5, 10), allow_redirects=True)
            with self._lock:
                if self._closed.is_set():
                    return
                self._responses.add(response)
            kind = (response.headers.get('Content-Type') or media_type('', response.url)).split(';', 1)[0].lower()
            playlist = kind in ('application/vnd.apple.mpegurl', 'application/x-mpegurl',
                                'audio/mpegurl', 'audio/x-mpegurl')
            body = None
            if playlist and not head and response.ok:
                chunks = []
                size = 0
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise ValueError('Stream playlist is too large')
                    chunks.append(chunk)
                body = self._playlist(b''.join(chunks), response.url)
            handler.send_response(response.status_code)
            handler.send_header('Content-Type', kind)
            handler.send_header('Access-Control-Allow-Origin', '*')
            handler.send_header('Access-Control-Expose-Headers', 'Content-Length, Content-Range, Accept-Ranges')
            if body is not None:
                handler.send_header('Content-Length', str(len(body)))
            elif not playlist:
                for name in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
                    if name == 'Content-Length' and response.headers.get('Content-Encoding'):
                        continue
                    if name in response.headers:
                        handler.send_header(name, response.headers[name])
            handler.end_headers()
            sent = True
            if not head:
                if body is not None:
                    handler.wfile.write(body)
                else:
                    for chunk in response.iter_content(8192):
                        if self._closed.is_set():
                            break
                        handler.wfile.write(chunk)
        except (requests.RequestException, OSError, ValueError):
            if not sent:
                try:
                    handler.send_error(502, 'Could not read the TV stream')
                except OSError:
                    pass
        finally:
            if response is not None:
                with self._lock:
                    self._responses.discard(response)
                response.close()
            session.close()

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        self._server.shutdown()
        self._server.server_close()
        # Wake blocked reads without waiting for their HTTP read timeout.
        with self._lock:
            responses = list(self._responses)
        for response in responses:
            try:
                connection = response.raw._connection
                sock = connection.sock if connection is not None else None
                if sock is None:
                    sock = response.raw._fp.fp.raw._sock
                sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass


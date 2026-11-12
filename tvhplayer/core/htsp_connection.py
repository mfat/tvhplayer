"""HTSP TCP client: hello, digest auth, sequenced RPC, async drain.

Follows Kodi pvr.hts (`HTSPConnection.cpp`): SHA-1 digest is
`sha1(password + challenge)` and a digest is always sent so Tvheadend
evaluates the username. Client protocol version matches pvr.hts (38).
"""

from __future__ import annotations

import errno
import hashlib
import logging
import select
import socket
import struct
import threading
import time
from typing import Callable, Optional

from .errors import TvhAuthError, TvhConnectionError, TvhError
from .htsmsg import Binary, read_message, serialize

log = logging.getLogger(__name__)

HTSP_CLIENT_VERSION = 38
HTSP_MIN_SERVER_VERSION = 26
CLIENT_NAME = 'TVHplayer'
DEFAULT_TIMEOUT = 10.0


def htsp_digest(password: str, challenge: bytes) -> bytes:
    """Same construction as pvr.hts SendAuth and Tvheadend htsp_server.c."""
    password_bytes = (password or '').encode('utf-8')
    return hashlib.sha1(password_bytes + challenge).digest()


class HtspConnection:
    def __init__(self, host, port, timeout=DEFAULT_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._sock = None
        self._rx = bytearray()
        self._lock = threading.RLock()
        self._seq = 0
        self._reader = None
        self._reader_stop = threading.Event()
        self._condition = threading.Condition()
        self._pending = {}
        self._reader_error = None
        self._challenge = b''
        self._digest = None
        self._username = ''
        self.htsp_version = 0
        self.server_name = ''
        self.server_version = ''
        self.webroot = ''
        self.capabilities = []

    def connect(self):
        self.close()
        self._rx = bytearray()
        try:
            self._sock = socket.create_connection((self.host, self.port), self.timeout)
            self._sock.settimeout(self.timeout)
        except OSError as exc:
            raise TvhConnectionError(f'HTSP connect {self.host}:{self.port} failed: {exc}') from exc

    def close(self):
        self._reader_stop.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join()
        self._reader = None
        self._rx = bytearray()
        with self._condition:
            self._reader_error = TvhConnectionError('HTSP connection closed')
            self._condition.notify_all()

    def start_reader(self, on_async):
        """Give one thread ownership of reads; RPC callers only send and wait."""
        with self._lock:
            if self._reader is not None:
                return
            if self._sock is None:
                raise TvhConnectionError('HTSP connection closed')
            self._reader_stop = threading.Event()
            self._reader_error = None
            self._reader = threading.Thread(
                target=self._read_loop, args=(self._sock, self._reader_stop, on_async),
                name='htsp-metadata', daemon=True,
            )
            self._reader.start()

    def _read_loop(self, sock, stop, on_async):
        try:
            while not stop.is_set():
                # Parse only complete frames: an idle or fragmented stream must
                # not discard a partially received length header or payload.
                if not self._message_ready():
                    if not select.select([sock], [], [], 0.2)[0]:
                        continue
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise TvhConnectionError('HTSP connection closed')
                    self._rx.extend(chunk)
                    continue
                msg = self._recv()
                if 'seq' in msg:
                    with self._condition:
                        pending = self._pending.get(msg['seq'])
                        if pending is not None:
                            pending.append(msg)
                        self._condition.notify_all()
                else:
                    on_async(msg)
                    with self._condition:
                        self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                self._reader_error = TvhConnectionError(f'HTSP reader stopped: {exc}')
                self._condition.notify_all()
        finally:
            if self._sock is sock:
                self._sock = None
            sock.close()

    def wait_for(self, predicate, timeout=30.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while not predicate():
                if self._reader_error is not None:
                    raise self._reader_error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TvhConnectionError('HTSP read timed out')
                self._condition.wait(remaining)

    def _recv_exact(self, size: int) -> bytes:
        while len(self._rx) < size:
            try:
                chunk = self._sock.recv(max(size - len(self._rx), 4096))
            except socket.timeout as exc:
                raise TvhConnectionError('HTSP read timed out') from exc
            except OSError as exc:
                raise TvhConnectionError(f'HTSP read failed: {exc}') from exc
            if not chunk:
                raise TvhConnectionError('HTSP connection closed')
            self._rx.extend(chunk)
        data = bytes(self._rx[:size])
        del self._rx[:size]
        return data

    def _message_ready(self) -> bool:
        if len(self._rx) < 4:
            return False
        (size,) = struct.unpack('>I', self._rx[:4])
        if size > 16 * 1024 * 1024:
            raise TvhError(f'HTSMSG too large ({size} bytes)')
        return len(self._rx) >= 4 + size

    def _read_available(self):
        """Pull bytes already queued on the socket into the receive buffer."""
        sock = self._sock
        old_timeout = sock.gettimeout()
        sock.setblocking(False)
        try:
            while True:
                try:
                    chunk = sock.recv(65536)
                except BlockingIOError:
                    break
                except socket.timeout:
                    break
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    raise TvhConnectionError(f'HTSP read failed: {exc}') from exc
                if not chunk:
                    raise TvhConnectionError('HTSP connection closed')
                self._rx.extend(chunk)
        finally:
            sock.settimeout(old_timeout)

    def drain_async(self, on_async: Optional[Callable] = None) -> int:
        """Dispatch async messages already buffered, without waiting for new ones.

        Tvheadend pushes dvrEntryUpdate on this socket after enableAsyncMetadata.
        Those messages sit unread until the next RPC, so a stop that only looks
        at the cached list still sees the entry as scheduled while the server
        is already recording.
        """
        with self._lock:
            if self._reader is not None:
                if self._reader_error is not None:
                    raise self._reader_error
                return 0  # The reader continuously dispatches metadata.
            if self._sock is None:
                return 0
            self._read_available()
            count = 0
            while self._message_ready():
                msg = self._recv()
                count += 1
                if on_async:
                    on_async(msg)
            return count

    def _send(self, msg: dict):
        payload = serialize(msg)
        sock = self._sock
        if sock is None:
            raise TvhConnectionError('HTSP connection closed')
        try:
            sock.sendall(payload)
        except OSError as exc:
            raise TvhConnectionError(f'HTSP write failed: {exc}') from exc

    def _recv(self) -> dict:
        try:
            msg = read_message(self._recv_exact)
        except (ValueError, OSError) as exc:
            raise TvhConnectionError(f'HTSP decode failed: {exc}') from exc
        if not isinstance(msg, dict):
            raise TvhConnectionError('HTSP root message was not a map')
        return msg

    def rpc(self, method: str, args=None, timeout=None, on_async: Optional[Callable] = None):
        """Send an RPC and return the matching reply, dispatching async messages."""
        with self._lock:
            self._seq += 1
            seq = self._seq
            msg = dict(args or {})
            msg['method'] = method
            msg['seq'] = seq
            if self._username:
                msg['username'] = self._username
            if self._digest is not None:
                msg['digest'] = Binary(self._digest)
            if self._reader is not None:
                pending = []
                with self._condition:
                    if self._reader_error is not None:
                        raise self._reader_error
                    self._pending[seq] = pending
                try:
                    self._send(msg)
                    self.wait_for(lambda: bool(pending), self.timeout if timeout is None else timeout)
                    reply = pending[0]
                    if reply.get('noaccess'):
                        raise TvhAuthError(f'HTSP {method}: access denied')
                    if reply.get('error'):
                        raise TvhError(f"HTSP {method}: {reply['error']}")
                    return reply
                except TvhConnectionError:
                    self.close()
                    raise
                finally:
                    with self._condition:
                        self._pending.pop(seq, None)
            old_timeout = self._sock.gettimeout() if self._sock else None
            if timeout is not None:
                self._sock.settimeout(timeout)
            try:
                self._send(msg)
                while True:
                    reply = self._recv()
                    if reply.get('seq') == seq:
                        if reply.get('noaccess'):
                            raise TvhAuthError(f'HTSP {method}: access denied')
                        error = reply.get('error')
                        if error:
                            raise TvhError(f'HTSP {method}: {error}')
                        return reply
                    if on_async:
                        on_async(reply)
            finally:
                if self._sock is not None:
                    self._sock.settimeout(old_timeout)

    def hello(self, client_version: str = '3.4'):
        reply = self.rpc(
            'hello',
            {
                'htspversion': HTSP_CLIENT_VERSION,
                'clientname': CLIENT_NAME,
                'clientversion': client_version,
            },
        )
        self.htsp_version = int(reply.get('htspversion') or 0)
        self.server_name = reply.get('servername') or 'Tvheadend'
        self.server_version = reply.get('serverversion') or ''
        self.webroot = reply.get('webroot') or ''
        caps = reply.get('servercapability') or []
        if isinstance(caps, list):
            self.capabilities = [str(item) for item in caps]
        else:
            self.capabilities = []
        challenge = reply.get('challenge')
        if isinstance(challenge, (bytes, bytearray)):
            self._challenge = bytes(challenge)
        else:
            self._challenge = b''
        if self.htsp_version < HTSP_MIN_SERVER_VERSION:
            raise TvhError(
                f'Server HTSP v{self.htsp_version} is older than required v{HTSP_MIN_SERVER_VERSION}'
            )
        log.info(
            'HTSP connected to %s / %s (HTSPv%d)',
            self.server_name,
            self.server_version,
            self.htsp_version,
        )
        return reply

    def authenticate(self, username: str, password: str, on_async=None):
        """Always send a digest, matching pvr.hts SendAuth."""
        self._username = username or ''
        self._digest = htsp_digest(password, self._challenge)
        reply = self.rpc('authenticate', on_async=on_async)
        if reply.get('noaccess'):
            raise TvhAuthError('HTSP authentication failed')
        return reply

    def recv_until(self, predicate, timeout=30.0, on_async=None):
        """Read async messages until predicate(msg) is true."""
        with self._lock:
            if self._reader is not None:
                raise TvhError('Use wait_for while the HTSP metadata reader is running')
            old_timeout = self._sock.gettimeout() if self._sock else None
            self._sock.settimeout(timeout)
            try:
                while True:
                    msg = self._recv()
                    if on_async:
                        on_async(msg)
                    if predicate(msg):
                        return msg
            finally:
                if self._sock is not None:
                    self._sock.settimeout(old_timeout)

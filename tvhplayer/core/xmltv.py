"""Load a playlist's programme guide (XMLTV) into Tvheadend. No Qt imports.

Tvheadend cannot download XMLTV from a web address by itself. A server on
this machine takes the file through its External XMLTV socket. A server
elsewhere only gets the address when it already has an XMLTV URL grabber
script, which some Docker images ship.
"""

from __future__ import annotations

import os
import socket
import stat
import tempfile
import zlib

import requests

from .errors import PlaylistError
from .proxy import configure_session, is_loopback_url

GUIDE_FAILED = 'The program guide could not be loaded.'
MAX_GUIDE_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60
SEND_TIMEOUT = 600


def download_guide(url: str, folder=None) -> str:
    """Save the guide, unpacked when gzipped, and return the file path."""
    handle, path = tempfile.mkstemp(prefix='tvhplayer-guide-', suffix='.xml', dir=folder)
    try:
        with os.fdopen(handle, 'wb') as out, requests.Session() as session:
            configure_session(session, url)
            with session.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True) as response:
                if response.status_code >= 400:
                    raise PlaylistError(GUIDE_FAILED)
                unpack = None
                size = 0
                for chunk in response.iter_content(256 * 1024):
                    if unpack is None:
                        # wbits 16 + MAX_WBITS reads the gzip container.
                        unpack = zlib.decompressobj(16 + zlib.MAX_WBITS) if chunk[:2] == b'\x1f\x8b' else False
                    data = unpack.decompress(chunk) if unpack else chunk
                    size += len(data)
                    if size > MAX_GUIDE_BYTES:
                        raise PlaylistError(GUIDE_FAILED)
                    out.write(data)
                if unpack:
                    out.write(unpack.flush())
    except (requests.RequestException, zlib.error, OSError) as exc:
        os.unlink(path)
        raise PlaylistError(GUIDE_FAILED) from exc
    except PlaylistError:
        os.unlink(path)
        raise
    return path


def send_guide(socket_path: str, file_path: str) -> None:
    """Write the file to Tvheadend's XMLTV socket, which reads until we close."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(SEND_TIMEOUT)
            sock.connect(socket_path)
            with open(file_path, 'rb') as handle:
                sock.sendfile(handle)
    except OSError as exc:
        raise PlaylistError(GUIDE_FAILED) from exc


def usable_socket(server, path: str) -> bool:
    """True when ``path`` is a socket on this machine that belongs to ``server``."""
    if not path or not is_local_server(server):
        return False
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return False


def is_local_server(server) -> bool:
    return bool(server.get('builtin')) or is_loopback_url(server.get('url'))


def load_guide(admin, server, url: str, new_channels: bool) -> bool:
    """Load the guide at ``url`` into the server. Returns False when it has no way in.

    Tvheadend links XMLTV channels to its channels on the first pass and
    drops their programmes, so the file is sent twice when channels are new.
    """
    socket_path = admin.enable_xmltv_socket() if is_local_server(server) else ''
    if usable_socket(server, socket_path):
        path = download_guide(url)
        try:
            for _ in range(2 if new_channels else 1):
                send_guide(socket_path, path)
        finally:
            os.unlink(path)
        return True
    return admin.use_url_grabber(url)

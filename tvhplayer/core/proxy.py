"""HTTP proxy settings per consumer. No Qt imports.

libvlc 3.0 sends every http:// stream through ``http_proxy`` and ignores
``no_proxy``, and it reads the variable from this process. The player hides
``http_proxy`` before VLC runs. requests and ffmpeg get the saved value back
and keep honoring ``no_proxy``. A server on this machine is always reached
directly.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

import requests

_HIDDEN = object()
_saved_http_proxy = _HIDDEN


def hide_http_proxy_from_vlc() -> None:
    """Remove ``http_proxy`` from this process once, keeping its value for others."""
    global _saved_http_proxy
    if _saved_http_proxy is _HIDDEN:
        _saved_http_proxy = os.environ.pop('http_proxy', None)


def http_proxy() -> str | None:
    if _saved_http_proxy is _HIDDEN:
        return os.environ.get('http_proxy')
    return _saved_http_proxy


def is_loopback_url(url) -> bool:
    host = urlparse(url or '').hostname or ''
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def configure_session(session, base_url) -> None:
    """Point a requests session at the right proxy for one Tvheadend server."""
    if is_loopback_url(base_url):
        session.trust_env = False
        return
    proxy = http_proxy()
    if proxy and not requests.utils.should_bypass_proxies(base_url, no_proxy=None):
        session.proxies.setdefault('http', proxy)


def child_env(url, base=None) -> dict:
    """Environment for a child that fetches ``url`` (ffmpeg, Tvheadend)."""
    env = dict(os.environ if base is None else base)
    if url is not None and is_loopback_url(url):
        env.pop('http_proxy', None)
        env.pop('HTTP_PROXY', None)
        return env
    proxy = http_proxy()
    if proxy:
        env['http_proxy'] = proxy
    return env

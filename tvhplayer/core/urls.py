from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit

from requests.auth import HTTPBasicAuth, HTTPDigestAuth


class TvhHttpAuth(HTTPDigestAuth):
    """Basic on the first request, digest when the server challenges for it.

    Tvheadend's ``tvh-json.py`` installs both handlers unless one scheme is
    pinned. Plain-auth servers accept the Basic header immediately. A
    digest-only server returns 401 and ``HTTPDigestAuth`` retries with the
    digest response.
    """

    def __call__(self, request):
        request = HTTPDigestAuth.__call__(self, request)
        if not getattr(self._thread_local, 'last_nonce', None):
            request = HTTPBasicAuth.__call__(self, request)
        return request


def http_base_url(url):
    """Return a scheme://host[:port] base with no trailing slash."""
    url = (url or '').strip()
    if not url:
        raise ValueError('Server URL is empty')
    if not url.startswith(('http://', 'https://')):
        if '://' in url:
            raise ValueError('Use http:// or https://')
        url = 'http://' + url
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError('Server URL has no host')
    path = parsed.path.rstrip('/')
    netloc = parsed.netloc
    if parsed.scheme == 'http' and parsed.port is None:
        netloc += ':9981'
    base = f'{parsed.scheme}://{netloc}'
    return base + path if path else base


def origin_url(url):
    """Return scheme://host[:port] with any webroot path dropped."""
    parsed = urlparse(http_base_url(url))
    return f'{parsed.scheme}://{parsed.netloc}'


def http_host_port(url):
    """Return (hostname, http_port) from a server URL."""
    parsed = urlparse(http_base_url(url))
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == 'https' else 80
    return parsed.hostname, port


def htsp_host_port(url, htsp_port=None):
    """Return (hostname, htsp_port) for an HTSP connection."""
    host, _http_port = http_host_port(url)
    if htsp_port in (None, '', 0, '0'):
        htsp_port = 9982
    return host, int(htsp_port)


def http_auth(server):
    """Return requests auth for the HTTP API, or None when no credentials are set.

    Playback URLs still use ``insert_basic_auth``. mpv and ffmpeg receive a
    URL, not this handler.
    """
    username = server.get('username') or ''
    password = server.get('password') or ''
    if username or password:
        return TvhHttpAuth(username, password)
    return None


def insert_basic_auth(url, username, password):
    """Embed user:pass in a URL for mpv/ffmpeg, which do not take an auth tuple.

    Both are percent-encoded: an ``@``, ``/``, ``#`` or ``?`` in them would
    otherwise end the login early and send the rest as the host or path.
    """
    if not username and not password:
        return url
    parsed = urlparse(url)
    host = parsed.hostname or ''
    port = f':{parsed.port}' if parsed.port else ''
    creds = f"{quote(username or '', safe='')}:{quote(password or '', safe='')}@"
    return parsed._replace(netloc=f'{creds}{host}{port}').geturl()


def append_profile(url, profile):
    """Add ``?profile=`` to a stream URL. An empty profile leaves the URL alone."""
    if not profile:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['profile'] = profile
    return urlunsplit(parts._replace(query=urlencode(query)))


def resolve_reference(base, reference, webroot=''):
    """Join a relative image or icon path onto the HTTP base.

    Absolute http(s) URLs are returned unchanged. ``webroot`` is prefixed
    only when ``base`` does not already end with it.
    """
    reference = (reference or '').strip()
    if not reference:
        return ''
    if reference.startswith(('http://', 'https://')):
        return reference
    base = (base or '').rstrip('/')
    root = (webroot or '').strip('/')
    path = reference.lstrip('/')
    if root and not base.endswith('/' + root):
        base = f'{base}/{root}'
    return f'{base}/{path}'

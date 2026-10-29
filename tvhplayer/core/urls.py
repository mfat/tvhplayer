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
        raise ValueError('Enter the server address')
    if not url.lower().startswith(('http://', 'https://')):
        if '://' in url:
            raise ValueError('Use http:// or https://')
        url = 'http://' + url
    if '?' in url or '#' in url:
        raise ValueError('Server address must not contain a query or fragment')
    if any(c in url for c in '\r\n\t'):
        raise ValueError('Server address must not contain control characters')
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError('Invalid host name or IP address') from exc
    if not parsed.hostname:
        raise ValueError('Enter a host name or IP address')
    host = parsed.hostname
    if any(c.isspace() for c in host):
        raise ValueError('Host name must not contain spaces')
    authority = parsed.netloc.rsplit('@', 1)[-1]
    if authority.startswith('['):
        suffix = authority.partition(']')[2]
        if suffix and not suffix.startswith(':'):
            raise ValueError('Invalid port number')
    else:
        if authority.count(':') > 1:
            raise ValueError('Enclose IPv6 addresses in brackets')
        suffix = ':' + authority.split(':', 1)[1] if ':' in authority else ''
    if suffix:
        port = suffix[1:]
        if not (port.isascii() and port.isdigit()):
            raise ValueError('Invalid port number')
        if not 1 <= int(port) <= 65535:
            raise ValueError('Port must be between 1 and 65535')
    if all(c in '0123456789.' for c in host):
        parts = host.split('.')
        if len(parts) != 4 or not all(parts):
            raise ValueError('Invalid IP address format')
        if any(int(part) > 255 for part in parts):
            raise ValueError('IP numbers must be between 0 and 255')
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
    if ':' in host:
        host = f'[{host}]'
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

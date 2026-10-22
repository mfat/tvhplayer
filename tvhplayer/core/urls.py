from urllib.parse import urlparse


def http_base_url(url):
    """Return a scheme://host[:port] base with no trailing slash."""
    url = (url or '').strip()
    if not url:
        raise ValueError('Server URL is empty')
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError('Server URL has no host')
    path = parsed.path.rstrip('/')
    base = f'{parsed.scheme}://{parsed.netloc}'
    return base + path if path else base


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
    """Return a requests auth tuple, or None when no credentials are set."""
    username = server.get('username') or ''
    password = server.get('password') or ''
    if username or password:
        return (username, password)
    return None


def insert_basic_auth(url, username, password):
    """Embed user:pass in a URL for VLC/ffmpeg, which do not take an auth tuple."""
    if not username and not password:
        return url
    parsed = urlparse(url)
    host = parsed.hostname or ''
    port = f':{parsed.port}' if parsed.port else ''
    creds = f'{username}:{password}@'
    return parsed._replace(netloc=f'{creds}{host}{port}').geturl()

"""A stand-in for ffmpeg that the built-in server runs for playlist channels. No Qt imports.

Most HLS addresses name a list of qualities. Before it sends anything, ffmpeg
opens every quality on the list and reads a piece of video from each. On a
slow site that takes longer than the server waits for a stream (the network's
max_timeout), and the channel fails although a player that opens one quality
plays it. The stand-in reads the list first and gives ffmpeg only the best
quality, the one ffmpeg would have played.

The installed script is this file run by the app's Python, so it uses the
standard library only. Anything unexpected passes ffmpeg its arguments unchanged.
"""

import os
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

FETCH_TIMEOUT = 8
MAX_LIST_BYTES = 1024 * 1024
# What ffmpeg itself sends when the playlist names no user agent.
DEFAULT_USER_AGENT = 'Lavf/60.16.100'

_ATTRIBUTE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def best_variant(text, base_url):
    """Address of the highest-bandwidth quality in a master playlist, or None.

    None as well when that quality takes its sound or picture from a separate
    rendition, which ffmpeg would also have to open.
    """
    lines = [line.strip() for line in text.lstrip('﻿').splitlines()]
    if not lines or not lines[0].startswith('#EXTM3U'):
        return None
    renditions = set()
    variants = []
    pending = None
    for line in lines:
        if line.startswith('#EXT-X-MEDIA:'):
            attrs = _attributes(line)
            if attrs.get('TYPE') in ('AUDIO', 'VIDEO') and attrs.get('URI'):
                renditions.add((attrs['TYPE'], attrs.get('GROUP-ID', '')))
        elif line.startswith('#EXT-X-STREAM-INF:'):
            pending = _attributes(line)
        elif line and not line.startswith('#') and pending is not None:
            variants.append((pending, line))
            pending = None
    if not variants:
        return None
    attrs, uri = max(variants, key=lambda variant: _number(variant[0].get('BANDWIDTH')))
    if any((kind, attrs[kind]) in renditions for kind in ('AUDIO', 'VIDEO') if kind in attrs):
        return None
    url = urljoin(base_url, uri)
    return url if url.split(':', 1)[0].lower() in ('http', 'https') else None


def request_headers(options):
    """The HTTP headers ffmpeg would send, from the options before ``-i``."""
    headers = {'User-Agent': DEFAULT_USER_AGENT}
    for index, option in enumerate(options[:-1]):
        value = options[index + 1]
        if option == '-headers':
            for line in re.split(r'\r\n|\r|\n', value):
                key, sep, val = line.partition(':')
                if sep and key.strip() and val.strip():
                    headers[key.strip()] = val.strip()
        elif option in ('-user_agent', '-user-agent'):
            headers['User-Agent'] = value
        elif option == '-referer':
            headers['Referer'] = value
    return headers


def fetch_list(url, headers, timeout=FETCH_TIMEOUT):
    """``(text, address after redirects)`` of an M3U playlist, or None for anything else."""
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # Segments would need the cookies ffmpeg keeps from the list.
        if response.headers.get_all('Set-Cookie'):
            return None
        head = response.read(16)
        if not head.lstrip(b'\xef\xbb\xbf').startswith(b'#EXTM3U'):
            return None
        body = head + response.read(MAX_LIST_BYTES)
        if len(body) > MAX_LIST_BYTES:
            return None
        return body.decode('utf-8', errors='replace'), response.geturl()


def with_best_variant(args, fetch=fetch_list):
    """ffmpeg arguments with an HLS list of qualities replaced by the best one."""
    inputs = [index for index, arg in enumerate(args) if arg == '-i']
    if len(inputs) != 1 or inputs[0] + 1 >= len(args):
        return args
    position = inputs[0] + 1
    url = args[position]
    if url.split(':', 1)[0].lower() not in ('http', 'https'):
        return args
    fetched = fetch(url, request_headers(args[:inputs[0]]))
    if not fetched:
        return args
    variant = best_variant(*fetched)
    if not variant:
        return args
    return args[:position] + [variant] + args[position + 1:]


def main(ffmpeg, args):
    try:
        args = with_best_variant(args)
    except Exception:
        pass
    os.execv(ffmpeg, [ffmpeg] + args)


def starter_path():
    xdg = os.environ.get('XDG_DATA_HOME')
    base = Path(xdg) if xdg else Path.home() / '.local' / 'share'
    # Named ffmpeg, so the app still reads the channel's command as an ffmpeg one.
    return base / 'tvhplayer' / 'bin' / 'ffmpeg'


def install_starter(ffmpeg, path=None, python=None):
    """Write the stand-in for ``ffmpeg`` and return its path, or None when it cannot run.

    A frozen build has no Python to run it. A shebang cannot hold a space.
    """
    python = sys.executable if python is None else python
    if getattr(sys, 'frozen', False) or not python or any(char.isspace() for char in python):
        return None
    path = Path(path) if path else starter_path()
    try:
        source = Path(__file__).read_text(encoding='utf-8')
        text = (
            f'#!{python} -I\n{source}\n\n'
            f"if __name__ == '__main__':\n    main({str(ffmpeg)!r}, sys.argv[1:])\n"
        )
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f'.{path.name}.new')
            temporary.write_text(text, encoding='utf-8')
            os.chmod(temporary, 0o755)
            os.replace(temporary, path)
    except OSError:
        return None
    return str(path)


def _attributes(line):
    attrs = {}
    for match in _ATTRIBUTE.finditer(line.partition(':')[2]):
        attrs[match.group(1)] = match.group(2).strip('"')
    return attrs


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

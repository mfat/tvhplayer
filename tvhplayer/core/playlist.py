"""Read M3U playlists and build the stream command for each channel. No Qt imports.

The reader takes the Kodi IPTV Simple dialect, which is what real playlists
use. Every channel is received through an ffmpeg command, so its stream always
carries program 1 and reconnects when the source drops. See
docs/proposals/playlist-import.md.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

import requests

from .errors import PlaylistError
from .proxy import configure_session

NOT_A_PLAYLIST = 'This file is not a TV playlist.'
NO_CHANNELS = 'This playlist has no channels TVHplayer can add.'
DOWNLOAD_FAILED = 'Could not download the playlist. Check the address and your internet connection.'
FILE_FAILED = 'Could not open the playlist file.'
TOO_LARGE = 'This playlist is too large to import.'
ONLY_FILMS = 'This playlist has only films and series, and TVHplayer imports only TV channels.'

MAX_PLAYLIST_BYTES = 256 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30
# File and path stems that say nothing about the playlist; the host names it instead.
_GENERIC_STEMS = {'', 'playlist', 'index', 'get', 'channels', 'list', 'tv', 'iptv', 'live', 'm3u', 'm3u8', 'playlist_m3u'}

# Tvheadend's spawn_parse_args keeps at most 63 arguments.
MAX_PIPE_ARGS = 63

_ATTRIBUTE = re.compile(r'''([A-Za-z0-9_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"',]+))''')
_CHANNEL_NUMBER = re.compile(r'^\d+(\.\d+)?$')
# Xtream Codes servers list films and series episodes as /movie/<user>/<pass>/<id>.<ext>.
# As a channel a film always starts from the beginning and Tvheadend restarts it when
# it ends, and a large server lists hundreds of thousands of them: each would be a mux,
# service, and channel the server opens once to scan.
_VOD_PATH = re.compile(r'^/(movie|series)/[^/]+/[^/]+/[^/]+$')
_HEADER_NAMES = {
    'user-agent': 'User-Agent',
    'referer': 'Referer',
    'referrer': 'Referer',
    'origin': 'Origin',
    'cookie': 'Cookie',
}
_VLC_HEADERS = {
    'http-user-agent': 'User-Agent',
    'http-referrer': 'Referer',
    'http-referer': 'Referer',
    'http-origin': 'Origin',
    'http-cookie': 'Cookie',
}
_SPAWN_ESCAPES = {'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
_QUOTE_ESCAPES = {'\\': '\\\\', '"': '\\"', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


@dataclass
class PlaylistEntry:
    name: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    groups: List[str] = field(default_factory=list)
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class Playlist:
    entries: List[PlaylistEntry]
    guide_url: str = ''
    # Films and series episodes left out; see _VOD_PATH.
    films: int = 0


@dataclass
class ChannelPlan:
    """One mux to write. ``key`` matches the same entry on the next refresh."""

    key: str
    name: str
    url: str
    number: str = ''
    icon: str = ''
    epg_id: str = ''
    groups: List[str] = field(default_factory=list)


@dataclass
class SkippedEntry:
    name: str
    reason: str


def decode_playlist(data: bytes) -> str:
    """UTF-8, with or without a BOM, falling back to Latin-1."""
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def is_web_address(location: str) -> bool:
    return (location or '').strip().lower().startswith(('http://', 'https://'))


def load_playlist(location: str) -> Playlist:
    """Download or read a playlist and parse it. Raises ``PlaylistError``."""
    location = (location or '').strip()
    if is_web_address(location):
        data = _download(location)
    else:
        path = unquote(location[7:]) if location.startswith('file://') else location
        try:
            with open(path, 'rb') as handle:
                data = handle.read(MAX_PLAYLIST_BYTES + 1)
        except OSError as exc:
            raise PlaylistError(FILE_FAILED) from exc
        if len(data) > MAX_PLAYLIST_BYTES:
            raise PlaylistError(TOO_LARGE)
    return parse_playlist(decode_playlist(data))


def playlist_name(location: str) -> str:
    """A short name: the file name, or the web host when the file name is generic."""
    location = (location or '').strip()
    if is_web_address(location):
        parts = urlsplit(location)
        stem = posixpath.splitext(posixpath.basename(unquote(parts.path).rstrip('/')))[0]
        host = parts.hostname or ''
        if host.startswith('www.'):
            host = host[4:]
        return stem if stem.lower() not in _GENERIC_STEMS else (host or 'Playlist')
    path = location[7:] if location.startswith('file://') else location
    stem = posixpath.splitext(posixpath.basename(path.replace('\\', '/').rstrip('/')))[0]
    return stem or 'Playlist'


def parse_playlist(text: str) -> Playlist:
    """Raise ``PlaylistError`` when the text is not an M3U playlist or has only films."""
    lines = (text or '').lstrip('﻿').splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or not lines[0].strip().upper().startswith('#EXTM3U'):
        raise PlaylistError(NOT_A_PLAYLIST)
    header = _attributes(lines[0].strip()[7:])
    guide_url = ''
    for value in (header.get('x-tvg-url', ''), header.get('url-tvg', '')):
        for candidate in value.split(','):
            candidate = candidate.strip()
            if candidate.startswith(('http://', 'https://')):
                guide_url = candidate
                break
        if guide_url:
            break

    entries = []
    films = 0
    pending = None
    extgrp: List[str] = []
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith('#EXTINF:'):
            # Read only once its address shows it is a channel, not a film.
            pending = {'extinf': line[8:], 'headers': {}}
        elif upper.startswith('#EXTGRP:'):
            extgrp = _split_groups(line[8:], ';')
        elif upper.startswith('#EXTVLCOPT:'):
            key, _, value = line[11:].partition('=')
            header = _VLC_HEADERS.get(key.strip().lower())
            if header and value.strip():
                if pending is None:
                    pending = {'extinf': None, 'headers': {}}
                pending['headers'][header] = value.strip()
        elif line.startswith('#'):
            continue
        else:
            info = pending or {'extinf': None, 'headers': {}}
            pending = None
            url, url_headers = _split_url(line)
            if _is_vod(url):
                films += 1
                continue
            headers = dict(info['headers'])
            headers.update(url_headers)
            attrs, name = _extinf(info['extinf']) if info['extinf'] is not None else ({}, '')
            if 'group-title' in attrs:
                groups = _split_groups(attrs['group-title'], ';')
            elif 'tvh-tags' in attrs:
                groups = _split_groups(attrs['tvh-tags'], '|')
            else:
                groups = list(extgrp)
            name = name or attrs.get('tvg-name', '').strip() or _name_from_url(url)
            entries.append(PlaylistEntry(name=name, url=url, headers=headers, groups=groups, attrs=attrs))
    if films and not entries:
        raise PlaylistError(ONLY_FILMS)
    return Playlist(entries=entries, guide_url=guide_url, films=films)


def _is_vod(url: str) -> bool:
    try:
        return bool(_VOD_PATH.match(urlsplit(url).path))
    except ValueError:
        return False


def playlist_commands(playlist: Playlist) -> List[PlaylistEntry]:
    """Entries that would run a program from the playlist other than ffmpeg."""
    return [
        entry for entry in playlist.entries
        if entry.url.startswith('pipe://') and ffmpeg_input(entry.url[7:]) is None
    ]


def plan_channels(
    playlist: Playlist,
    ffmpeg: str,
    provider: str = '',
    allow_commands: bool = False,
) -> Tuple[List[ChannelPlan], List[SkippedEntry]]:
    """Turn entries into mux plans. ``ffmpeg`` is the path on the server."""
    plans = []
    skipped = []
    for entry in playlist.entries:
        url, reason = _stream_command(entry, ffmpeg, provider, allow_commands)
        if not url:
            skipped.append(SkippedEntry(entry.name, reason))
            continue
        plans.append(ChannelPlan(
            key='',
            name=entry.name,
            url=url,
            number=_channel_number(entry.attrs),
            icon=_icon(entry.attrs),
            epg_id=entry.attrs.get('tvg-id', '').strip(),
            groups=list(entry.groups),
        ))
    _assign_keys(plans)
    return plans, skipped


def ffmpeg_command(ffmpeg: str, url: str, headers=None, name: str = '', provider: str = '') -> str:
    """A ``pipe://`` command that remuxes ``url`` to MPEG-TS with program 1."""
    args = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error']
    if url.split(':', 1)[0].lower() in ('http', 'https'):
        args += [
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_delay_max', '5',
        ]
        args += _header_args(headers)
    args += ['-i', url, '-c', 'copy']
    args += _output_args(name, provider)
    return 'pipe://' + ' '.join(_quote(arg) for arg in args)


def shell_command(ffmpeg: str, command_args: List[str], name: str = '', provider: str = '') -> str:
    """Run a playlist's own program and remux its output with ffmpeg."""
    remux = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0', '-c', 'copy']
    remux += _output_args(name, provider)
    script = f'{shlex.join(command_args)} | {shlex.join(remux)}'
    return 'pipe://' + ' '.join(_quote(arg) for arg in ['/bin/sh', '-c', script])


def ffmpeg_input(command: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """Input address and headers of a ``pipe://`` ffmpeg command, or None.

    ``command`` is the text after ``pipe://``. Commands with more than one
    input, or that read from stdin, are not ffmpeg wrappers this app can rebuild.
    """
    args = tvh_split(command)
    if not args or posixpath.basename(args[0]) != 'ffmpeg':
        return None
    inputs = [index for index, arg in enumerate(args) if arg == '-i']
    if len(inputs) != 1 or inputs[0] + 1 >= len(args):
        return None
    url = args[inputs[0] + 1]
    if '://' not in url:
        return None
    headers = {}
    options = args[1:inputs[0]]
    for index, option in enumerate(options[:-1]):
        value = options[index + 1]
        if option == '-headers':
            for line in re.split(r'\r\n|\r|\n', value):
                key, sep, val = line.partition(':')
                if sep and key.strip() and val.strip():
                    headers[_header_name(key.strip())] = val.strip()
        elif option in ('-user_agent', '-user-agent'):
            headers['User-Agent'] = value
        elif option == '-referer':
            headers['Referer'] = value
    return url, headers


def tvh_split(command: str) -> List[str]:
    """Split a pipe command the way Tvheadend's ``spawn_parse_args`` does."""
    chars = list(command or '')
    args = []
    pos = 0
    while pos < len(chars) and len(args) < MAX_PIPE_ARGS:
        while pos < len(chars) and chars[pos] == ' ':
            pos += 1
        start = pos
        quote = None
        while pos < len(chars):
            char = chars[pos]
            if char == '\\':
                escaped = _SPAWN_ESCAPES.get(chars[pos + 1] if pos + 1 < len(chars) else '')
                if escaped:
                    chars[pos] = escaped
                    del chars[pos + 1]
                    pos += 1
                else:
                    del chars[pos]
                    if pos < len(chars):
                        pos += 1
            elif quote:
                if char == quote:
                    del chars[pos]
                    quote = None
                else:
                    pos += 1
            elif char in ('"', "'"):
                quote = char
                del chars[pos]
            elif char == ' ':
                break
            else:
                pos += 1
        if start != pos:
            args.append(''.join(chars[start:pos]))
            if pos < len(chars):
                pos += 1
    return args


def _download(url: str) -> bytes:
    with requests.Session() as session:
        configure_session(session, url)
        try:
            with session.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True) as response:
                if response.status_code >= 400:
                    raise PlaylistError(DOWNLOAD_FAILED)
                chunks = []
                size = 0
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > MAX_PLAYLIST_BYTES:
                        raise PlaylistError(TOO_LARGE)
                    chunks.append(chunk)
        except requests.RequestException as exc:
            raise PlaylistError(DOWNLOAD_FAILED) from exc
    return b''.join(chunks)


def _stream_command(entry, ffmpeg, provider, allow_commands):
    url = entry.url
    scheme = url.split(':', 1)[0].lower() if '://' in url else ''
    if scheme == 'pipe':
        wrapped = ffmpeg_input(url[7:])
        if wrapped is not None:
            inner_url, inner_headers = wrapped
            headers = dict(inner_headers)
            headers.update(entry.headers)
            return ffmpeg_command(ffmpeg, inner_url, headers, entry.name, provider), ''
        if not allow_commands:
            return '', 'It runs a program from the playlist.'
        args = tvh_split(url[7:])
        if not args:
            return '', 'It has no stream address.'
        return shell_command(ffmpeg, args, entry.name, provider), ''
    if scheme == 'file':
        return '', 'It is a file on another computer.'
    if not scheme:
        return '', 'It has no stream address.'
    return ffmpeg_command(ffmpeg, url, entry.headers, entry.name, provider), ''


def _header_args(headers):
    headers = dict(headers or {})
    args = []
    agent = headers.pop('User-Agent', '')
    if agent:
        args += ['-user_agent', agent]
    if headers:
        args += ['-headers', ''.join(f'{key}: {value}\r\n' for key, value in headers.items())]
    return args


def _output_args(name, provider):
    args = []
    if name:
        args += ['-metadata', f'service_name={name}']
    if provider:
        args += ['-metadata', f'service_provider={provider}']
    return args + ['-mpegts_service_id', '1', '-f', 'mpegts', '-mpegts_flags', 'resend_headers', 'pipe:1']


def _quote(arg: str) -> str:
    if arg and not any(char in arg for char in ' "\'\\\b\f\n\r\t'):
        return arg
    return '"' + ''.join(_QUOTE_ESCAPES.get(char, char) for char in arg) + '"'


def _attributes(text: str) -> Dict[str, str]:
    attrs = {}
    for match in _ATTRIBUTE.finditer(text or ''):
        value = next(group for group in match.groups()[1:] if group is not None)
        attrs[match.group(1).lower()] = value
    return attrs


def _extinf(text: str) -> Tuple[Dict[str, str], str]:
    """Attributes and the name after the first comma outside quotes."""
    quote = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == ',':
            return _attributes(text[:index]), text[index + 1:].strip()
    return _attributes(text), ''


def _split_url(line: str) -> Tuple[str, Dict[str, str]]:
    """Split Kodi's ``url|Key=value&Key=value`` header suffix."""
    if line.startswith('pipe://') or '|' not in line:
        return line, {}
    url, _, suffix = line.partition('|')
    headers = {}
    for part in suffix.split('&'):
        key, sep, value = part.partition('=')
        key = key.strip().lstrip('!')
        if sep and key and value.strip():
            headers[_header_name(key)] = unquote(value.strip())
    return url.strip(), headers


def _header_name(name: str) -> str:
    return _HEADER_NAMES.get(name.lower(), name)


def _split_groups(value: str, separator: str) -> List[str]:
    return [group.strip() for group in (value or '').split(separator) if group.strip()]


def _name_from_url(url: str) -> str:
    if url.startswith('pipe://'):
        return ''
    parts = urlsplit(url)
    return posixpath.basename(parts.path.rstrip('/')) or parts.hostname or ''


def _channel_number(attrs) -> str:
    for key in ('tvh-chnum', 'tvg-chno', 'channel-number'):
        value = (attrs.get(key) or '').strip()
        if _CHANNEL_NUMBER.match(value):
            return value
    return ''


def _icon(attrs) -> str:
    icon = (attrs.get('tvg-logo') or attrs.get('logo') or '').strip()
    return icon if icon.startswith(('http://', 'https://')) else ''


def _assign_keys(plans: List[ChannelPlan]) -> None:
    """Prefer a unique ``tvg-id``; otherwise the name, numbered when repeated."""
    id_counts: Dict[str, int] = {}
    for plan in plans:
        if plan.epg_id:
            id_counts[plan.epg_id] = id_counts.get(plan.epg_id, 0) + 1
    seen: Dict[str, int] = {}
    for plan in plans:
        if plan.epg_id and id_counts[plan.epg_id] == 1:
            base = f'id:{plan.epg_id}'
        else:
            base = f'name:{plan.name}'
        seen[base] = seen.get(base, 0) + 1
        plan.key = base if seen[base] == 1 else f'{base} #{seen[base]}'

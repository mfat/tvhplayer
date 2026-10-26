"""Programme guide sources: download, check, keep, and turn into one guide per server. No Qt imports.

A source is an XMLTV web address or file. Each download is checked before
it replaces the copy kept in the cache: a guide that fails to download, has
no programmes, or shrank to less than half of the last one is not used, and
the last good copy stays.

The server gets a guide written for it: one guide channel per TV channel,
named ``tvhplayer.<channel uuid>``, holding the programmes of the guide
channel matched to it, shifted for "+1" channels. ``guide_update`` sends it
and links each TV channel to its guide channel.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from calendar import timegm
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, IO, Iterable, Iterator, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

import requests

from .guide_match import Assignment, GuideChannel, GuideIndex, id_country, normalize_id
from .proxy import configure_session

MAX_GUIDE_BYTES = 2 * 1024 * 1024 * 1024
# Seconds to connect, and to wait for each piece; some guide sites are slow.
TIMEOUT = (30, 180)
SHRINK_LIMIT = 0.5
DEFAULT_HOURS = 12
UPDATE_HOURS = (6, 12, 24, 168, 0)
CHANNEL_PREFIX = 'tvhplayer.'
GUIDE_SUFFIX = ' (TVHplayer guide)'

DOWNLOAD_FAILED = 'Could not download the guide.'
NOT_A_GUIDE = 'This is not an XMLTV programme guide.'
NO_PROGRAMMES = 'The guide has no programmes.'
SHRANK = 'The new guide has far fewer programmes than the last one.'
FILE_FAILED = 'Could not open the guide file.'
TOO_LARGE = 'The guide is too large.'

_TIME = re.compile(r'^\s*(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?\s*([+-]\d{2}:?\d{2}|Z|UTC|GMT)?')


class GuideError(Exception):
    """A guide that could not be used, in words for the user."""


def is_web_address(location: str) -> bool:
    return (location or '').strip().lower().startswith(('http://', 'https://'))


@dataclass
class GuideSource:
    """A programme guide used for one server's channels, saved in tvhplayer.conf."""

    location: str
    server: str
    name: str = ''
    # Hours between updates; 0 updates only when asked.
    hours: int = DEFAULT_HOURS
    # The playlist this guide came with, so removing the playlist removes it.
    playlist: str = ''
    # When the copy in use was downloaded, and when it was last tried.
    updated: float = 0.0
    tried: float = 0.0
    error: str = ''

    @classmethod
    def from_dict(cls, data) -> 'GuideSource':
        data = data if isinstance(data, dict) else {}

        def number(key, kind, default):
            try:
                value = kind(data.get(key) or default)
            except (TypeError, ValueError):
                return default
            return value if value >= 0 else default

        return cls(
            location=str(data.get('location') or '').strip(),
            server=str(data.get('server') or ''),
            name=str(data.get('name') or ''),
            hours=number('hours', int, DEFAULT_HOURS) if data.get('hours') != 0 else 0,
            playlist=str(data.get('playlist') or ''),
            updated=number('updated', float, 0.0),
            tried=number('tried', float, 0.0),
            error=str(data.get('error') or ''),
        )

    def to_dict(self) -> dict:
        return {
            'location': self.location,
            'server': self.server,
            'name': self.name,
            'hours': self.hours,
            'playlist': self.playlist,
            'updated': self.updated,
            'tried': self.tried,
            'error': self.error,
        }

    def label(self) -> str:
        return self.name or guide_name(self.location)

    def is_due(self, now: Optional[float] = None) -> bool:
        """Whether an automatic update should download it again."""
        now = time.time() if now is None else now
        if not self.updated:
            # Never loaded: try again an hour after a failure.
            return now - self.tried >= 3600
        if not self.hours:
            return False
        return now - max(self.updated, self.tried) >= self.hours * 3600


def guide_name(location: str) -> str:
    """A short name for a guide address or file."""
    location = (location or '').strip()
    if is_web_address(location):
        host = re.sub(r'^https?://', '', location, flags=re.I).split('/', 1)[0]
        last = location.rstrip('/').rsplit('/', 1)[-1]
        last = re.sub(r'\.(xml|gz|xz)$', '', re.sub(r'\.(xml|gz|xz)$', '', last, flags=re.I), flags=re.I)
        return f'{host}: {last}' if last and last != host else host
    return Path(location).name or location


# --- Reading guide files -----------------------------------------------------


def open_guide(path: str) -> IO[bytes]:
    """Open a guide file, unpacking gzip and xz."""
    handle = open(path, 'rb')
    magic = handle.read(6)
    handle.seek(0)
    if magic[:2] == b'\x1f\x8b':
        return gzip.GzipFile(fileobj=handle, mode='rb')
    if magic == b'\xfd7zXZ\x00':
        return lzma.LZMAFile(handle, mode='rb')
    return handle


def parse_time(value: str) -> Tuple[Optional[int], bool]:
    """``(epoch seconds, has time zone)`` of an XMLTV time. Without a zone the time is read as UTC."""
    match = _TIME.match(value or '')
    if not match:
        return None, False
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        stamp = timegm((int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)))
    except (ValueError, OverflowError):
        return None, False
    if not zone:
        return stamp, False
    if zone in ('Z', 'UTC', 'GMT'):
        return stamp, True
    sign = -1 if zone[0] == '-' else 1
    digits = zone[1:].replace(':', '')
    offset = int(digits[:2]) * 3600 + int(digits[2:]) * 60
    return stamp - sign * offset, True


def format_time(stamp: int, zone: bool = True) -> str:
    text = time.strftime('%Y%m%d%H%M%S', time.gmtime(stamp))
    return f'{text} +0000' if zone else text


def _elements(handle: IO[bytes]) -> Iterator[ET.Element]:
    """The ``<channel>`` and ``<programme>`` elements, each freed after use."""
    root = None
    try:
        for event, element in ET.iterparse(handle, events=('start', 'end')):
            if event == 'start':
                if root is None:
                    root = element
                    if element.tag != 'tv':
                        raise GuideError(NOT_A_GUIDE)
                continue
            if element.tag in ('channel', 'programme'):
                yield element
                root.clear()
    except ET.ParseError as exc:
        raise GuideError(NOT_A_GUIDE) from exc
    except (OSError, EOFError, lzma.LZMAError) as exc:
        raise GuideError(NOT_A_GUIDE) from exc
    if root is None:
        raise GuideError(NOT_A_GUIDE)


@dataclass
class GuideSummary:
    """What a guide file holds, kept next to the cached copy."""

    channels: Dict[str, dict] = field(default_factory=dict)
    programmes: int = 0
    no_zone: int = 0

    def to_dict(self) -> dict:
        return {'channels': self.channels, 'programmes': self.programmes, 'no_zone': self.no_zone}

    @classmethod
    def from_dict(cls, data) -> 'GuideSummary':
        data = data if isinstance(data, dict) else {}
        channels = data.get('channels') if isinstance(data.get('channels'), dict) else {}
        return cls(channels, int(data.get('programmes') or 0), int(data.get('no_zone') or 0))

    def guide_channels(self, source: str) -> List[GuideChannel]:
        return [
            GuideChannel(source, channel_id, tuple(info.get('names') or ()),
                         int(info.get('programmes') or 0), int(info.get('last') or 0))
            for channel_id, info in self.channels.items()
        ]

    def ids(self) -> set:
        return {normalize_id(channel_id) for channel_id in self.channels}


def summarize(path: str, cancelled: Callable[[], bool] = lambda: False) -> GuideSummary:
    """Read a whole guide file: its channels, and how many programmes each has."""
    summary = GuideSummary()
    with open_guide(path) as handle:
        for element in _elements(handle):
            if cancelled():
                raise GuideError('Stopped.')
            channel_id = element.get('channel') if element.tag == 'programme' else element.get('id')
            if not channel_id:
                continue
            info = summary.channels.setdefault(channel_id, {'names': [], 'programmes': 0, 'last': 0})
            if element.tag == 'channel':
                for name in element.findall('display-name'):
                    text = (name.text or '').strip()
                    if text and text not in info['names']:
                        info['names'].append(text)
                continue
            stop, zone = parse_time(element.get('stop') or '')
            start, start_zone = parse_time(element.get('start') or '')
            if start is None:
                continue
            summary.programmes += 1
            info['programmes'] += 1
            if not start_zone:
                summary.no_zone += 1
            info['last'] = max(info['last'], stop or start)
    return summary


# --- The cache -----------------------------------------------------------------


class GuideCache:
    """Downloaded guides and their summaries, one pair per address."""

    def __init__(self, folder):
        self.folder = Path(folder)

    def _stem(self, location: str) -> Path:
        digest = hashlib.sha256(location.strip().encode('utf-8')).hexdigest()[:20]
        return self.folder / digest

    def file(self, location: str) -> str:
        """The copy in use. A local file is copied too, so a broken new version never replaces a good one."""
        return str(self._stem(location).with_suffix('.guide'))

    def summary(self, location: str) -> Optional[GuideSummary]:
        try:
            data = json.loads(self._stem(location).with_suffix('.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if not os.path.exists(self.file(location)):
            return None
        return GuideSummary.from_dict(data)

    def _save_summary(self, location: str, summary: GuideSummary) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._stem(location).with_suffix('.json')
        tmp = path.with_suffix('.json.part')
        tmp.write_text(json.dumps(summary.to_dict()), encoding='utf-8')
        os.replace(tmp, path)

    def forget(self, location: str) -> None:
        for suffix in ('.guide', '.json'):
            try:
                self._stem(location).with_suffix(suffix).unlink()
            except OSError:
                pass

    def refresh(
        self,
        location: str,
        progress: Callable[[int, int], None] = lambda _done, _total: None,
        cancelled: Callable[[], bool] = lambda: False,
        session: Optional[requests.Session] = None,
    ) -> GuideSummary:
        """Download or read the guide again and keep it if it looks right.

        Raises ``GuideError`` and keeps the last good copy otherwise.
        """
        previous = self.summary(location)
        self.folder.mkdir(parents=True, exist_ok=True)
        handle, part = tempfile.mkstemp(prefix='download-', suffix='.part', dir=str(self.folder))
        try:
            with os.fdopen(handle, 'wb') as out:
                if is_web_address(location):
                    _download(location, out, progress, cancelled, session)
                else:
                    _copy(location, out)
            summary = self._check(part, previous, cancelled)
            os.replace(part, self.file(location))
            self._save_summary(location, summary)
            return summary
        finally:
            if os.path.exists(part):
                os.unlink(part)

    @staticmethod
    def _check(path: str, previous: Optional[GuideSummary], cancelled) -> GuideSummary:
        summary = summarize(path, cancelled)
        if not summary.programmes:
            raise GuideError(NO_PROGRAMMES)
        if previous is not None and summary.programmes < previous.programmes * SHRINK_LIMIT:
            raise GuideError(SHRANK)
        return summary


def _copy(location, out) -> None:
    try:
        with open(os.path.expanduser(location), 'rb') as source:
            shutil.copyfileobj(source, out, 1024 * 1024)
    except OSError as exc:
        raise GuideError(FILE_FAILED) from exc


def _download(location, out, progress, cancelled, session=None) -> None:
    own = session is None
    session = session or requests.Session()
    try:
        configure_session(session, location)
        with session.get(location, timeout=TIMEOUT, stream=True) as response:
            if response.status_code >= 400:
                raise GuideError(DOWNLOAD_FAILED)
            try:
                total = int(response.headers.get('Content-Length') or 0)
            except ValueError:
                total = 0
            done = 0
            for chunk in response.iter_content(256 * 1024):
                if cancelled():
                    raise GuideError('Stopped.')
                done += len(chunk)
                if done > MAX_GUIDE_BYTES:
                    raise GuideError(TOO_LARGE)
                out.write(chunk)
                progress(done, total)
    except requests.RequestException as exc:
        raise GuideError(DOWNLOAD_FAILED) from exc
    except OSError as exc:
        raise GuideError(DOWNLOAD_FAILED) from exc
    finally:
        if own:
            session.close()


def build_index(cache: GuideCache, sources: Iterable[GuideSource]) -> GuideIndex:
    """The channels of every source that has a good copy, in the sources' order."""
    channels = []
    order = []
    for source in sources:
        summary = cache.summary(source.location)
        if summary is None:
            continue
        order.append(source.location)
        channels.extend(summary.guide_channels(source.location))
    return GuideIndex(channels, order)


# --- Writing the server's guide ------------------------------------------------


def guide_channel_id(channel_uuid: str) -> str:
    return f'{CHANNEL_PREFIX}{channel_uuid}'


@dataclass
class BuildResult:
    path: str
    # Programmes written per TV channel, and when its last one ends.
    programmes: Dict[str, int] = field(default_factory=dict)
    last_stop: Dict[str, int] = field(default_factory=dict)


def _shifted(value: str, shift: int) -> str:
    if not shift:
        return value
    stamp, zone = parse_time(value)
    if stamp is None:
        return value
    return format_time(stamp + shift * 60, zone)


def write_server_guide(
    cache: GuideCache,
    assignments: Dict[str, Assignment],
    names: Dict[str, str],
    folder,
    cancelled: Callable[[], bool] = lambda: False,
    now: Optional[float] = None,
) -> BuildResult:
    """Write the guide for the server: one guide channel per assigned TV channel.

    ``names`` gives each channel's name, shown in Tvheadend's EPG source list.
    Programmes that ended before ``now`` are left out.
    """
    now = int(time.time() if now is None else now)
    targets: Dict[str, Dict[str, List[Tuple[str, int]]]] = {}
    for uuid, assignment in assignments.items():
        guide = assignment.channel
        targets.setdefault(guide.source, {}).setdefault(guide.id, []).append((uuid, assignment.shift))
    Path(folder).mkdir(parents=True, exist_ok=True)
    handle, path = tempfile.mkstemp(prefix='server-', suffix='.xml', dir=str(folder))
    result = BuildResult(path)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            out.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="TVHplayer">\n')
            for uuid in sorted(assignments):
                name = escape(names.get(uuid) or uuid) + escape(GUIDE_SUFFIX)
                out.write(f'<channel id={quoteattr(guide_channel_id(uuid))}><display-name>{name}</display-name></channel>\n')
            for location, wanted in targets.items():
                try:
                    with open_guide(cache.file(location)) as source:
                        for element in _elements(source):
                            if cancelled():
                                raise GuideError('Stopped.')
                            if element.tag != 'programme':
                                continue
                            receivers = wanted.get(element.get('channel') or '')
                            if not receivers:
                                continue
                            _write_programme(out, element, receivers, now, result)
                except OSError as exc:
                    raise GuideError(FILE_FAILED) from exc
            out.write('</tv>\n')
    except BaseException:
        os.unlink(path)
        raise
    return result


def _write_programme(out, element, receivers, now, result) -> None:
    start = element.get('start') or ''
    stop = element.get('stop') or ''
    for uuid, shift in receivers:
        start_text = _shifted(start, shift)
        stop_text = _shifted(stop, shift) if stop else ''
        start_stamp, _zone = parse_time(start_text)
        if start_stamp is None:
            continue
        stop_stamp, _zone = parse_time(stop_text) if stop_text else (start_stamp, True)
        if (stop_stamp or start_stamp) <= now:
            continue
        element.set('start', start_text)
        if stop_text:
            element.set('stop', stop_text)
        element.set('channel', guide_channel_id(uuid))
        element.tail = '\n'
        out.write(ET.tostring(element, encoding='unicode'))
        result.programmes[uuid] = result.programmes.get(uuid, 0) + 1
        result.last_stop[uuid] = max(result.last_stop.get(uuid, 0), stop_stamp or start_stamp)
    element.set('start', start)
    if stop:
        element.set('stop', stop)


# --- Finding guides for the server's channels ---------------------------------

EPGSHARE_FOLDER = 'https://epgshare01.online/epgshare01/'
IPTV_EPG_FILE = 'https://iptv-epg.org/files/epg-{code}.xml.gz'
# Countries searched at most, the ones most channels are from.
MAX_COUNTRIES = 4
_EPGSHARE_FILE = re.compile(r'epg_ripper_([A-Za-z0-9_.-]+?)\.xml\.gz')


@dataclass
class Candidate:
    name: str
    location: str
    matched: int
    total: int
    recommended: bool = False


def epgshare_codes(country: str) -> Tuple[str, ...]:
    country = country.upper()
    return ('UK', 'GB') if country in ('UK', 'GB') else (country,)


def iptv_epg_code(country: str) -> str:
    return 'gb' if country == 'uk' else country


def countries_of(epg_ids: Iterable[str], limit: int = MAX_COUNTRIES) -> List[str]:
    counts: Dict[str, int] = {}
    for epg_id in epg_ids:
        country = id_country(epg_id)
        if country:
            counts[country] = counts.get(country, 0) + 1
    return [country for country, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))][:limit]


def epgshare_files(index_html: str, countries: Iterable[str]) -> List[str]:
    """epgshare01 files for these countries, such as ``UK1`` or ``US_LOCALS1``."""
    names = sorted(set(_EPGSHARE_FILE.findall(index_html or '')))
    wanted = []
    for country in countries:
        for code in epgshare_codes(country):
            pattern = re.compile(rf'{re.escape(code)}(?:_[A-Z]+)?\d*')
            wanted.extend(name for name in names if pattern.fullmatch(name) and name not in wanted)
    return wanted


def ids_in_list(text: str) -> set:
    """The guide IDs in one of epgshare01's ``.txt`` lists."""
    ids = set()
    for line in (text or '').splitlines():
        line = line.strip()
        if line and not line.startswith('--') and not line.isdigit():
            ids.add(normalize_id(line))
    return ids


def recommend(candidates: List[Candidate], total: int, covered: Dict[str, set]) -> None:
    """Tick the guides that together cover the most channels, each adding a fair share."""
    have: set = set()
    minimum = max(1, total // 50)
    for candidate in sorted(candidates, key=lambda c: -c.matched):
        new = covered.get(candidate.location, set()) - have
        if len(new) >= minimum:
            candidate.recommended = True
            have |= new


def find_guides(
    epg_ids: List[str],
    fetch_text: Callable[[str], str],
    fetch_summary: Callable[[str], GuideSummary],
    status: Callable[[str], None] = lambda _text: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Tuple[List[Candidate], List[str]]:
    """Free guides that hold the channels with these IDs, best first, and what failed.

    epgshare01 publishes a list of the IDs in each file, so only those lists
    are read. iptv-epg.org has one file per country, which ``fetch_summary``
    downloads; the copy is kept for when the guide is added.
    """
    wanted = {normalize_id(epg_id) for epg_id in epg_ids if normalize_id(epg_id)}
    total = len(wanted)
    countries = countries_of(epg_ids)
    candidates: List[Candidate] = []
    covered: Dict[str, set] = {}
    problems: List[str] = []
    if not countries:
        return candidates, problems

    status('Looking at epgshare01…')
    try:
        files = epgshare_files(fetch_text(EPGSHARE_FOLDER), countries)
    except Exception:
        files = []
        problems.append('epgshare01 could not be reached.')
    for name in files:
        if cancelled():
            return candidates, problems
        status(f'Looking at epgshare01 {name}…')
        try:
            ids = ids_in_list(fetch_text(f'{EPGSHARE_FOLDER}epg_ripper_{name}.txt'))
        except Exception:
            problems.append(f'epgshare01 {name} could not be read.')
            continue
        hits = wanted & ids
        if hits:
            location = f'{EPGSHARE_FOLDER}epg_ripper_{name}.xml.gz'
            candidates.append(Candidate(f'epgshare01 {name}', location, len(hits), total))
            covered[location] = hits

    for country in countries:
        if cancelled():
            return candidates, problems
        code = iptv_epg_code(country)
        location = IPTV_EPG_FILE.format(code=code)
        status(f'Downloading iptv-epg.org {code.upper()}…')
        try:
            ids = fetch_summary(location).ids()
        except GuideError as exc:
            if str(exc) != DOWNLOAD_FAILED:
                problems.append(f'iptv-epg.org {code.upper()}: {exc}')
            continue
        except Exception:
            problems.append(f'iptv-epg.org {code.upper()} could not be read.')
            continue
        hits = wanted & ids
        if hits:
            candidates.append(Candidate(f'iptv-epg.org {code.upper()}', location, len(hits), total))
            covered[location] = hits

    candidates.sort(key=lambda c: (-c.matched, c.name))
    recommend(candidates, total, covered)
    return candidates, problems

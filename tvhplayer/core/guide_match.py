"""Match the server's channels to channels in programme guides. No Qt imports.

A channel whose guide ID (a playlist's ``tvg-id``) equals a guide channel's
ID gets that guide on its own. Matching by name only makes suggestions,
because names like "FOX" or "BBC One" exist in many regions. The user
confirms a suggestion before it is used. Name clean-up and the "+1" handling
follow Headendarr's matcher (Apache 2.0, Josh Sunnex).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Words that say how a channel is sent, not which channel it is.
_QUALITY_WORDS = {
    'hd', 'fhd', 'uhd', 'sd', 'hq', 'lq', '4k', '8k', 'hevc', 'h264', 'h265',
    '2160p', '1080p', '1080i', '720p', '576p', '576i', '540p', '480p', '360p',
    'backup', 'raw',
}
# iptv-org feeds that differ only in picture quality.
_QUALITY_FEEDS = {'', 'sd', 'hd', 'fhd', 'uhd', '4k'}
# "UK: BBC One", "UK| BBC One", "|UK| BBC One", "[UK] BBC One", "(UK) BBC One".
_REGION_PREFIX = re.compile(r'^\s*(?:[\[(|]\s*[^\])|]{1,6}\s*[\])|]|[A-Z]{2,4}\s*[:|])\s*')
_PLUS_ONE = re.compile(r'(?:\+\s*1|\bplus\s*1)\s*$')
_WORDS = re.compile(r'[^\W_]+')
_COUNTRY = re.compile(r'\.([a-z]{2})$')

SCORE_ID = 1.0
SCORE_NAME = 0.94
SCORE_NAME_OTHER_FEED = 0.9
FUZZY_CUTOFF = 0.85
FUZZY_CAP = 0.88
COUNTRY_BONUS = 0.03
MAX_SUGGESTIONS = 5
# A "+1" channel shows the same programmes an hour later.
PLUS_ONE_SHIFT = 60


def normalize_id(value: str) -> str:
    """Compare guide IDs without case and without an iptv-org quality feed (``@HD``).

    Other feeds stay: ``HBO.us@West`` or ``Fox.us@WFTXTV`` run another
    schedule than the guide's ``HBO.us`` or ``Fox.us``.
    """
    value = (value or '').strip().casefold()
    base, _sep, feed = value.partition('@')
    return base.strip() if feed.strip() in _QUALITY_FEEDS else value


def id_country(value: str) -> str:
    """The two-letter country ending of an ID like ``BBCOne.uk``, or ''."""
    match = _COUNTRY.search((value or '').strip().casefold().partition('@')[0].strip())
    return match.group(1) if match else ''


def clean_name(name: str) -> Tuple[str, bool]:
    """``(words, plus_one)``: the name without region prefix, quality words and punctuation."""
    text = name or ''
    for _ in range(2):
        stripped = _REGION_PREFIX.sub('', text, count=1)
        if stripped == text or not stripped.strip():
            break
        text = stripped
    text = text.casefold().replace('&', ' and ')
    plus_one = bool(_PLUS_ONE.search(text))
    if plus_one:
        text = _PLUS_ONE.sub('', text)
    # "Bloomberg TV+" is another channel than "Bloomberg TV".
    text = text.replace('+', ' plus ')
    words = [word for word in _WORDS.findall(text) if word not in _QUALITY_WORDS]
    return ' '.join(words), plus_one


@dataclass(frozen=True)
class GuideChannel:
    """One ``<channel>`` of a guide file."""

    source: str
    id: str
    names: Tuple[str, ...] = ()
    programmes: int = 0
    last_stop: int = 0

    @property
    def name(self) -> str:
        return self.names[0] if self.names else self.id


@dataclass
class ServerChannel:
    uuid: str
    name: str
    number: str = ''
    # The guide IDs of the channel's services (an IPTV mux's EPG ID).
    epg_ids: Tuple[str, ...] = ()
    enabled: bool = True
    # Our guide channels and others the channel takes programmes from.
    epggrab: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Suggestion:
    channel: GuideChannel
    score: float
    shift: int = 0
    reason: str = ''
    # The same name, and no sign of another country: safe to tick for the user.
    sure: bool = False


@dataclass(frozen=True)
class Assignment:
    """Where a channel's programmes come from."""

    channel: GuideChannel
    shift: int = 0
    # 'id' when the IDs are equal, 'chosen' when the user picked it.
    how: str = 'id'


@dataclass
class Choice:
    """The user's decision for one channel, saved in tvhplayer.conf.

    An empty ``id`` means the channel gets no guide, even when one has its ID.
    """

    source: str = ''
    id: str = ''
    shift: int = 0

    @classmethod
    def from_dict(cls, data) -> Optional['Choice']:
        if not isinstance(data, dict):
            return None
        try:
            shift = int(data.get('shift') or 0)
        except (TypeError, ValueError):
            shift = 0
        return cls(str(data.get('source') or ''), str(data.get('id') or ''), shift)

    def to_dict(self) -> dict:
        return {'source': self.source, 'id': self.id, 'shift': self.shift}


@dataclass
class GuideIndex:
    """Every channel of the guides in use, looked up by ID and by name."""

    channels: List[GuideChannel] = field(default_factory=list)
    # Sources in the user's order: an ID found in two guides comes from the first.
    order: List[str] = field(default_factory=list)

    def __post_init__(self):
        rank = {source: index for index, source in enumerate(self.order)}
        self._by_id: Dict[str, List[GuideChannel]] = {}
        self._by_key: Dict[Tuple[str, str], GuideChannel] = {}
        self._by_name: Dict[str, List[Tuple[GuideChannel, bool]]] = {}
        self._by_word: Dict[str, set] = {}
        for channel in self.channels:
            self._by_key[(channel.source, channel.id)] = channel
            key = normalize_id(channel.id)
            if key:
                self._by_id.setdefault(key, []).append(channel)
            for name in set(channel.names) or {channel.id}:
                words, plus_one = clean_name(name)
                if not words:
                    continue
                entries = self._by_name.setdefault(words, [])
                if (channel, plus_one) not in entries:
                    entries.append((channel, plus_one))
                for key in _word_keys(words):
                    self._by_word.setdefault(key, set()).add(words)
        for matches in self._by_id.values():
            matches.sort(key=lambda ch: (rank.get(ch.source, len(rank)), -ch.programmes))

    def find(self, source: str, channel_id: str) -> Optional[GuideChannel]:
        return self._by_key.get((source, channel_id))

    def by_id(self, epg_id: str) -> Optional[GuideChannel]:
        matches = self._by_id.get(normalize_id(epg_id))
        return matches[0] if matches else None

    def search(self, text: str, limit: int = 50) -> List[GuideChannel]:
        """Guide channels whose ID or name contains ``text``, for picking one by hand."""
        needle = (text or '').casefold().strip()
        if not needle:
            return []
        found = []
        for channel in self.channels:
            if needle in channel.id.casefold() or any(needle in name.casefold() for name in channel.names):
                found.append(channel)
                if len(found) >= limit:
                    break
        return found

    def suggest(self, channel: ServerChannel, region: str = '') -> List[Suggestion]:
        """Guide channels with a name like this channel's, best first."""
        words, plus_one = clean_name(channel.name)
        if not words:
            return []
        countries = {id_country(epg_id) for epg_id in channel.epg_ids} - {''}
        if region and not countries:
            countries.add(region)
        best: Dict[Tuple[str, str], Suggestion] = {}

        def offer(guide: GuideChannel, guide_plus_one: bool, score: float, reason: str):
            shift = 0
            if plus_one != guide_plus_one:
                if not plus_one:
                    return  # A "+1" guide never fits the channel itself.
                score -= SCORE_NAME - SCORE_NAME_OTHER_FEED
                shift = PLUS_ONE_SHIFT
            country = id_country(guide.id)
            foreign = bool(country and countries and country not in countries)
            if country and countries:
                score += -COUNTRY_BONUS if foreign else COUNTRY_BONUS
            key = (guide.source, guide.id)
            if key not in best or best[key].score < score:
                best[key] = Suggestion(guide, round(score, 4), shift, reason, reason == 'name' and not foreign)

        for guide, guide_plus_one in self._by_name.get(words, ()):
            offer(guide, guide_plus_one, SCORE_NAME, 'name')
        candidates = set()
        for key in _word_keys(words):
            candidates |= self._by_word.get(key, set())
        candidates.discard(words)
        matcher = SequenceMatcher(None, '', words)
        for other in candidates:
            matcher.set_seq1(other)
            if matcher.real_quick_ratio() < FUZZY_CUTOFF or matcher.quick_ratio() < FUZZY_CUTOFF:
                continue
            ratio = matcher.ratio()
            if ratio < FUZZY_CUTOFF:
                continue
            for guide, guide_plus_one in self._by_name[other]:
                offer(guide, guide_plus_one, min(ratio, FUZZY_CAP), 'similar name')
        ranked = sorted(best.values(), key=lambda s: (-s.score, s.channel.name.casefold(), s.channel.id))
        return ranked[:MAX_SUGGESTIONS]


def _word_keys(words: str) -> set:
    """Keys of names worth comparing: a shared word, or a word's first four letters."""
    keys = set()
    for word in words.split():
        if len(word) > 1:
            keys.add(word)
        if len(word) >= 4:
            keys.add('^' + word[:4])
    return keys


def main_region(channels: Iterable[ServerChannel]) -> str:
    """The country most of the channels' guide IDs end in, to break ties between names."""
    counts = Counter(id_country(epg_id) for channel in channels for epg_id in channel.epg_ids)
    counts.pop('', None)
    return counts.most_common(1)[0][0] if counts else ''


def assign(
    channels: Sequence[ServerChannel],
    index: GuideIndex,
    choices: Dict[str, Choice],
) -> Dict[str, Assignment]:
    """Each channel's guide: the user's choice, else the guide channel with its ID."""
    result = {}
    for channel in channels:
        choice = choices.get(channel.uuid)
        if choice is not None:
            if not choice.id:
                continue
            guide = index.find(choice.source, choice.id)
            if guide is not None:
                result[channel.uuid] = Assignment(guide, choice.shift, 'chosen')
                continue
            # The chosen guide was removed: fall back to the channel's ID.
        for epg_id in channel.epg_ids:
            guide = index.by_id(epg_id)
            if guide is not None:
                result[channel.uuid] = Assignment(guide)
                break
    return result

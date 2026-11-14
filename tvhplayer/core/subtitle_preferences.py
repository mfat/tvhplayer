"""Per-server subtitle language selection, independent of Qt and libmpv."""

from __future__ import annotations

import re
import unicodedata

# Stable ISO-639-2 identifiers; include names and common 2/3-letter TV labels.
SUBTITLE_LANGUAGES = (
    ('ron', 'Romanian', ('romanian', 'romana', 'rum', 'ron', 'ro')),
    ('eng', 'English', ('english', 'eng', 'en')),
    ('hun', 'Hungarian', ('hungarian', 'magyar', 'hun', 'hu')),
    ('fra', 'French', ('french', 'francais', 'fra', 'fre', 'fr')),
    ('deu', 'German', ('german', 'deutsch', 'deu', 'ger', 'de')),
    ('ita', 'Italian', ('italian', 'italiano', 'ita', 'it')),
    ('spa', 'Spanish', ('spanish', 'espanol', 'spa', 'es')),
    ('pol', 'Polish', ('polish', 'polski', 'pol', 'pl')),
    ('por', 'Portuguese', ('portuguese', 'portugues', 'por', 'pt')),
    ('tur', 'Turkish', ('turkish', 'turkce', 'tur', 'tr')),
    ('rus', 'Russian', ('russian', 'russkiy', 'rus', 'ru')),
    ('ukr', 'Ukrainian', ('ukrainian', 'ukr', 'uk')),
    ('bul', 'Bulgarian', ('bulgarian', 'bul', 'bg')),
    ('srp', 'Serbian', ('serbian', 'srpski', 'srp', 'sr')),
    ('hrv', 'Croatian', ('croatian', 'hrv', 'hr')),
    ('ces', 'Czech', ('czech', 'ces', 'cze', 'cs')),
    ('slk', 'Slovak', ('slovak', 'slk', 'slo', 'sk')),
    ('ell', 'Greek', ('greek', 'ell', 'gre', 'el')),
    ('nld', 'Dutch', ('dutch', 'nederlands', 'nld', 'dut', 'nl')),
    ('ara', 'Arabic', ('arabic', 'ara', 'ar')),
    ('heb', 'Hebrew', ('hebrew', 'heb', 'he')),
)


def _tokens(value):
    text = unicodedata.normalize('NFKD', str(value or '').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.findall(r'[a-z0-9]+', text)


def normalize_subtitle_language(value):
    """Return a known ISO-639-2 language or '' for manual/off selection."""
    tokens = _tokens(value)
    if len(tokens) != 1:
        return ''
    term = tokens[0]
    for code, _title, aliases in SUBTITLE_LANGUAGES:
        if term == code or term in aliases:
            return code
    return ''


def subtitle_track_language(label):
    """Identify one supported language from an MPV subtitle-track description.

    Unlike a configured language, a track label can contain text such as
    'DVB Subtitles (rum)'. Ambiguous and unlabelled tracks are not remembered.
    """
    tokens = set(_tokens(label))
    matches = {
        code for code, _title, aliases in SUBTITLE_LANGUAGES
        if tokens.intersection(set(aliases) | {code})
    }
    return next(iter(matches)) if len(matches) == 1 else None


def preferred_subtitle_track(tracks, language):
    """Match an actual MPV track by language token; do not guess a track ID.

    MPV can expose 'Romanian', 'DVB Subtitle [rum]', 'Subtitle (ron)' etc.
    Match only whole tokens to avoid 'ro' matching 'program' or 'fr' 'frames'.
    """
    language = normalize_subtitle_language(language)
    if not language:
        return None
    entry = next((item for item in SUBTITLE_LANGUAGES if item[0] == language), None)
    if entry is None:
        return None
    aliases = set(entry[2])
    aliases.add(language)
    for track_id, title in tracks or []:
        if aliases.intersection(_tokens(title)):
            return int(track_id)
    return None

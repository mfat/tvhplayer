"""Server subtitle preferences, independent of the Qt and MPV runtimes."""

from tvhplayer.core.models import ServerConfig
from tvhplayer.core.subtitle_preferences import (
    normalize_subtitle_language,
    preferred_subtitle_track,
    subtitle_track_language,
)


def test_server_subtitle_language_is_normalized_and_persisted():
    server = ServerConfig.from_dict({
        "name": "TVH", "url": "http://tvh:9981",
        "subtitle_language": "Romanian",
        "remember_subtitle_selection": True,
    })
    assert server.subtitle_language == "ron"
    assert server.remember_subtitle_selection is True
    restored = ServerConfig.from_dict(server.to_dict())
    assert restored.subtitle_language == "ron"
    assert restored.remember_subtitle_selection is True


def test_missing_or_invalid_preferences_fail_closed():
    default = ServerConfig.from_dict({"name": "TVH", "url": "http://tvh:9981"})
    assert default.subtitle_language == ""
    assert not default.remember_subtitle_selection
    invalid = ServerConfig.from_dict({
        "name": "TVH", "url": "http://tvh:9981",
        "subtitle_language": "English Romanian",
        "remember_subtitle_selection": "true",
    })
    assert invalid.subtitle_language == ""
    assert not invalid.remember_subtitle_selection


def test_mpv_dvb_track_language_aliases_and_no_guessing():
    assert normalize_subtitle_language("rum") == "ron"
    assert normalize_subtitle_language("Romanian") == "ron"
    assert normalize_subtitle_language("fr") == "fra"
    assert subtitle_track_language("DVB Subtitles - rum") == "ron"
    assert subtitle_track_language("English - eng") == "eng"
    assert subtitle_track_language("Subtitle 2") is None
    assert preferred_subtitle_track([
        (5, "DVB Subtitles - eng"),
        (7, "DVB Subtitles - rum"),
    ], "Romanian") == 7
    assert preferred_subtitle_track([(1, "English")], "ron") is None
    assert preferred_subtitle_track([(1, "DVB Subtitles")], "ron") is None

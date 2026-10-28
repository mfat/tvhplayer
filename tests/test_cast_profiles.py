from tvhplayer.core.cast_profiles import choose_cast_profile, profile_media_type, profile_score
from tvhplayer.core.models import StreamProfile


def profile(name, **raw):
    return StreamProfile(uuid=name, name=name, raw=raw)


def test_automatic_choice_accounts_for_audio_and_container():
    profiles = [profile(name) for name in (
        'webtv-h264-vorbis-mp4', 'webtv-h264-aac-matroska',
        'webtv-vp8-vorbis-webm', 'webtv-h264-aac-mpegts', 'htsp',
    )]
    assert choose_cast_profile(profiles).name == 'webtv-h264-aac-mpegts'
    assert profile_score(profiles[0]) < 0


def test_structured_codec_fields_override_misleading_names():
    safe = profile('My television', pro_vcodec='webtv-h264', pro_acodec='webtv-aac', container=2)
    unsafe = profile('h264-aac-mpegts', pro_vcodec='webtv-h264', pro_acodec='webtv-vorbis', container=13)
    assert choose_cast_profile([unsafe, safe]) is safe


def test_automatic_choice_does_not_select_unknown_or_disabled_transcoding():
    assert choose_cast_profile([profile('htsp'), profile('custom'), profile('h264-vorbis-mp4')]) is None
    assert choose_cast_profile([profile('h264-aac-mpegts', enabled=False), profile('pass')]).name == 'pass'


def test_webm_vorbis_is_valid_with_vp8_but_not_h264():
    assert choose_cast_profile([profile('h264-vorbis-webm'), profile('vp8-vorbis-webm')]).name == 'vp8-vorbis-webm'


def test_profile_supplies_a_container_hint_for_extensionless_ticket_urls():
    assert profile_media_type(profile('webtv-vp8-vorbis-webm')) == 'video/webm'
    assert profile_media_type(profile('webtv-h264-aac-mpegts')) == 'video/mp2t'
    assert profile_media_type(profile('Living room', container=13)) == 'video/mp4'

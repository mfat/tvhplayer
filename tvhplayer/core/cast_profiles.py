"""Conservative automatic choices from the server's advertised stream profiles."""

import re

AUTO_PROFILE = 'auto'


def _compact(text):
    return re.sub(r'[^a-z0-9]', '', text)


def profile_media_type(profile):
    raw = profile.raw or {}
    container = raw.get('container')
    known = {1: 'video/x-matroska', 2: 'video/mp2t', 6: 'video/webm', 13: 'video/mp4'}
    if container in known:
        return known[container]
    label = _compact(str(container or f'{profile.name} {profile.comment}').lower())
    for token, kind in (('mpegts', 'video/mp2t'), ('webm', 'video/webm'),
                        ('matroska', 'video/x-matroska'), ('mp4', 'video/mp4')):
        if token in label:
            return kind
    return None


def profile_score(profile):
    """Rank known codec/container combinations, never H.264 by itself.

    Older viewing accounts expose only names/comments. Codec fields, when
    present, take precedence over those labels. Unknown/pass-through profiles
    remain a fallback: their compatibility depends on the channel itself.
    """
    raw = profile.raw or {}
    if raw.get('enabled') is False:
        return -1
    label = f'{profile.name} {profile.comment}'.lower()
    video = str(raw.get('pro_vcodec') or raw.get('vcodec') or '').lower()
    audio = str(raw.get('pro_acodec') or raw.get('acodec') or '').lower()
    container = str(raw.get('container') or '').lower()
    video = video or label
    audio = audio or label
    container = {1: 'matroska', 2: 'mpegts', 6: 'webm', 13: 'mp4'}.get(raw.get('container'), container) or label
    video, audio, container = map(_compact, (video, audio, container))
    h264 = 'h264' in video or 'libx264' in video
    aac = 'aac' in audio
    vorbis = 'vorbis' in audio
    webm = 'webm' in container
    mpegts = 'mpegts' in container
    mp4 = 'mp4' in container
    matroska = 'matroska' in container or 'mkv' in container
    if ('htsp' == profile.name.lower() or 'disabled' in (video, audio)):
        return -1
    if h264 and (vorbis or webm):
        return -1
    if h264 and aac:
        if mpegts:
            return 100
        if mp4:
            return 90
        if matroska:
            return 50
        return 40
    if webm and ('vp8' in video or 'vp9' in video) and (vorbis or 'opus' in audio):
        return 70
    if any(codec in video for codec in ('h265', 'hevc', 'mpeg2')):
        return -1
    if profile.name.lower() in ('pass', 'mpegts', 'default'):
        return 10
    return 0


def choose_cast_profile(profiles):
    """Return the best described compatible profile, or the server default."""
    return next(iter(ranked_cast_profiles(profiles)), None)


def ranked_cast_profiles(profiles):
    candidates = sorted(profiles, key=lambda item: (-profile_score(item), item.name.casefold(), item.uuid))
    return [item for item in candidates if profile_score(item) > 0]

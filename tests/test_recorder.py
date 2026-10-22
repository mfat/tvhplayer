from tvhplayer.core.recorder import build_ffmpeg_command, redact_command


def test_ts_command_copies_streams():
    cmd = build_ffmpeg_command('http://127.0.0.1:9981/stream/channel/abc', '/tmp/a.ts')
    assert cmd[0] == 'ffmpeg'
    assert '-i' in cmd
    assert cmd[cmd.index('-i') + 1].endswith('/stream/channel/abc')
    assert '-f' in cmd and 'mpegts' in cmd
    assert cmd[-1] == '/tmp/a.ts'
    assert '-headers' not in cmd


def test_mp4_command_transcodes_audio():
    cmd = build_ffmpeg_command('http://host/stream', '/tmp/show.mp4')
    assert 'aac' in cmd
    assert 'mp4' in cmd


def test_auth_header_only_when_url_has_no_userinfo():
    with_header = build_ffmpeg_command(
        'http://127.0.0.1:9981/stream/channel/x', '/tmp/a.ts', 'user', 'secret'
    )
    assert '-headers' in with_header
    already_embedded = build_ffmpeg_command(
        'http://user:secret@127.0.0.1:9981/stream/channel/x', '/tmp/a.ts', 'user', 'secret'
    )
    assert '-headers' not in already_embedded


def test_redact_hides_basic_auth():
    cmd = build_ffmpeg_command(
        'http://user:secret@127.0.0.1:9981/stream/channel/x', '/tmp/a.ts'
    )
    text = redact_command(cmd)
    assert 'secret' not in text
    assert 'user:secret@' not in text

import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction

import pytest

from tvhplayer.core import convert
from tvhplayer.core.builtin_server import quit_confirmation


def test_frame_rate_options_give_a_keyframe_every_second():
    assert convert.frame_rate_options(Fraction(50)) == [
        '-fps_mode', 'cfr', '-r', '50', '-g', '50', '-keyint_min', '50',
    ]
    assert convert.frame_rate_options(Fraction(30000, 1001), fps_mode=False) == [
        '-vsync', 'cfr', '-r', '30000/1001', '-g', '30', '-keyint_min', '30',
    ]
    assert convert.frame_rate_options(None) == []
    assert convert.parse_rate('0/0') is None
    assert convert.parse_rate('25/1') == 25


def test_command_puts_the_users_options_last(tmp_path):
    cmd = convert.build_convert_command('/r/a.ts', '/r/a_edit.mp4', ['-crf', '20'], Fraction(25))
    assert cmd[cmd.index('-i') + 1] == '/r/a.ts'
    assert '-sn' in cmd and cmd.index('-r') < cmd.index('-crf')
    assert cmd[-3:] == ['-crf', '20', '/r/a_edit.mp4']


def test_edit_path_never_overwrites(tmp_path):
    source = tmp_path / 'show.ts'
    assert convert.edit_path(source) == str(tmp_path / 'show_edit.mp4')
    (tmp_path / 'show_edit.mp4').write_bytes(b'')
    assert convert.edit_path(source) == str(tmp_path / 'show_edit_2.mp4')
    assert convert.edit_path(source, '/out') == '/out/show_edit.mp4'
    assert convert.edit_path(source, '/out', {'/out/show_edit.mp4'}) == '/out/show_edit_2.mp4'


def test_requested_encoder():
    assert convert.requested_encoder(['-c:v', 'libx264', '-crf', '18']) == 'libx264'
    assert convert.requested_encoder(['-vcodec', 'h264_vaapi']) == 'h264_vaapi'
    assert convert.requested_encoder(['-crf', '18']) is None


def test_missing_encoder_is_named(monkeypatch):
    monkeypatch.setitem(convert._encoders, 'fake-ffmpeg', {'libx264', 'aac'})
    assert convert.missing_encoder('-c:v libx264', 'fake-ffmpeg') is None
    assert convert.missing_encoder('-c:v libx265', 'fake-ffmpeg') == 'This ffmpeg has no libx265 encoder.'
    monkeypatch.setitem(convert._encoders, 'gone', set())
    assert convert.missing_encoder('-c:v libx264', 'gone') == 'ffmpeg was not found.'
    with pytest.raises(ValueError):
        convert.missing_encoder('-metadata "title=open', 'fake-ffmpeg')


def _script(path, body):
    path.write_text(f'#!{sys.executable}\n{body}')
    path.chmod(0o755)
    return str(path)


def test_older_ffmpeg_is_asked_again_with_vsync(tmp_path):
    ffprobe = _script(tmp_path / 'ffprobe', 'print(%r)' % json.dumps(
        {'streams': [{'avg_frame_rate': '25/1'}], 'format': {'duration': '10.0'}}
    ))
    calls = tmp_path / 'calls'
    ffmpeg = _script(tmp_path / 'ffmpeg', f'''
import sys
open({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')
if '-fps_mode' in sys.argv:
    sys.stderr.write("Unrecognized option 'fps_mode'.\\n")
    sys.exit(8)
print('out_time_us=5000000', flush=True)
open(sys.argv[-1], 'wb').write(b'video')
''')
    source = tmp_path / 'rec.ts'
    source.write_bytes(b'ts')
    job = convert.Conversion(source, tmp_path / 'rec_edit.mp4', ['-crf', '18'], delete_original=True,
                             ffmpeg=ffmpeg, ffprobe=ffprobe)
    job.run()
    assert job.status == convert.DONE, job.error
    lines = calls.read_text().splitlines()
    assert '-fps_mode cfr' in lines[0] and '-vsync cfr -r 25 -g 25' in lines[1]
    assert (tmp_path / 'rec_edit.mp4').read_bytes() == b'video'
    assert not source.exists()


def test_failed_conversion_keeps_the_original_and_says_why(tmp_path):
    ffmpeg = _script(tmp_path / 'ffmpeg', '''
import sys
open(sys.argv[-1], 'wb').write(b'partial')
sys.stderr.write("Unknown encoder 'libx264'\\n")
sys.exit(1)
''')
    source = tmp_path / 'rec.ts'
    source.write_bytes(b'ts')
    job = convert.Conversion(source, tmp_path / 'rec_edit.mp4', [], delete_original=True,
                             ffmpeg=ffmpeg, ffprobe=str(tmp_path / 'missing-ffprobe'))
    job.run()
    assert job.status == convert.FAILED
    assert job.error == "Unknown encoder 'libx264'"
    assert source.exists() and not (tmp_path / 'rec_edit.mp4').exists()


def test_cancelled_before_it_starts(tmp_path):
    job = convert.Conversion(tmp_path / 'a.ts', tmp_path / 'a_edit.mp4', [], ffmpeg='/nonexistent')
    job.cancel()
    assert job.status == convert.CANCELLED and not job.is_active
    job.start()
    assert job.status == convert.CANCELLED


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='needs ffmpeg')
def test_real_conversion_has_a_keyframe_every_second(tmp_path):
    source = tmp_path / 'rec.ts'
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=3:size=160x120:rate=25',
        '-c:v', 'mpeg2video', '-f', 'mpegts', str(source),
    ], check=True)
    options = '-c:v libx264 -preset ultrafast -crf 30 -c:a copy -movflags +faststart'
    if convert.missing_encoder(options):
        pytest.skip('ffmpeg has no libx264')
    job = convert.Conversion(source, convert.edit_path(source), convert.parse_ffmpeg_options(options))
    job.run()
    assert job.status == convert.DONE, job.error
    keyframes = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-skip_frame', 'nokey',
        '-show_entries', 'frame=pts_time', '-of', 'csv=p=0', job.target,
    ], capture_output=True, text=True, check=True).stdout.split()
    assert [round(float(t.strip(','))) for t in keyframes] == [0, 1, 2]


def test_quit_asks_while_converting():
    message = quit_confirmation([], False, conversions=['rec.ts'])
    assert 'Converting for editing: rec.ts' in message
    assert 'original recording is kept' in message
    assert quit_confirmation([], False, conversions=[]) is None

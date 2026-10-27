import types

from tvhplayer.core import convert, processes
from tvhplayer.core.recorder import LocalRecorder

CREATE_NO_WINDOW = 0x08000000


def test_windows_starts_helpers_without_a_console_window():
    assert processes.no_window_flags('win32') == CREATE_NO_WINDOW
    assert processes.no_window_flags('linux') == 0
    assert processes.no_window_flags('darwin') == 0


def test_local_recording_opens_no_console_window_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr('tvhplayer.core.recorder.no_window_flags', lambda: CREATE_NO_WINDOW)
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(stderr=types.SimpleNamespace(read=lambda n: b'', close=lambda: None),
                                     poll=lambda: 0)

    monkeypatch.setattr('tvhplayer.core.recorder.subprocess.Popen', fake_popen)
    LocalRecorder().start('http://192.0.2.1/stream/channel/1', tmp_path / 'a.ts')
    assert seen['creationflags'] == CREATE_NO_WINDOW


def test_converting_opens_no_console_window_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr('tvhplayer.core.convert.no_window_flags', lambda: CREATE_NO_WINDOW)
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(kwargs.get('creationflags'))
        return types.SimpleNamespace(returncode=1, stdout='', stderr='')

    monkeypatch.setattr('tvhplayer.core.convert.subprocess.run', fake_run)
    # available_encoders asks ffmpeg once per process.
    monkeypatch.setattr(convert, '_encoders', {})
    convert.probe(tmp_path / 'a.ts')
    convert.available_encoders()
    assert seen == [CREATE_NO_WINDOW, CREATE_NO_WINDOW]

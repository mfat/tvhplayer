import ctypes.util
import sys

import pytest

from tvhplayer.core import frozen_libs


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(ctypes.util, 'find_library', lambda name: f'system:{name}')
    return tmp_path


@pytest.mark.parametrize('platform, name', [('win32', 'libmpv-2.dll'), ('darwin', 'libmpv.2.dylib')])
def test_a_packaged_build_loads_its_own_libmpv(frozen, monkeypatch, platform, name):
    monkeypatch.setattr(sys, 'platform', platform)
    (frozen / name).write_bytes(b'')
    frozen_libs.prepare()
    # python-mpv asks for 'mpv' on macOS and for the DLL names on Windows.
    for asked in ('mpv', 'libmpv-2.dll', 'mpv-2.dll'):
        assert ctypes.util.find_library(asked) == str(frozen / name)
    assert ctypes.util.find_library('vlc') == 'system:vlc'


def test_without_a_bundled_libmpv_the_system_is_asked(frozen, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    frozen_libs.prepare()
    assert ctypes.util.find_library('mpv') == 'system:mpv'


def test_a_source_run_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(ctypes.util, 'find_library', lambda name: f'system:{name}')
    frozen_libs.prepare()
    assert ctypes.util.find_library('mpv') == 'system:mpv'

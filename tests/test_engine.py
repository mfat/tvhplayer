from tvhplayer.core.engine import ENGINE_MPV, ENGINE_VLC, choose_engine

WAYLAND = {'WAYLAND_DISPLAY': 'wayland-0'}


def _choose(environ, platform='linux', missing=''):
    return choose_engine(environ, platform, lambda: missing)[0]


def test_wayland_session_with_libmpv_uses_mpv():
    assert _choose(WAYLAND) == ENGINE_MPV


def test_x11_session_uses_vlc():
    assert _choose({'DISPLAY': ':0'}) == ENGINE_VLC


def test_a_platform_the_user_chose_keeps_vlc():
    assert _choose({**WAYLAND, 'QT_QPA_PLATFORM': 'xcb'}) == ENGINE_VLC


def test_missing_libmpv_falls_back_to_vlc_and_says_why():
    engine, reason = choose_engine(WAYLAND, 'linux', lambda: 'Cannot find libmpv')
    assert engine == ENGINE_VLC
    assert 'Cannot find libmpv' in reason


def test_windows_and_macos_keep_vlc():
    assert _choose(WAYLAND, 'win32') == ENGINE_VLC
    assert _choose(WAYLAND, 'darwin') == ENGINE_VLC


def test_the_environment_variable_overrides_the_choice():
    assert _choose({**WAYLAND, 'TVHPLAYER_ENGINE': 'vlc'}) == ENGINE_VLC
    assert _choose({'DISPLAY': ':0', 'TVHPLAYER_ENGINE': 'mpv'}) == ENGINE_MPV
    assert _choose({'TVHPLAYER_ENGINE': 'mpv'}, missing='no libmpv') == ENGINE_VLC

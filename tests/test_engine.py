from tvhplayer.core.engine import ENGINE_MPV, ENGINE_VLC, choose_engine, qt_platform_for

WAYLAND = {'WAYLAND_DISPLAY': 'wayland-0'}
X11 = {'DISPLAY': ':0'}


def _choose(environ, platform='linux', missing='', preference='auto'):
    return choose_engine(environ, platform, lambda: missing, preference)[0]


def test_wayland_session_uses_mpv():
    assert _choose(WAYLAND) == ENGINE_MPV
    assert _choose({**WAYLAND, 'QT_QPA_PLATFORM': 'wayland'}) == ENGINE_MPV
    assert _choose({**WAYLAND, 'QT_QPA_PLATFORM': 'wayland;xcb'}) == ENGINE_MPV


def test_x11_session_uses_vlc():
    assert _choose(X11) == ENGINE_VLC
    assert _choose({**WAYLAND, 'QT_QPA_PLATFORM': 'xcb'}) == ENGINE_VLC


def test_missing_libmpv_falls_back_to_vlc_and_says_why():
    engine, reason = choose_engine(WAYLAND, 'linux', lambda: 'Cannot find libmpv')
    assert engine == ENGINE_VLC
    assert 'Cannot find libmpv' in reason


def test_windows_and_macos_keep_vlc():
    assert _choose(WAYLAND, 'win32', preference='mpv') == ENGINE_VLC
    assert _choose(WAYLAND, 'darwin') == ENGINE_VLC


def test_the_setting_picks_one_engine_everywhere():
    assert _choose(WAYLAND, preference='vlc') == ENGINE_VLC
    assert _choose(X11, preference='mpv') == ENGINE_MPV
    assert _choose(X11, preference='mpv', missing='no libmpv') == ENGINE_VLC


def test_the_environment_variable_overrides_the_setting():
    assert _choose({**WAYLAND, 'TVHPLAYER_ENGINE': 'vlc'}, preference='mpv') == ENGINE_VLC
    assert _choose({**X11, 'TVHPLAYER_ENGINE': 'mpv'}, preference='vlc') == ENGINE_MPV


def test_vlc_gets_x11_even_where_qt_would_pick_wayland():
    assert qt_platform_for(ENGINE_VLC, WAYLAND, 'linux') == 'xcb'
    assert qt_platform_for(ENGINE_VLC, {**WAYLAND, 'QT_QPA_PLATFORM': 'wayland'}, 'linux') == 'xcb'
    assert qt_platform_for(ENGINE_VLC, {'QT_QPA_PLATFORM': 'offscreen'}, 'linux') is None
    assert qt_platform_for(ENGINE_VLC, WAYLAND, 'win32') is None


def test_mpv_leaves_the_platform_to_qt():
    assert qt_platform_for(ENGINE_MPV, WAYLAND, 'linux') is None


def test_startup_platform_is_the_one_the_engine_will_get():
    from tvhplayer.core.engine import startup_platform
    assert startup_platform(ENGINE_VLC, WAYLAND, 'linux') == 'xcb'
    assert startup_platform(ENGINE_MPV, WAYLAND, 'linux') == 'wayland'
    assert startup_platform(ENGINE_MPV, {}, 'linux') == 'xcb'
    assert startup_platform(ENGINE_MPV, {**WAYLAND, 'QT_QPA_PLATFORM': 'xcb'}, 'linux') == 'xcb'
    assert startup_platform(ENGINE_VLC, {}, 'darwin') is None
    # Platform arguments are not part of the name.
    assert startup_platform(ENGINE_MPV, {'QT_QPA_PLATFORM': 'xcb:display=:1'}, 'linux') == 'xcb'
    assert startup_platform(ENGINE_MPV, {'QT_QPA_PLATFORM': 'wayland:foo;xcb'}, 'linux') == 'wayland'

from types import SimpleNamespace

from tvhplayer.video_widget import MpvVideoWidget, live_splitter_keeps_up


def test_live_splitter_keeps_up_from_qt_6_11():
    assert not live_splitter_keeps_up('6.10.2')
    assert not live_splitter_keeps_up('6.10.0')
    assert live_splitter_keeps_up('6.11.0')
    assert live_splitter_keeps_up('6.11.2')
    assert live_splitter_keeps_up('6.12.0')
    assert live_splitter_keeps_up('7.0.0')

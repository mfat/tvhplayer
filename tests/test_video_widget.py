from types import SimpleNamespace

from tvhplayer.video_widget import MpvVideoWidget, live_splitter_keeps_up, use_live_resize


def test_live_splitter_keeps_up_from_qt_6_11():
    assert not live_splitter_keeps_up('6.10.2')
    assert not live_splitter_keeps_up('6.10.0')
    assert live_splitter_keeps_up('6.11.0')
    assert live_splitter_keeps_up('6.11.2')
    assert live_splitter_keeps_up('6.12.0')
    assert live_splitter_keeps_up('7.0.0')


def test_live_resize_follows_qt_until_chosen():
    assert not use_live_resize(None, '6.10.2')
    assert use_live_resize(None, '6.11.0')
    assert use_live_resize(True, '6.10.2')
    assert not use_live_resize(False, '6.11.0')


def test_release_keeps_native_callback_alive_until_render_context_is_freed():
    """The libmpv VO thread may still call the old ctypes closure on shutdown."""
    called = []

    class FakeContext:
        def __init__(self):
            self._callback = object()

        @property
        def update_cb(self):
            return self._callback

        @update_cb.setter
        def update_cb(self, new_value):
            raise AssertionError('Do not replace an active ctypes callback before free()')

        def free(self):
            assert self.update_cb is not None
            called.append('free')

    fake = SimpleNamespace(
        _render_context=FakeContext(),
        _wayland=None,
        makeCurrent=lambda: called.append('makeCurrent'),
        doneCurrent=lambda: called.append('doneCurrent'),
    )
    MpvVideoWidget.release(fake)
    assert called == ['makeCurrent', 'free', 'doneCurrent']
    assert fake._render_context is None

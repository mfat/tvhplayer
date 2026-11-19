from concurrent.futures import Future

import pytest
from PyQt6.QtCore import Qt

from tvhplayer.media_info import MediaInfoDialog


def test_media_info_waits_without_blocking_and_shows_a_plain_text_snapshot(qapp):
    request = Future()
    dialog = MediaInfoDialog(None, lambda: request, lambda: True, '<b>Channel & One</b>')
    try:
        assert dialog.note.textFormat() == Qt.TextFormat.PlainText
        assert dialog.note.text() == '<b>Channel & One</b>'
        dialog._poll()
        assert dialog.view.toPlainText() == 'Reading media information…'
        request.set_result('Resolution: 1920 × 1080\nVideo codec: h264\nAudio codec: aac')
        dialog._poll()
        assert '1920 × 1080' in dialog.view.toPlainText()
        assert 'h264' in dialog.view.toPlainText()
        assert 'aac' in dialog.view.toPlainText()
        assert not dialog._poll_timer.isActive()
        assert not dialog._deadline.isActive()
    finally:
        dialog.close()


@pytest.mark.parametrize('result', [None, '', '   '])
def test_media_info_handles_missing_properties(qapp, result):
    request = Future()
    request.set_result(result)
    dialog = MediaInfoDialog(None, lambda: request, lambda: True)
    dialog._poll()
    assert dialog.view.toPlainText() == 'Media information is not available yet.'
    dialog.close()


@pytest.mark.parametrize('submission_failure', [False, True])
def test_media_info_reports_engine_failure(qapp, submission_failure):
    def request():
        if submission_failure:
            raise RuntimeError('engine closed')
        future = Future()
        future.set_exception(RuntimeError('decoder unavailable'))
        return future

    dialog = MediaInfoDialog(None, request, lambda: True)
    dialog._poll()
    assert dialog.view.toPlainText() == 'Could not read media information.'
    assert not dialog._deadline.isActive()
    dialog.close()


@pytest.mark.parametrize('reason', ['close', 'timeout', 'stream-changed'])
def test_media_info_cancels_pending_requests(qapp, reason):
    request = Future()
    dialog = MediaInfoDialog(None, lambda: request, lambda: reason != 'stream-changed')
    if reason == 'close':
        dialog.reject()
    elif reason == 'timeout':
        dialog._deadline.timeout.emit()
        assert 'Timed out' in dialog.view.toPlainText()
    else:
        dialog._poll()
        assert 'Playback changed' in dialog.view.toPlainText()
    assert request.cancelled()
    assert not dialog._poll_timer.isActive()
    assert not dialog._deadline.isActive()
    dialog.close()


@pytest.mark.parametrize('reason', ['close', 'timeout', 'stream-changed'])
def test_media_info_ignores_a_reply_that_could_not_be_cancelled(qapp, reason):
    request = Future()
    request.set_running_or_notify_cancel()
    current = [True]
    dialog = MediaInfoDialog(None, lambda: request, lambda: current[0])
    if reason == 'close':
        dialog.reject()
    elif reason == 'timeout':
        dialog._timed_out()
    else:
        current[0] = False
        dialog._poll()
    before = dialog.view.toPlainText()
    request.set_result('old channel resolution')
    dialog._poll()
    assert dialog.view.toPlainText() == before
    dialog.close()


def test_completed_reply_from_a_superseded_stream_is_rejected(qapp):
    request = Future()
    request.set_result('old channel codec')
    dialog = MediaInfoDialog(None, lambda: request, lambda: False)
    dialog._poll()
    assert 'Playback changed' in dialog.view.toPlainText()
    assert 'old channel' not in dialog.view.toPlainText()
    dialog.close()

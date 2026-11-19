"""A bounded, asynchronous snapshot of the stream playing locally."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout


class MediaInfoDialog(QDialog):
    def __init__(self, parent, request, is_current, channel_name=''):
        super().__init__(parent)
        self.setWindowTitle('Media Information')
        self._request = None
        self._is_current = is_current
        layout = QVBoxLayout(self)
        self.note = QLabel(channel_name or 'Current playback')
        # A channel name is untrusted text, never QLabel HTML.
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setAccessibleName('Media information')
        self.view.setPlainText('Reading media information…')
        layout.addWidget(self.view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(520, 320)

        # Polling a Future's readiness does not wait for mpv and avoids native
        # reply callbacks retaining or accessing a deleted Qt dialog.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.setInterval(5000)
        self._deadline.timeout.connect(self._timed_out)
        self.finished.connect(self._cancel)
        try:
            self._request = request()
        except Exception:
            self.view.setPlainText('Could not read media information.')
        else:
            self._poll_timer.start()
            self._deadline.start()

    def _poll(self):
        if self._request is None:
            return
        if not self._is_current():
            self._finish('Playback changed. Reopen Media Information for the current stream.')
        elif self._request.done():
            try:
                text = self._request.result()
            except Exception:
                text = 'Could not read media information.'
            self._finish(text if isinstance(text, str) and text.strip()
                         else 'Media information is not available yet.')

    def _timed_out(self):
        self._finish('Timed out reading media information. Please try again.')

    def _finish(self, text):
        self._cancel()
        self.view.setPlainText(text[:16384])

    def _cancel(self, *_args):
        self._poll_timer.stop()
        self._deadline.stop()
        request, self._request = self._request, None
        if request is not None and not request.done():
            try:
                request.cancel()
            except Exception:
                # Shutdown or a reply can race mpv's cancellation bookkeeping.
                pass

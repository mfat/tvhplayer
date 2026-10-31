"""Regression: Record and Stop recording must occupy the same control-bar slot."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from tvhplayer.player_bar import PlayerBar


def test_record_and_stop_buttons_share_exact_geometry():
    app = QApplication.instance() or QApplication([])
    bar = PlayerBar(Path(__file__).resolve().parents[1] / "icons")
    try:
        bar.resize(950, 90)
        bar.show()
        app.processEvents()
        expected_width = bar.record_btn.width()
        assert expected_width == bar.recording_group.width()
        assert bar.recording_group.sizeHint().width() <= expected_width
        assert bar.record_btn.height() == bar.recording_group.height() == 36

        for server, local in ((True, False), (True, True), (False, True), (False, False)):
            bar.set_recording(server, local, "TVR 1 HD")
            app.processEvents()
            assert bar.record_btn.width() == expected_width
            assert bar.recording_group.width() == expected_width
            assert bar.record_btn.height() == bar.recording_group.height() == 36
            assert bar.record_btn.isVisible() is (not (server or local))
            assert bar.recording_group.isVisible() is (server or local)
    finally:
        bar.close()
        bar.deleteLater()
        app.processEvents()

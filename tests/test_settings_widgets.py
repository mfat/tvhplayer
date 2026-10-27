from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QWidget

from tvhplayer.settings_widgets import SettingRow, SettingsGroup, StatusStrip, ToggleSwitch


class _WindowsShown(QObject):
    """Widgets shown while they had no parent, so as windows of their own."""

    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(type(obj).__name__)
        return False


def test_building_rows_and_strips_shows_no_window_of_their_own(qapp):
    # On Wayland each such window is a real one with an activation token,
    # and GNOME shows a busy cursor until the tokens run out.
    shown = _WindowsShown()
    qapp.installEventFilter(shown)
    try:
        group = SettingsGroup('Group')
        group.add_row(SettingRow('Title', 'What it does', ToggleSwitch()))
        group.add_row(SettingRow('No description'))
        group.add_strip(StatusStrip('A note'))
        group.add_strip(StatusStrip())
    finally:
        qapp.removeEventFilter(shown)
    assert shown.windows == []


def test_rows_and_strips_show_what_they_have(qapp):
    group = SettingsGroup('Group')
    described = group.add_row(SettingRow('Title', 'What it does'))
    bare = group.add_row(SettingRow('Title'))
    note = group.add_strip(StatusStrip('A note'))
    empty = group.add_strip(StatusStrip())
    group.show()
    QApplication.processEvents()
    assert described.description.isVisible()
    assert not bare.description.isVisible()
    assert note.isVisible()
    assert not empty.isVisible()
    empty.label.setText('Now with text')
    assert empty.isVisible()
    empty.label.setText('')
    assert not empty.isVisible()
    group.hide()

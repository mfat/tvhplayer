from PyQt6.QtWidgets import QLabel


def test_announced_label_keeps_its_text_as_its_name():
    from tvhplayer.a11y import announce_label

    label = QLabel()
    announce_label(label, 'These options cannot be read; they were not saved.')
    assert label.text() == 'These options cannot be read; they were not saved.'
    # No name of its own: screen readers read the text, and hear each change.
    assert label.accessibleName() == ''

    label.setText('')
    assert label.accessibleName() == ''

    label.setAccessibleName('Old message')
    announce_label(label, 'Saved.')
    assert label.accessibleName() == ''
    announce_label(label, 'Saved.')
    assert label.text() == 'Saved.'


def test_key_text_is_written_as_the_platform_shows_it(monkeypatch):
    from PyQt6.QtGui import QKeySequence

    from tvhplayer import a11y

    # Off macOS, the native text is the text written.
    assert a11y.keys_text('Keyboard: Ctrl+E. P or Ctrl+., then Shift+F10, Ctrl+Up') == (
        'Keyboard: Ctrl+E. P or Ctrl+., then Shift+F10, Ctrl+Up'
    )
    assert a11y.keys_text('Shift times by 60') == 'Shift times by 60'
    assert a11y.shortcut_help(mac=False) == a11y.SHORTCUT_HELP

    class Native(QKeySequence):
        def toString(self, _format=None):
            return '<' + super().toString() + '>'

    # On macOS each whole combination, and nothing around it, becomes ⌘ text.
    monkeypatch.setattr(a11y, 'QKeySequence', Native)
    assert a11y.keys_text('Stop (Ctrl+Shift+E), Ctrl+..') == 'Stop (<Ctrl+Shift+E>), <Ctrl+.>.'


def test_shortcut_help_on_macos():
    from tvhplayer import a11y

    text = a11y.shortcut_help(mac=True)
    lines = text.splitlines()
    assert not any(line.strip().startswith('Alt+') for line in lines)
    assert any('Move to the menu bar' in line for line in lines)
    fullscreen = next(line for line in lines if 'Toggle fullscreen' in line)
    assert 'F11' not in fullscreen and a11y.keys_text(a11y.MAC_FULLSCREEN_KEY) in fullscreen
    assert any(line.rstrip().endswith('Quit') for line in lines)
    # The key column stays one width, so a screen reader reads keys then action.
    assert all(line[18] == ' ' for line in lines if line.startswith('  '))

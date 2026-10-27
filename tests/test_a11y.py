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

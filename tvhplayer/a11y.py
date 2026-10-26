"""Accessibility helpers for TVHplayer.

Qt exposes widgets to Orca, Narrator, and VoiceOver through accessible names
and descriptions. Icon-only controls need an explicit name. Status changes
are announced by updating that name, which emits the platform name-change
event. PyQt 6.11 does not wrap QAccessibleAnnouncementEvent, so this name
change is the supported way to notify assistive technology.
"""

from PyQt6.QtGui import QColor, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)
from PyQt6.QtCore import Qt


SHORTCUT_HELP = """\
Channels
  Type letters     Jump to a matching channel
  Enter            Play the selected channel
  Shift+F10        Open the channel menu
  Ctrl+F           Focus channel search
  S                Focus channel search (not while typing in the list)

Playback
  P                Play the selected channel, or stop playback
  Ctrl+.           Stop playback
  M                Mute or unmute
  Ctrl+Up          Raise volume
  Ctrl+Down        Lower volume
  F or F11         Toggle fullscreen
  Escape           Leave fullscreen

Recording
  Ctrl+R           Record on the server
  Ctrl+E           Stop the server recording
  Ctrl+Shift+R     Record on this computer
  Ctrl+Shift+E     Stop the local recording
  Ctrl+G           Open the TV guide at the selected channel

TV guide
  Arrow keys       Move between programmes and channels
  Home             Go back to what is on now
  Ctrl+Home/End    First or last channel
  Page Up/Down     Move a page of channels
  Type letters     Jump to a matching channel
  Enter            Watch the channel
  Ctrl+R           Record the programme, or cancel its recording
  Shift+F10        Open the programme menu
  Ctrl+F           Find a channel

Menus
  Alt+F            File menu
  Alt+V            View menu
  Alt+P            Playback menu: sound track, subtitles, deinterlace
  Alt+H            Help menu
  Ctrl+I           Import a playlist
  Ctrl+Q           Quit (Cmd+Q on macOS)
"""


def prefers_high_contrast():
    """True when the platform asked for a high-contrast theme."""
    app = QApplication.instance()
    if app is None:
        return False
    try:
        hints = app.styleHints().accessibility()
        return hints.contrastPreference() == Qt.ContrastPreference.HighContrast
    except Exception:
        return False


def describe(widget, name=None, description=""):
    """Set the accessible name and the longer description.

    Hover text is separate. A status tip replaces the status bar for as long
    as the pointer is over the widget, so help text does not belong there.
    """
    if name:
        widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
        if hasattr(widget, "setWhatsThis"):
            widget.setWhatsThis(description)
    return widget


def buddy_label(text, widget):
    """A visible label whose mnemonic focuses widget. The label text needs '&'."""
    label = QLabel(text)
    label.setBuddy(widget)
    return label


def button_stylesheet(body, radius=None):
    """Keep a visible keyboard focus ring. High contrast uses the platform style."""
    if prefers_high_contrast():
        return ""
    focus = "border: 2px solid palette(highlight);"
    if radius is not None:
        focus += f" border-radius: {int(radius)}px;"
    return f"QPushButton {{ {body} }} QPushButton:focus {{ {focus} }}"


def announce(widget, message):
    """Make assistive technology notice a status change.

    setAccessibleName emits a name-change event. Repeating the same message
    would be ignored, so the name is cleared first in that case.
    """
    if not message:
        return
    if widget.accessibleName() == message:
        widget.setAccessibleName(" ")
    widget.setAccessibleName(message)


def announce_label(label, message):
    """Show a message and expose the same text to assistive technology."""
    label.setText(message)
    announce(label, message)


def set_item_access(item, name, description=""):
    """Name and description for assistive technology. Does not add a hover popup."""
    item.setData(Qt.ItemDataRole.AccessibleTextRole, name)
    if description:
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, description)


def quality_phrase(percent):
    """Word for a 0-100 signal or SNR reading. Color is not the only cue."""
    if percent >= 80:
        return "good"
    if percent >= 60:
        return "fair"
    if percent >= 40:
        return "weak"
    return "poor"


def quality_colors(percent):
    """Background and text colors that stay readable with the quality word."""
    if percent >= 80:
        return QColor("#166534"), QColor("#ffffff")
    if percent >= 60:
        return QColor("#facc15"), QColor("#1c1917")
    if percent >= 40:
        return QColor("#9a3412"), QColor("#ffffff")
    return QColor("#7f1d1d"), QColor("#ffffff")


def row_emphasis(kind):
    """Row colors for status. None under high contrast, where the status text is enough."""
    if prefers_high_contrast() or not kind:
        return None
    if kind == "recording":
        return QColor("#166534"), QColor("#ffffff")
    if kind == "playing":
        return QColor("#1e3a8a"), QColor("#ffffff")
    if kind == "failed":
        return QColor("#7f1d1d"), QColor("#ffffff")
    return None


def find_shortcut():
    return QKeySequence(QKeySequence.StandardKey.Find)


class ShortcutHelpDialog(QDialog):
    """Plain-text shortcut list that a screen reader can read from the start."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setAccessibleName("Keyboard Shortcuts")
        self.setAccessibleDescription("Keyboard shortcuts for channels, playback, and recording.")
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        self.help_text = QTextEdit()
        self.help_text.setReadOnly(True)
        self.help_text.setPlainText(SHORTCUT_HELP)
        self.help_text.setAccessibleName("Keyboard shortcuts")
        self.help_text.setAccessibleDescription("List of TVHplayer keyboard shortcuts")
        layout.addWidget(self.help_text)
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        close_btn.setAutoDefault(True)
        layout.addWidget(close_btn)

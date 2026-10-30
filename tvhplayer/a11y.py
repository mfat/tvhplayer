"""Accessibility helpers for TVHplayer.

Qt exposes widgets to Orca, Narrator, and VoiceOver through accessible names
and descriptions. Icon-only controls need an explicit name. Status changes
are announced through the platform name-change event. PyQt6 does not wrap
QAccessible or QAccessibleAnnouncementEvent, so that event is the way left
to notify assistive technology. A QLabel sends it on each new text while it
has no accessible name; other widgets send it when their name is set.
"""

import re
import sys

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
  Tab              Leave the list for the next control (Shift+Tab: previous)
  Ctrl+F           Focus channel search
  S                Focus channel search (not while typing in the list)
  Ctrl+J           Jump to now playing in the list
  F5               Reload the channel list from the server
  Ctrl+= or Ctrl+- Taller or shorter channel rows (also Ctrl+mouse wheel)

Playback
  Space            Pause or resume when the player has focus
  P                Play the selected channel, or stop playback
  Ctrl+.           Stop playback
  Ctrl+PgUp        Play the previous channel in the list
  Ctrl+PgDown      Play the next channel in the list
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
  Alt+P            Playback menu: play, volume, recording, sound track, subtitles
  Alt+H            Help menu
  Ctrl+I           Import a playlist
  Ctrl+Q           Quit
"""

MAC = sys.platform == "darwin"
# F11 shows the desktop on macOS; Control+Command+F is its fullscreen key.
MAC_FULLSCREEN_KEY = "Ctrl+Meta+F"
FULLSCREEN_KEY = MAC_FULLSCREEN_KEY if MAC else "F11"
HELP_KEY = "Ctrl+?" if MAC else "F1"

# Ctrl+R, Ctrl+Shift+E, Ctrl+., Shift+F10: modifiers, then a word or one symbol.
_KEY_COMBO = re.compile(r"\b(?:(?:Ctrl|Shift|Alt|Meta)\+)+(?:[A-Za-z0-9]+|[^\sA-Za-z0-9])")


def keys_text(text):
    """Write the key combinations in text as this platform shows them.

    Qt's Ctrl is Command on macOS, where menus show ⌘R for Ctrl+R; text
    written by hand would say Ctrl+R next to it. Elsewhere it is unchanged
    (or translated, as the menus are).
    """
    def native(match):
        sequence = QKeySequence(match.group())
        return sequence.toString(QKeySequence.SequenceFormat.NativeText) or match.group()
    return _KEY_COMBO.sub(native, text)


def shortcut_help(mac=MAC):
    """The keyboard shortcut list, with this platform's keys."""
    lines = []
    for line in SHORTCUT_HELP.splitlines():
        if not line.startswith("  "):
            lines.append(line)
            continue
        keys, text = line[2:19].rstrip(), line[19:]
        if mac and keys.startswith("Alt+"):
            # macOS menus have no Alt letters; Control+F2 moves to the menu bar.
            if keys == "Alt+F":
                lines.append(f"  {keys_text('Meta+F2'):<17}Move to the menu bar (Fn+Control+F2 on a laptop)")
            continue
        if mac:
            keys = keys.replace("F11", MAC_FULLSCREEN_KEY)
        keys = keys_text(keys)
        lines.append(f"  {keys:<16} {text}")
    return "\n".join(lines) + "\n"


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
        description = keys_text(description)
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
    # The app theme pads every button; these are styled whole, often round and icon-only.
    return f"QPushButton {{ padding: 0; {body} }} QPushButton:focus {{ {focus} }}"


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
    """Show a message and expose the same text to assistive technology.

    The label reports the change itself, with its text as its name. A name set
    on it would replace the text and stop those reports, so the old message
    would stay with screen readers after the label is cleared.
    """
    label.setAccessibleName("")
    if message and label.text() == message:
        # The same message again is announced again.
        label.setText("")
    label.setText(message)


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


def with_keys(text, keys):
    """Menu item text that shows keys handled outside the menu, where a shortcut shows.

    A real shortcut on a letter key would take it from typing and type-ahead.
    """
    return f"{text}\t{keys_text(keys)}"


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
        self.help_text.setPlainText(shortcut_help())
        self.help_text.setAccessibleName("Keyboard shortcuts")
        self.help_text.setAccessibleDescription("List of TVHplayer keyboard shortcuts")
        layout.addWidget(self.help_text)
        close_btn = QPushButton("&Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        close_btn.setAutoDefault(True)
        layout.addWidget(close_btn)

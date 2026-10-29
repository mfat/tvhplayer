"""The dark bar under the picture: Play/Stop, channel switching, timeshift, Record, volume and fullscreen.

In fullscreen the same bar floats over the bottom of the picture as a
child overlay on the OpenGL video widget.
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QByteArray, QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

try:
    from .a11y import button_stylesheet, describe, keys_text, prefers_high_contrast, with_keys
except ImportError:
    from a11y import button_stylesheet, describe, keys_text, prefers_high_contrast, with_keys

BAR_BACKGROUND = '#141414'
FLOATING_BACKGROUND = QColor(20, 20, 20, 224)
BUTTON_LIGHT = '#f2f2f2'
PILL_DARK = '#262626'
PILL_DARK_HOVER = '#333333'
RECORD_RED = '#e5484d'
ICON_LIGHT = '#d9d9d9'
CAST_ACTIVE = '#5b9cf8'
MENU_BACKGROUND = '#1f1f1f'

CHEVRON_SVG = (
    '<svg viewBox="0 0 10 10"><path d="M2 3.5 L5 6.5 L8 3.5" stroke="{c}" stroke-width="1.4" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
DOT_SVG = '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="6" fill="{c}"/></svg>'
SQUARE_SVG = '<svg viewBox="0 0 10 10"><rect width="10" height="10" rx="1" fill="{c}"/></svg>'
# Menu icons share one square so the dot, the square and the arrow line up.
MENU_DOT_SVG = '<svg viewBox="0 0 18 18"><circle cx="9" cy="9" r="5" fill="{c}"/></svg>'
MENU_SQUARE_SVG = '<svg viewBox="0 0 18 18"><rect x="4" y="4" width="10" height="10" rx="1" fill="{c}"/></svg>'

# How long the fullscreen bar stays after the pointer last moved.
FLOATING_HIDE_MS = 3000


def svg_icon(markup, color, size):
    """Draw an SVG at twice its size so it stays sharp on high-density screens."""
    data = markup.replace('{c}', color)
    if 'xmlns' not in data:
        data = data.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    # Qt renders an SVG at its own width and height; a 16px icon scaled up would blur.
    data = re.sub(r'<svg\b[^>]*>', lambda tag: re.sub(r'\s(width|height)="[^"]*"', '', tag.group(0)),
                  data, count=1)
    data = data.replace('<svg ', f'<svg width="{size * 2}" height="{size * 2}" ', 1)
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(data.encode()), 'SVG')
    if pixmap.isNull():
        return QIcon()
    pixmap = pixmap.scaled(
        size * 2, size * 2,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def file_icon(path, color, size, pad=0):
    """Draw an icon file in ``color``, which takes the place of its currentColor.

    ``pad`` widens the viewBox by that many units on each side, so the
    picture sits smaller in its square.
    """
    try:
        markup = Path(path).read_text(encoding='utf-8')
    except OSError:
        return QIcon()
    if pad:
        def padded(match):
            x, y, w, h = (float(n) for n in match.group(1).split())
            return f'viewBox="{x - pad} {y - pad} {w + 2 * pad} {h + 2 * pad}"'
        markup = re.sub(r'viewBox="([^"]+)"', padded, markup, count=1)
    return svg_icon(markup.replace('currentColor', '{c}'), color, size)


def _icon_label(markup, color, size):
    label = QLabel()
    label.setPixmap(svg_icon(markup, color, size).pixmap(QSize(size, size)))
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    label.setStyleSheet("background: transparent;")
    return label


class SeekSlider(QSlider):
    """A click on the groove moves the handle there, as on a video seek bar."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(event.position().x()), max(self.width(), 1)))
        super().mousePressEvent(event)


def _slider_stylesheet():
    return (
        "QSlider { background: transparent; min-height: 16px; }"
        "QSlider::groove:horizontal { height: 3px; border-radius: 1px; background: #3a3a3a; }"
        f"QSlider::sub-page:horizontal {{ height: 3px; border-radius: 1px; background: {BUTTON_LIGHT}; }}"
        f"QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; "
        f"border-radius: 6px; background: {BUTTON_LIGHT}; }}"
        "QSlider::handle:horizontal:focus { border: 2px solid palette(highlight); "
        "width: 10px; height: 10px; margin: -6px 0; border-radius: 7px; }"
    )


def _menu_stylesheet():
    if prefers_high_contrast():
        return ""
    return (
        f"QMenu {{ background: {MENU_BACKGROUND}; color: #ededed; border: 1px solid #333333; "
        "border-radius: 8px; padding: 5px; }"
        "QMenu::item { padding: 8px 12px 8px 8px; border-radius: 5px; }"
        "QMenu::item:selected { background: #2e2e2e; }"
        "QMenu::item:disabled { color: #7a7a7a; }"
        "QMenu::separator { height: 1px; background: #333333; margin: 4px 6px; }"
        "QMenu::icon { padding-left: 6px; }"
        "QLabel { color: #ededed; background: transparent; }"
    )


class PlayerBar(QWidget):
    """Controls joined to the bottom of the picture.

    The window connects the buttons and reports state back through
    set_playing(), set_timeshift(), set_recording(), set_muted() and set_fullscreen().
    """

    # Seconds behind live, chosen on the seek bar.
    seek_requested = pyqtSignal(int)

    def __init__(self, icons_dir, parent=None):
        super().__init__(parent)
        self._icons_dir = Path(icons_dir)
        self.setObjectName("player_bar")
        self.setAccessibleName("Player controls")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._contrast = prefers_high_contrast()
        self._playing = False
        self._server = False
        self._local = False
        self._floating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(4)

        # From the oldest buffered picture to live; a click or drag seeks.
        self.seek_slider = SeekSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setTracking(False)
        self.seek_slider.setSingleStep(10)
        self.seek_slider.setPageStep(60)
        if not self._contrast:
            self.seek_slider.setStyleSheet(_slider_stylesheet())
        describe(self.seek_slider, "Timeshift position",
                 "Where the picture is in what has been buffered, from the oldest to live.")
        self.seek_slider.setToolTip("Timeshift position")
        self._seek_updating = False
        self.seek_slider.valueChanged.connect(self._seek_moved)
        root.addWidget(self.seek_slider)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        root.addLayout(layout)

        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setIconSize(QSize(32, 32))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setStyleSheet(button_stylesheet(
            "background: transparent; border: none; border-radius: 18px; }"
            " QPushButton:hover { background: rgba(255,255,255,20);",
            radius=18,
        ))
        self.play_btn.setToolTip("Play / Stop (P)")
        layout.addWidget(self.play_btn)

        self.prev_btn = self._channel_button('skip_previous.svg', "Previous channel", "Ctrl+PgUp")
        layout.addWidget(self.prev_btn)
        self.next_btn = self._channel_button('skip_next.svg', "Next channel", "Ctrl+PgDown")
        layout.addWidget(self.next_btn)

        # Timeshift: shown while a channel plays on this computer.
        self.back_btn = self._icon_button('replay_10.svg')
        describe(self.back_btn, "Back 10 seconds", "Go back 10 seconds in what has been buffered.")
        self.back_btn.setToolTip("Back 10 seconds")
        self.pause_btn = self._icon_button('pause.svg')
        self.forward_btn = self._icon_button('forward_10.svg')
        describe(self.forward_btn, "Forward 10 seconds", "Go forward 10 seconds, up to live.")
        self.forward_btn.setToolTip("Forward 10 seconds")
        self.live_btn = QPushButton("LIVE")
        self.live_btn.setFixedHeight(32)
        self.live_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.live_btn.setStyleSheet(button_stylesheet(
            f"background: {PILL_DARK}; border: none; border-radius: 16px; padding: 0 12px; "
            "color: #ededed; font-weight: 600; }"
            f" QPushButton:hover {{ background: {PILL_DARK_HOVER}; }}"
            " QPushButton:disabled { color: #9a9a9a;",
            radius=16,
        ))
        self._timeshift_controls = (self.seek_slider, self.back_btn, self.pause_btn, self.forward_btn,
                                    self.live_btn)
        for control in (self.back_btn, self.pause_btn, self.forward_btn, self.live_btn):
            layout.addWidget(control)
        self._paused = None
        self._behind = None
        self._seek_span = 0
        self._available_span = 0
        self._timeshift_visible = None

        # Shown while nothing records: a dark pill that opens the Record menu.
        self.record_btn = QPushButton()
        self.record_btn.setFixedHeight(36)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Tab focus only, so a mouse click doesn't leave the focus ring behind.
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.record_btn.setStyleSheet(button_stylesheet(
            f"background: {PILL_DARK}; border: none; border-radius: 18px; }}"
            f" QPushButton:hover {{ background: {PILL_DARK_HOVER};",
            radius=18,
        ))
        inner = QHBoxLayout(self.record_btn)
        inner.setContentsMargins(12, 0, 10, 0)
        inner.setSpacing(8)
        inner.addWidget(_icon_label(DOT_SVG, RECORD_RED, 12))
        self._record_text = QLabel("Record")
        self._record_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if not self._contrast:
            self._record_text.setStyleSheet(
                "color: #ededed; background: transparent; font-weight: 500;"
            )
        inner.addWidget(self._record_text)
        inner.addWidget(_icon_label(CHEVRON_SVG, '#c8c8c8', 10))
        self.record_btn.setMinimumWidth(inner.sizeHint().width())
        describe(
            self.record_btn,
            "Record",
            "Open the record menu: record on the server or on this computer. "
            "Keyboard: Ctrl+R records on the server, Ctrl+Shift+R on this computer.",
        )
        self.record_btn.setToolTip(keys_text("Record (Ctrl+R / Ctrl+Shift+R)"))
        layout.addWidget(self.record_btn)

        # Shown while recording: a red pill. Stop on the left, the Record menu on the right.
        self.recording_group = QFrame()
        self.recording_group.setObjectName("recording_group")
        self.recording_group.setFixedHeight(36)
        self.recording_group.setAccessibleName("Recording")
        if not self._contrast:
            self.recording_group.setStyleSheet(
                f"#recording_group {{ background: {RECORD_RED}; border-radius: 18px; }}"
            )
        group_layout = QHBoxLayout(self.recording_group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(0)
        self.stop_record_btn = QPushButton(" Stop recording")
        self.stop_record_btn.setFixedHeight(36)
        self.stop_record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_record_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.stop_record_btn.setIcon(svg_icon(SQUARE_SVG, '#ffffff', 10))
        self.stop_record_btn.setIconSize(QSize(10, 10))
        self.stop_record_btn.setStyleSheet(button_stylesheet(
            "background: transparent; border: none; color: #ffffff; font-weight: 600; "
            "padding: 0 12px; border-top-left-radius: 18px; border-bottom-left-radius: 18px; }"
            " QPushButton:hover { background: rgba(255,255,255,36);",
            radius=18,
        ))
        group_layout.addWidget(self.stop_record_btn)
        divider = QFrame()
        divider.setFixedWidth(1)
        if not self._contrast:
            divider.setStyleSheet("background: rgba(255,255,255,102); margin: 9px 0;")
        group_layout.addWidget(divider)
        self.record_more_btn = QPushButton()
        self.record_more_btn.setFixedSize(30, 36)
        self.record_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_more_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.record_more_btn.setIcon(svg_icon(CHEVRON_SVG, '#ffffff', 10))
        self.record_more_btn.setIconSize(QSize(10, 10))
        self.record_more_btn.setStyleSheet(button_stylesheet(
            "background: transparent; border: none; padding-right: 2px; "
            "border-top-right-radius: 18px; border-bottom-right-radius: 18px; }"
            " QPushButton:hover { background: rgba(255,255,255,36);",
            radius=18,
        ))
        describe(
            self.record_more_btn,
            "Start another recording",
            "Open the record menu to start the other kind of recording.",
        )
        self.record_more_btn.setToolTip("Start another recording")
        group_layout.addWidget(self.record_more_btn)
        self.recording_group.hide()
        layout.addWidget(self.recording_group)

        # The save icon is as wide as the menu's dot and square.
        local_icon = file_icon(
            Path(icons_dir) / 'download.svg', '#ededed' if not self._contrast else '#000000', 18
        )
        self.record_menu = QMenu(self)
        self.record_menu.setAccessibleName("Record")
        self.record_menu.setStyleSheet(_menu_stylesheet())
        self.record_server_action = self.record_menu.addAction(
            svg_icon(MENU_DOT_SVG, RECORD_RED, 18), with_keys("Record on server…", "Ctrl+R")
        )
        self.record_local_action = self.record_menu.addAction(
            local_icon,
            with_keys("Record on this computer", "Ctrl+Shift+R"),
        )

        self.stop_menu = QMenu(self)
        self.stop_menu.setAccessibleName("Stop which recording?")
        self.stop_menu.setStyleSheet(_menu_stylesheet())
        heading = QWidget()
        heading_layout = QVBoxLayout(heading)
        heading_layout.setContentsMargins(10, 6, 10, 6)
        heading_layout.setSpacing(2)
        title = QLabel("Stop which recording?")
        title.setStyleSheet("" if self._contrast else "color: #ededed; font-weight: 600;")
        self._stop_detail = QLabel("")
        self._stop_detail.setWordWrap(True)
        self._stop_detail.setFixedWidth(280)
        self._stop_detail.setStyleSheet("" if self._contrast else "color: #9a9a9a;")
        heading_layout.addWidget(title)
        heading_layout.addWidget(self._stop_detail)
        heading_action = QWidgetAction(self.stop_menu)
        heading_action.setDefaultWidget(heading)
        heading_action.setEnabled(False)
        self.stop_menu.addAction(heading_action)
        self.stop_server_action = self.stop_menu.addAction(
            svg_icon(MENU_DOT_SVG, RECORD_RED, 18), with_keys("Stop server recording", "Ctrl+E")
        )
        self.stop_local_action = self.stop_menu.addAction(
            local_icon,
            with_keys("Stop local recording", "Ctrl+Shift+E"),
        )
        self.stop_both_action = self.stop_menu.addAction(
            svg_icon(MENU_SQUARE_SVG, '#ff6b6f', 18), "Stop both"
        )
        self.stop_menu.addSeparator()
        self.stop_menu.addAction("Cancel\tEsc")

        self.record_btn.clicked.connect(lambda: self.popup_above(self.record_menu, self.record_btn))
        self.record_more_btn.clicked.connect(
            lambda: self.popup_above(self.record_menu, self.recording_group)
        )

        layout.addStretch(1)

        self.cast_btn = QPushButton()
        self.cast_btn.setFixedSize(32, 32)
        self.cast_btn.setIconSize(QSize(24, 24))
        self.cast_btn.setCheckable(True)
        self.cast_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cast_btn.setStyleSheet(button_stylesheet(
            "background: transparent; border: none; border-radius: 6px; }"
            " QPushButton:checked { background: rgba(91,156,248,40); }"
            " QPushButton:hover { background: rgba(255,255,255,20);",
            radius=6,
        ))
        layout.addWidget(self.cast_btn)

        self.mute_btn = QPushButton()
        self.mute_btn.setFixedSize(32, 32)
        self.mute_btn.setIconSize(QSize(24, 24))
        self.mute_btn.setCheckable(True)
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute_btn.setStyleSheet(button_stylesheet(
            "background: transparent; border: none; border-radius: 6px; }"
            " QPushButton:hover { background: rgba(255,255,255,20);",
            radius=6,
        ))
        layout.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(96)
        self.volume_slider.setSingleStep(1)
        self.volume_slider.setPageStep(10)
        if not self._contrast:
            self.volume_slider.setStyleSheet(_slider_stylesheet())
        layout.addWidget(self.volume_slider)
        self._muted = False
        self.volume_slider.valueChanged.connect(self._update_speaker)

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setFixedSize(32, 32)
        self.fullscreen_btn.setIconSize(QSize(24, 24))
        self.fullscreen_btn.setCheckable(True)
        self.fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fullscreen_btn.setStyleSheet(self.mute_btn.styleSheet())
        layout.addWidget(self.fullscreen_btn)

        for control in (self.play_btn, self.prev_btn, self.next_btn, *self._timeshift_controls,
                        self.cast_btn, self.mute_btn, self.volume_slider, self.fullscreen_btn):
            control.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        self.set_playing(False)
        self.set_timeshift(None)
        self.set_casting(False)
        self.set_muted(False)
        self.set_fullscreen(False)
        self._apply_background()

    def _icon_color(self):
        return '#000000' if self._contrast else ICON_LIGHT

    def _icon_button(self, icon):
        button = QPushButton()
        button.setFixedSize(32, 32)
        button.setIconSize(QSize(24, 24))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(button_stylesheet(
            "background: transparent; border: none; border-radius: 6px; }"
            " QPushButton:hover { background: rgba(255,255,255,20);",
            radius=6,
        ))
        button.setIcon(file_icon(self._icons_dir / icon, self._icon_color(), 24))
        return button

    def _channel_button(self, icon, label, keys):
        button = self._icon_button(icon)
        button.setToolTip(keys_text(f"{label} ({keys})"))
        describe(button, label, keys_text(f"Play the {label.split()[0].lower()} channel in the list. Keyboard: {keys}."))
        return button

    def _apply_background(self):
        if self._contrast:
            return
        if self._floating:
            self.setStyleSheet("#player_bar { background: transparent; }")
        else:
            self.setStyleSheet(f"#player_bar {{ background: {BAR_BACKGROUND}; }}")

    def set_floating(self, floating):
        self._floating = bool(floating)
        self._apply_background()

    def popup_above(self, menu, anchor):
        """Open a menu just above a control, where it does not hide the bar."""
        hint = menu.sizeHint()
        menu.popup(anchor.mapToGlobal(QPoint(0, -hint.height() - 6)))

    def set_playing(self, playing):
        self._playing = bool(playing)
        name = 'stop_circle.svg' if self._playing else 'play_circle.svg'
        self.play_btn.setIcon(file_icon(self._icons_dir / name, self._icon_color(), 32))
        if self._playing:
            describe(self.play_btn, "Stop", "Stop playback. Keyboard: P or Ctrl+.")
        else:
            describe(self.play_btn, "Play", "Play the selected channel. Keyboard: P, or Enter on the channel list.")

    def _seek_moved(self, value):
        if not self._seek_updating:
            value = max(value, self._seek_span - self._available_span)
            self._seek_updating = True
            self.seek_slider.setValue(value)
            self._seek_updating = False
            self.seek_requested.emit(self._seek_span - value)

    def set_timeshift(self, state):
        """The player's ``(paused, behind, span)``, or None to hide the timeshift controls."""
        visible = state is not None
        if visible != self._timeshift_visible:
            self._timeshift_visible = visible
            for control in self._timeshift_controls:
                control.setVisible(visible)
        if state is None:
            self._paused = self._behind = None
            self._seek_span = 0
            return
        paused, behind, span = state
        self._available_span = max(0, int(span))
        # Keep the longest span seen this channel. mpv drops old packets as you
        # play, which would otherwise shrink the bar and yank the handle left.
        self._seek_span = max(self._seek_span, int(span), int(behind))
        if not self.seek_slider.isSliderDown():
            self._seek_updating = True
            self.seek_slider.setRange(0, self._seek_span)
            self.seek_slider.setValue(self._seek_span - int(behind))
            self._seek_updating = False
        if paused != self._paused:
            self._paused = paused
            self.pause_btn.setIcon(file_icon(
                self._icons_dir / ('play_arrow.svg' if paused else 'pause.svg'), self._icon_color(), 24))
            name = "Resume" if paused else "Pause"
            describe(self.pause_btn, name, "Resume from where it paused." if paused
                     else "Pause the channel; it keeps buffering so you can resume where you left off.")
            self.pause_btn.setToolTip(name)
        behind = int(behind)
        if behind == self._behind:
            return
        # The name changes only between live and behind, so screen readers are not told every second.
        if self._behind is None or (behind > 0) != (self._behind > 0):
            if behind > 0:
                describe(self.live_btn, "Go to live", "Shows how far behind live the picture is.")
                self.live_btn.setToolTip("Go to live")
            else:
                describe(self.live_btn, "Live", "The picture is live.")
                self.live_btn.setToolTip("Live")
        self._behind = behind
        self.live_btn.setText(f"−{_clock(behind)}" if behind > 0 else "LIVE")
        self.live_btn.setEnabled(behind > 0)

    def set_recording(self, server, local, channel_name='', local_here=None):
        """Swap Record for Stop recording while either kind runs.

        ``local_here`` says this channel records to this computer; another
        channel can still start one. It defaults to ``local``.
        """
        local_here = bool(local) if local_here is None else bool(local_here)
        self._server, self._local = bool(server), bool(local)
        recording = self._server or self._local
        self.record_btn.setVisible(not recording)
        self.recording_group.setVisible(recording)
        both = self._server and self._local
        if both:
            self.stop_record_btn.setToolTip("Stop recording… (asks which)")
            describe(
                self.stop_record_btn,
                "Stop recording",
                "Recording on the server and on this computer. Asks which to stop.",
            )
        elif self._server:
            self.stop_record_btn.setToolTip(keys_text("Stop the server recording (Ctrl+E)"))
            describe(self.stop_record_btn, "Stop recording", "Stop the recording on the server. Keyboard: Ctrl+E.")
        else:
            self.stop_record_btn.setToolTip(keys_text("Stop the recording on this computer (Ctrl+Shift+E)"))
            describe(
                self.stop_record_btn,
                "Stop recording",
                "Stop the recording on this computer. Keyboard: Ctrl+Shift+E.",
            )
        name = channel_name or 'This channel'
        self._stop_detail.setText(f"{name} is recording on the server and on this computer.")
        if self._server:
            self.record_server_action.setText("Record on server\tRecording")
        else:
            self.record_server_action.setText(with_keys("Record on server…", "Ctrl+R"))
        self.record_server_action.setEnabled(not self._server)
        if local_here:
            self.record_local_action.setText("Record on this computer\tRecording")
        else:
            self.record_local_action.setText(with_keys("Record on this computer", "Ctrl+Shift+R"))
        self.record_local_action.setEnabled(not local_here)

    def set_muted(self, muted):
        self._muted = bool(muted)
        self.mute_btn.setChecked(self._muted)
        self._update_speaker()

    def _update_speaker(self):
        volume = self.volume_slider.value()
        if self._muted:
            name = 'volume_off.svg'
        elif volume == 0:
            name = 'volume_mute.svg'
        elif volume < 50:
            name = 'volume_down.svg'
        else:
            name = 'volume_up.svg'
        self.mute_btn.setIcon(file_icon(self._icons_dir / name, self._icon_color(), 24))

    def set_casting(self, casting, name=''):
        casting = bool(casting)
        self.cast_btn.setChecked(casting)
        color = CAST_ACTIVE if casting and not self._contrast else self._icon_color()
        self.cast_btn.setIcon(file_icon(self._icons_dir / 'cast.svg', color, 24))
        if casting:
            label = f'Casting to {name}' if name else 'Casting'
            describe(self.cast_btn, label, 'Choose another Chromecast or disconnect.')
            self.cast_btn.setToolTip(label)
        else:
            describe(self.cast_btn, 'Cast', 'Play channels on a Chromecast or Cast-enabled television.')
            self.cast_btn.setToolTip('Cast to a device')

    def set_fullscreen(self, fullscreen):
        self.fullscreen_btn.setChecked(bool(fullscreen))
        name = 'fullscreen_exit.svg' if fullscreen else 'fullscreen.svg'
        self.fullscreen_btn.setIcon(file_icon(self._icons_dir / name, self._icon_color(), 24))


def _clock(seconds):
    """1:05 or 1:02:05."""
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


class _PulseDot(QWidget):
    """A dot that blinks on and off while something records."""

    SIZE = 8
    BLINK_MS = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.color = QColor('#ffffff')
        self._lit = True
        self._blink = QTimer(self)
        self._blink.setInterval(self.BLINK_MS)
        self._blink.timeout.connect(self._toggle)

    def _toggle(self):
        self._lit = not self._lit
        self.update()

    def start(self):
        if not self._blink.isActive():
            self._lit = True
            self.update()
            self._blink.start()

    def stop(self):
        self._blink.stop()
        self._lit = True
        self.update()

    def is_pulsing(self):
        return self._blink.isActive()

    def paintEvent(self, event):
        if not self._lit:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()


class RecordingBadge(QPushButton):
    """The status bar's red pill while anything records; a click opens Tasks."""

    HEIGHT = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 10, 0)
        layout.setSpacing(6)
        self.dot = _PulseDot(self)
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel()
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        if prefers_high_contrast():
            self.dot.color = self.palette().color(self.foregroundRole())
        else:
            radius = self.HEIGHT // 2
            self.setStyleSheet(button_stylesheet(
                f"background: {RECORD_RED}; border: none; border-radius: {radius}px;",
                radius=radius,
            ) + " QPushButton:hover { background: #d13d42; } QPushButton:pressed { background: #b8343a; }")
            self.label.setStyleSheet(
                "color: #ffffff; background: transparent; font-weight: 600;"
            )
        self.setToolTip("Show recordings in Tasks")
        self._count = 0
        self.hide()
        self._describe()

    def text(self):
        return self.label.text()

    def count(self):
        return self._count

    def set_count(self, count):
        """How many recordings run; more than one is shown on the pill."""
        self._count = max(int(count or 0), 0)
        if self.label.text():
            self._show_text()

    def start(self):
        self._show_text()
        self.show()
        self.dot.start()

    def stop(self):
        self.dot.stop()
        self.label.setText("")
        self.hide()
        self._describe()

    def _show_text(self):
        self.label.setText(f"{self._count} recordings" if self._count > 1 else "Recording")
        self.setMinimumWidth(self.layout().sizeHint().width())
        self._describe()

    def _describe(self):
        if not self.label.text():
            describe(self, "Not recording", "Shown only while a recording is in progress")
            return
        name = f"{self._count} recordings in progress" if self._count > 1 else "Recording in progress"
        describe(self, name, "Open Tasks to see or stop the recordings.")


class FloatingBar(QWidget):
    """Holds the player bar over the bottom of the picture in fullscreen.

    It appears when the pointer moves or a key is pressed, and fades out
    of the way after a few seconds unless the pointer rests on it.
    """

    MARGIN_X = 24
    MARGIN_BOTTOM = 18
    RADIUS = 26

    def __init__(self, window):
        # Child of the main window over the OpenGL video widget. A separate
        # Tool window cannot place itself on Wayland.
        super().__init__(window)
        # A child shows with its window; the bar waits for fullscreen.
        self.hide()
        self._window = window
        self._bar = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAccessibleName("Player controls")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_idle)

    @property
    def bar(self):
        return self._bar

    def hold(self, bar):
        self._bar = bar
        bar.set_floating(True)
        self.layout().addWidget(bar)
        bar.show()

    def release(self):
        bar, self._bar = self._bar, None
        self._hide_timer.stop()
        self.hide()
        if bar is not None:
            self.layout().removeWidget(bar)
            bar.set_floating(False)
        return bar

    def place(self):
        frame = self._window.rect()
        height = self._bar.sizeHint().height() if self._bar is not None else 52
        width = max(frame.width() - 2 * self.MARGIN_X, 200)
        self.setGeometry(
            frame.x() + (frame.width() - width) // 2,
            frame.y() + frame.height() - self.MARGIN_BOTTOM - height,
            width,
            height,
        )

    def poke(self):
        """Show the bar and start the countdown to hiding it again."""
        if self._bar is None:
            return
        self.place()
        if not self.isVisible():
            self.show()
        self.raise_()
        self._hide_timer.start(FLOATING_HIDE_MS)

    def _hide_if_idle(self):
        if self._bar is None:
            return
        menus = (self._bar.record_menu, self._bar.stop_menu)
        if self.underMouse() or any(menu.isVisible() for menu in menus):
            self._hide_timer.start(FLOATING_HIDE_MS)
            return
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.RADIUS, self.RADIUS)
        painter.fillPath(path, FLOATING_BACKGROUND)
        painter.end()


__all__ = ['PlayerBar', 'FloatingBar', 'RecordingBadge', 'file_icon', 'svg_icon']

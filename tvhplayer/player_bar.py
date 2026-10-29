"""The dark bar under the picture: Play/Stop, Record, volume and fullscreen.

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

PLAY_SVG = '<svg viewBox="0 0 48 48"><path d="M19 13 L19 35 L36 24 Z" fill="{c}"/></svg>'
STOP_SVG = '<svg viewBox="0 0 48 48"><rect x="15" y="15" width="18" height="18" rx="2" fill="{c}"/></svg>'
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
    set_playing(), set_recording(), set_muted() and set_fullscreen().
    """

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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setIconSize(QSize(24, 24))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setStyleSheet(button_stylesheet(
            f"background: {BUTTON_LIGHT}; border: none; border-radius: 18px; }}"
            f" QPushButton:hover {{ background: #ffffff;",
            radius=18,
        ))
        self.play_btn.setToolTip("Play / Stop (P)")
        layout.addWidget(self.play_btn)

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
            Path(icons_dir) / 'save-fill.svg', '#ededed' if not self._contrast else '#000000', 18, pad=6
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
            self.volume_slider.setStyleSheet(
                "QSlider { background: transparent; min-height: 16px; }"
                "QSlider::groove:horizontal { height: 3px; border-radius: 1px; background: #3a3a3a; }"
                f"QSlider::sub-page:horizontal {{ height: 3px; border-radius: 1px; background: {BUTTON_LIGHT}; }}"
                f"QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; "
                f"border-radius: 6px; background: {BUTTON_LIGHT}; }}"
                "QSlider::handle:horizontal:focus { border: 2px solid palette(highlight); "
                "width: 10px; height: 10px; margin: -6px 0; border-radius: 7px; }"
            )
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

        for control in (self.play_btn, self.cast_btn, self.mute_btn, self.volume_slider, self.fullscreen_btn):
            control.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        self.set_playing(False)
        self.set_casting(False)
        self.set_muted(False)
        self.set_fullscreen(False)
        self._apply_background()

    def _icon_color(self):
        return '#000000' if self._contrast else ICON_LIGHT

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
        dark = '#000000' if self._contrast else BAR_BACKGROUND
        if self._playing:
            self.play_btn.setIcon(svg_icon(STOP_SVG, dark, 22))
            describe(self.play_btn, "Stop", "Stop playback. Keyboard: P or Ctrl+.")
        else:
            self.play_btn.setIcon(svg_icon(PLAY_SVG, dark, 24))
            describe(self.play_btn, "Play", "Play the selected channel. Keyboard: P, or Enter on the channel list.")

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
            name = 'volume-mute-fill.svg'
        elif volume == 0:
            name = 'volume-off-fill.svg'
        elif volume < 50:
            name = 'volume-down-fill.svg'
        else:
            name = 'volume-up-fill.svg'
        self.mute_btn.setIcon(file_icon(self._icons_dir / name, self._icon_color(), 24))

    def set_casting(self, casting, name=''):
        casting = bool(casting)
        self.cast_btn.setChecked(casting)
        color = CAST_ACTIVE if casting and not self._contrast else self._icon_color()
        self.cast_btn.setIcon(file_icon(self._icons_dir / 'chromecast.svg', color, 24))
        if casting:
            label = f'Casting to {name}' if name else 'Casting'
            describe(self.cast_btn, label, 'Choose another Chromecast or disconnect.')
            self.cast_btn.setToolTip(label)
        else:
            describe(self.cast_btn, 'Cast', 'Play channels on a Chromecast or Cast-enabled television.')
            self.cast_btn.setToolTip('Cast to a device')

    def set_fullscreen(self, fullscreen):
        self.fullscreen_btn.setChecked(bool(fullscreen))
        name = 'fullscreen-exit.svg' if fullscreen else 'fullscreen.svg'
        self.fullscreen_btn.setIcon(file_icon(self._icons_dir / name, self._icon_color(), 24))


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


__all__ = ['PlayerBar', 'FloatingBar', 'file_icon', 'svg_icon']

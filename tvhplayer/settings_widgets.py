"""Building blocks for settings pages: switch, row, group, status strip, sidebar."""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)  # QCheckBox is the base of ToggleSwitch

try:
    from .ui_theme import color as theme_color, is_active as theme_is_active, is_organic
except ImportError:
    from ui_theme import color as theme_color, is_active as theme_is_active, is_organic


# QWIDGETSIZE_MAX, the maximum size of a widget with none set.
QWIDGETSIZE_MAX = (1 << 24) - 1


def _heading_font(label, scale=1.0):
    """The TVHplayer theme's style sets headings; with a Qt style they are bold in its font."""
    if theme_is_active():
        return
    font = QApplication.font()
    font.setWeight(QFont.Weight.DemiBold)
    if scale != 1.0:
        font.setPointSizeF(font.pointSizeF() * scale)
    label.setFont(font)


def _alpha(color, alpha):
    """``color`` with an alpha from 0 to 255. Colors come from the palette, so any theme, light or dark, fits."""
    color = QColor(color)
    color.setAlpha(alpha)
    return color


class ToggleSwitch(QCheckBox):
    """A QCheckBox drawn as a switch. ``text`` becomes the accessible name; the row shows the label.

    With a Qt style instead of the TVHplayer theme it is that style's checkbox.
    """

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setAccessibleName(text.replace('&', ''))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b'offset', self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._move)

    def sizeHint(self):
        if not theme_is_active():
            return super().sizeHint()
        return QSize(40, 24)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def _get_offset(self):
        return self._offset

    def _set_offset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(float, _get_offset, _set_offset)

    def _move(self, on):
        end = 1.0 if on else 0.0
        if not self.isVisible():
            self._set_offset(end)
            return
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(end)
        self._anim.start()

    def showEvent(self, event):
        self._set_offset(1.0 if self.isChecked() else 0.0)
        super().showEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            # A switch with the TVHplayer theme, the style's checkbox otherwise: another size.
            self.updateGeometry()
        super().changeEvent(event)

    def paintEvent(self, event):
        if not theme_is_active():
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, (self.height() - 20) / 2, 36, 20)
        pal = self.palette()
        accent = pal.color(QPalette.ColorRole.Highlight)
        ink = pal.color(QPalette.ColorRole.Text)
        on_color = accent if self.isEnabled() else _alpha(accent, 90)
        color = on_color if self.isChecked() else _alpha(ink, 72)
        if not self.isEnabled() and not self.isChecked():
            color = _alpha(ink, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(track, 10, 10)
        knob = QRectF(track.x() + 2 + self._offset * 16, track.y() + 2, 16, 16)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob.translated(0, 0.8))
        # On the accent, the accent's own ink: Organic's dark accent is near white.
        p.setBrush(pal.color(QPalette.ColorRole.HighlightedText) if self.isChecked() else QColor('#ffffff'))
        p.drawEllipse(knob)
        if self.hasFocus():
            pen = p.pen()
            pen.setStyle(Qt.PenStyle.SolidLine)
            pen.setColor(accent)
            pen.setWidthF(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Center the 2px stroke inside the 40x24 switch bounds. Expanding
            # the track by 2px put half the stroke outside the widget and
            # caused Qt to clip the corners of the focus ring.
            ring = track.adjusted(-1, -1, 1, 1)
            p.drawRoundedRect(ring, ring.height() / 2, ring.height() / 2)


class SettingRow(QWidget):
    """Title and description on the left, the control on the right (or below when ``stacked``)."""

    def __init__(self, title, description='', control=None, stacked=False, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(3)
        self.title = title if isinstance(title, QLabel) else QLabel(title)
        self.title.setObjectName('rowTitle')
        self.title.setWordWrap(True)
        self.description = QLabel(description)
        self.description.setObjectName('rowDesc')
        self.description.setWordWrap(True)
        # Only hidden, never shown here: shown before the grid adopts it, it would be a
        # window of its own, which on Wayland leaves GNOME showing a busy cursor.
        if not description:
            self.description.hide()
        grid.addWidget(self.title, 0, 0)
        grid.addWidget(self.description, 1, 0)
        grid.setColumnStretch(0, 1)
        if control is not None:
            self.title.setBuddy(control)
            if stacked:
                grid.setVerticalSpacing(6)
                grid.addWidget(control, 2, 0, 1, 2)
            else:
                grid.addWidget(control, 0, 1, 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.control = control

    def mousePressEvent(self, event):
        # Clicking anywhere on a switch row flips the switch, like clicking a checkbox label.
        if isinstance(self.control, ToggleSwitch) and self.control.isEnabled():
            self.control.toggle()
            self.control.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)


class StatusLabel(QLabel):
    """Shows its strip only while it has text, so empty status lines take no space."""

    def __init__(self, strip):
        super().__init__('')
        self._strip = strip
        self.setObjectName('statusText')
        self.setWordWrap(True)

    def setText(self, text):
        super().setText(text)
        self._strip.refresh()


class StatusStrip(QFrame):
    """Tinted footer inside a group for live feedback or a standing note."""

    def __init__(self, text='', progress=False, parent=None):
        super().__init__(parent)
        self.setObjectName('statusStrip')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)
        self.progress = None
        if progress:
            self.progress = QProgressBar()
            self.progress.setTextVisible(False)
            self.progress.hide()
            layout.addWidget(self.progress)
        self.label = StatusLabel(self)
        layout.addWidget(self.label)
        self.label.setText(text)

    def refresh(self):
        busy = self.progress is not None and not self.progress.isHidden()
        wanted = bool(self.label.text()) or busy
        # Shown only inside its group, as for row descriptions; add_strip refreshes it there.
        if wanted and self.parentWidget() is None:
            return
        self.setVisible(wanted)


class SettingsGroup(QWidget):
    """A titled card of rows separated by hairlines, with an optional status strip at the bottom."""

    def __init__(self, title='', parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._heading = None
        if title:
            self._heading = QLabel(title)
            self._heading.setObjectName('groupTitle')
            outer.addWidget(self._heading)
        self.card = QFrame()
        self.card.setObjectName('groupCard')
        self._rows = QVBoxLayout(self.card)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        self._lines = []
        self._line_above = {}
        outer.addWidget(self.card)
        self._restyle()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            self._restyle()
        super().changeEvent(event)

    def _restyle(self):
        """The TVHplayer theme draws the card and its hairlines; a Qt style draws its own panel and lines."""
        if self._heading is not None:
            _heading_font(self._heading)
        active = theme_is_active()
        self.card.setFrameShape(QFrame.Shape.NoFrame if active else QFrame.Shape.StyledPanel)
        for line in self._lines:
            self._restyle_line(line, active)

    @staticmethod
    def _restyle_line(line, active):
        if active:
            line.setFrameShape(QFrame.Shape.NoFrame)
            line.setFixedHeight(1)
        else:
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            line.setMinimumHeight(0)
            line.setMaximumHeight(QWIDGETSIZE_MAX)

    def add_row(self, row):
        if self._rows.count():
            line = QFrame()
            line.setObjectName('rowSeparator')
            self._restyle_line(line, theme_is_active())
            self._lines.append(line)
            self._rows.addWidget(line)
            self._line_above[row] = line
        self._rows.addWidget(row)
        return row

    def set_row_visible(self, row, visible):
        """Show or hide a row with the line above it."""
        row.setVisible(visible)
        line = self._line_above.get(row)
        if line is not None:
            line.setVisible(visible)

    def add_strip(self, strip):
        self._rows.addWidget(strip)
        strip.refresh()
        return strip


class SettingsPage(QScrollArea):
    """A scrolling page with a title; add groups to ``layout``."""

    def __init__(self, title, intro='', parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName('settingsPage')
        self.layout_ = QVBoxLayout(body)
        self.layout_.setContentsMargins(28, 24, 28, 32)
        self.layout_.setSpacing(22)
        self._heading = QLabel(title)
        self._heading.setObjectName('pageTitle')
        _heading_font(self._heading, 1.4)
        self._heading.setAccessibleName(title)
        self.layout_.addWidget(self._heading)
        if intro:
            text = QLabel(intro)
            text.setObjectName('pageIntro')
            text.setWordWrap(True)
            self.layout_.addWidget(text)
        self.setWidget(body)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            _heading_font(self._heading, 1.4)
        super().changeEvent(event)

    def add(self, widget):
        self.layout_.addWidget(widget)
        return widget

    def finish(self):
        self.layout_.addStretch(1)


SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1


class _NavDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 50)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(0, 1, 0, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        ink = option.palette.color(QPalette.ColorRole.Text)
        p.setPen(Qt.PenStyle.NoPen)
        if not theme_is_active():
            # A Qt style draws the selection and hover as in its other lists.
            style = option.widget.style() if option.widget is not None else QApplication.style()
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, p, option.widget)
            if selected:
                ink = option.palette.color(QPalette.ColorRole.HighlightedText)
        elif selected and is_organic():
            # Organic fills the selected page with the accent, as its lists.
            p.setBrush(theme_color('selected'))
            p.drawRoundedRect(r, 14, 14)
            ink = theme_color('selected_ink')
        elif selected:
            # The app's highlight: the theme gives lists a clear one, as ThemeStyle draws their selection.
            p.setBrush(_alpha(QApplication.palette().color(QPalette.ColorRole.Highlight), 56))
            p.drawRoundedRect(r, 6, 6)
        elif hover:
            p.setBrush(_alpha(ink, 18))
            radius = 14 if is_organic() else 6
            p.drawRoundedRect(r, radius, radius)
        title_font = QFont(option.font)
        title_font.setPointSizeF(option.font.pointSizeF() * 1.04)
        title_font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
        p.setFont(title_font)
        p.setPen(ink)
        p.drawText(r.adjusted(12, 7, -12, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, index.data())
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(option.font.pointSizeF() * 0.9)
        p.setFont(sub_font)
        p.setPen(_alpha(ink, 165))
        p.drawText(r.adjusted(12, 0, -12, -7), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   index.data(SUBTITLE_ROLE) or '')
        p.restore()


class SettingsNav(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('settingsNav')
        self.setFixedWidth(208)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSpacing(1)
        self.setMouseTracking(True)
        self.setItemDelegate(_NavDelegate(self))
        self.setAccessibleName('Settings pages')

    def add_page(self, title, subtitle):
        item = QListWidgetItem(title)
        item.setData(SUBTITLE_ROLE, subtitle)
        item.setToolTip(subtitle)
        self.addItem(item)
        return item

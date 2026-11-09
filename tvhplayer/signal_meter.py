"""Signal meters: a coloured bar and its number for a tuner's strength and quality.

Shared by any view that shows reception (the channel scan first). Feed it
``core.signal.SignalReadings``; the bar's colour follows the reading's level,
and the number beside it says the same, so colour is not the only cue.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

try:
    from .a11y import prefers_high_contrast
    from .core.playback_status import SIGNAL_FAIR, SIGNAL_GOOD, SIGNAL_NONE, SIGNAL_POOR
    from .core.signal import UNRATED, SignalReadings
    from .ui_theme import color as theme_color, is_active as theme_is_active
except ImportError:
    from a11y import prefers_high_contrast
    from core.playback_status import SIGNAL_FAIR, SIGNAL_GOOD, SIGNAL_NONE, SIGNAL_POOR
    from core.signal import UNRATED, SignalReadings
    from ui_theme import color as theme_color, is_active as theme_is_active

# Bar colours by level; the number beside the bar says the same.
LEVEL_COLORS = {
    SIGNAL_GOOD: QColor('#22c55e'),
    SIGNAL_FAIR: QColor('#eab308'),
    SIGNAL_POOR: QColor('#f97316'),
    SIGNAL_NONE: QColor('#ef4444'),
}


class SignalBar(QWidget):
    """A horizontal bar filled to a percentage, in the colour of its level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._percent = 0
        self._level = SIGNAL_NONE
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_value(self, percent, level):
        percent = max(0, min(100, int(percent)))
        if (percent, level) != (self._percent, self._level):
            self._percent, self._level = percent, level
            self.update()

    def percent(self):
        return self._percent

    def level(self):
        return self._level

    def fill_color(self):
        if prefers_high_contrast():
            return self.palette().color(QPalette.ColorRole.Highlight)
        if self._level == UNRATED:
            # Not judged, so not a warning colour either.
            return theme_color('accent') if theme_is_active() else self.palette().color(QPalette.ColorRole.Highlight)
        return LEVEL_COLORS.get(self._level, LEVEL_COLORS[SIGNAL_NONE])

    def sizeHint(self):
        return QSize(72, max(6, self.fontMetrics().height() // 2))

    def minimumSizeHint(self):
        return QSize(32, self.sizeHint().height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        height = self.sizeHint().height()
        rect = QRectF(0.5, (self.height() - height) / 2 + .5, self.width() - 1, height - 1)
        radius = rect.height() / 2
        if prefers_high_contrast():
            painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            track = theme_color('track') if theme_is_active() else self.palette().color(QPalette.ColorRole.Mid)
            if not theme_is_active():
                track.setAlpha(90)
            painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)
        if self._percent > 0:
            fill = QRectF(rect.left(), rect.top(), max(rect.height(), rect.width() * self._percent / 100), rect.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.fill_color())
            painter.drawRoundedRect(fill, radius, radius)
        painter.end()


class _Gauge(QWidget):
    """A caption, a bar and the number: "Quality ▮▮▮▯ 84%"."""

    def __init__(self, caption, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.caption = QLabel(caption)
        self.caption.setObjectName('rowDesc')
        self.bar = SignalBar()
        self.number = QLabel('')
        self.number.setObjectName('rowDesc')
        self.number.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Room for "100%", so bars line up from row to row; a tuner that
        # reports dB or dBm does so on every row, so those line up too.
        self.number.setMinimumWidth(self.number.fontMetrics().horizontalAdvance('100%'))
        layout.addWidget(self.caption)
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.number)

    def set_reading(self, reading):
        self.setVisible(reading is not None)
        if reading is not None:
            self.bar.set_value(reading.percent, reading.level)
            self.number.setText(reading.text)


class SignalMeter(QWidget):
    """Strength and quality of a tuner, side by side, each a coloured bar with its number.

    A reading the tuner does not give is left out. The meter's accessible name
    says the readings in words.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.strength = _Gauge('Strength')
        self.quality = _Gauge('Quality')
        layout.addWidget(self.strength, 1)
        layout.addWidget(self.quality, 1)
        self._readings = SignalReadings()
        self.set_readings(SignalReadings())

    def set_readings(self, readings):
        readings = readings or SignalReadings()
        self._readings = readings
        self.strength.set_reading(readings.strength)
        self.quality.set_reading(readings.quality)
        self.setVisible(bool(readings))
        self.setAccessibleName(readings.describe() if readings else 'No signal reading')

    def readings(self):
        return self._readings

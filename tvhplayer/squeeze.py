"""Rows of controls that give up room step by step as they get narrower."""

from PyQt6.QtCore import QEvent, QSize
from PyQt6.QtWidgets import QWidget


def _invalidate(layout):
    """Forget cached sizes of a layout and the layouts inside it; Qt only clears the one."""
    for index in range(layout.count()):
        inner = layout.itemAt(index).layout()
        if inner is not None:
            _invalidate(inner)
    layout.invalidate()


class Squeeze:
    """Steps that make a widget narrower, taken in order as the room runs out.

    Each step is a callable ``step(on)``: on makes the row narrower (hides a
    control, drops a button's text), off undoes it. Level n has the first n
    steps on. The widget asks ``minimum()`` for its minimum width and calls
    ``fit(width)`` when it is resized.

    The width each level needs comes from the widget's own layout, by putting
    the level on and asking; the answers are kept until ``invalidate()``.
    """

    def __init__(self, widget, steps):
        self._widget = widget
        self._steps = list(steps)
        self._level = 0
        self._widths = None
        self._probing = False

    @property
    def level(self):
        return self._level

    def invalidate(self):
        self._widths = None

    def _apply(self, level):
        for index, step in enumerate(self._steps):
            step(index < level)

    def widths(self):
        """Width each level needs, from no steps to all of them."""
        if self._widths is None and not self._probing:
            self._probing = True
            layout = self._widget.layout()
            widths = []
            try:
                for level in range(len(self._steps) + 1):
                    self._apply(level)
                    _invalidate(layout)
                    widths.append(layout.totalMinimumSize().width())
            finally:
                self._apply(self._level)
                _invalidate(layout)
                self._probing = False
            self._widths = widths
        return self._widths or [0]

    def minimum(self):
        return self.widths()[-1]

    def fit(self, width):
        """Take as few steps as the width allows."""
        if self._probing:
            return
        widths = self.widths()
        level = next((n for n, need in enumerate(widths) if need <= width), len(widths) - 1)
        if level != self._level:
            self._level = level
            self._apply(level)
            _invalidate(self._widget.layout())


class SqueezeRow(QWidget):
    """A row whose minimum width is its narrowest level; ``steps`` as for Squeeze."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.squeeze = Squeeze(self, ())

    def set_steps(self, steps):
        self.squeeze = Squeeze(self, steps)
        self.refit()

    def refit(self):
        self.squeeze.invalidate()
        self.squeeze.fit(self.width())
        self.updateGeometry()

    def minimumSizeHint(self):
        return QSize(self.squeeze.minimum(), super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.squeeze.fit(event.size().width())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.refit()

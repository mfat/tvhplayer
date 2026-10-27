"""Themes: TVHplayer's own look, or a Qt style, light or dark as the desktop is.

The TVHplayer theme is a style over Fusion that draws the app's own look from
a light or a dark set of colors, with a palette made from the same colors.
Qt keeps style sheets for small, local changes and does not support them over
a style of the app's own, so the look is drawn, not written as a style sheet.
Any other theme is a Qt style, which paints the same colors through a palette
of every role, as Jottr's Classic look does, rather than the desktop's. Every
theme is light or dark as the desktop is set, following it while the app
runs, unless set to always light or always dark. Both can be changed while the
app runs. Under high contrast the system look stays in charge.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, QStandardPaths, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleFactory,
    QStyleOption,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStyleOptionFrame,
    QStyleOptionHeader,
    QStyleOptionMenuItem,
    QStyleOptionProgressBar,
    QStyleOptionSlider,
    QStyleOptionSpinBox,
    QStyleOptionToolButton,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QToolTip,
    QTreeView,
    QWidget,
)

try:
    from . import system_color_scheme as desktop
    from .core.config import SCHEME_DARK, SCHEME_LIGHT, SCHEME_SYSTEM, THEME_TVHPLAYER
except ImportError:
    import system_color_scheme as desktop
    from core.config import SCHEME_DARK, SCHEME_LIGHT, SCHEME_SYSTEM, THEME_TVHPLAYER

LIGHT = {
    'ink': '#232629', 'muted': '#5d6166', 'placeholder': '#8a8d90', 'link': '#1d79b0',
    'window': '#eff0f1', 'base': '#fcfcfc', 'alt': '#f6f7f7', 'read_only': '#f3f4f5',
    'nav': '#e6e8ea', 'strip': '#f6f7f7', 'strip_ink': '#3b3f43',
    'accent': '#3daee9', 'primary': '#2c8fc9', 'primary_edge': '#2478aa', 'primary_hover': '#267fb4',
    'primary_off': '#9fcbe5', 'on_accent': '#ffffff',
    'hover': '#f2f8fc', 'pressed': '#e3f2fb',
    'edge': 'rgba(35,38,41,64)', 'edge_soft': 'rgba(35,38,41,36)', 'menu_edge': 'rgba(35,38,41,51)',
    'rule': 'rgba(35,38,41,31)', 'hairline': 'rgba(35,38,41,26)', 'tint': 'rgba(35,38,41,18)',
    # Solid, unlike the see-through edges: drawn around a list, a see-through
    # one would darken where it crosses the list's own background.
    'list_edge': '#bcbdbf',
    'scroll': 'rgba(35,38,41,70)', 'scroll_hover': 'rgba(35,38,41,110)', 'track': 'rgba(35,38,41,31)',
    'disabled': 'rgba(35,38,41,110)', 'disabled_soft': 'rgba(35,38,41,90)',
    'selected': 'rgba(61,174,233,51)', 'selected_ink': '#124a6a',
    'tooltip': '#232629', 'tooltip_ink': '#ffffff',
    'arrow': '#5d6166', 'arrow_off': '#b8babc',
}

DARK = {
    'ink': '#fcfcfc', 'muted': '#a1a9b1', 'placeholder': '#7f868c', 'link': '#3daee9',
    'window': '#202326', 'base': '#292c30', 'alt': '#2e3236', 'read_only': '#25282b',
    'nav': '#1b1e20', 'strip': '#25282b', 'strip_ink': '#d0d3d6',
    'accent': '#3daee9', 'primary': '#2c8fc9', 'primary_edge': '#3daee9', 'primary_hover': '#349fd6',
    'primary_off': '#2b4a5c', 'on_accent': '#ffffff',
    'hover': '#2d3a44', 'pressed': '#2a4a5e',
    'edge': 'rgba(252,252,252,51)', 'edge_soft': 'rgba(252,252,252,31)', 'menu_edge': 'rgba(252,252,252,40)',
    'rule': 'rgba(252,252,252,26)', 'hairline': 'rgba(252,252,252,20)', 'tint': 'rgba(252,252,252,20)',
    'list_edge': '#4b4f53',
    'scroll': 'rgba(252,252,252,70)', 'scroll_hover': 'rgba(252,252,252,120)', 'track': 'rgba(252,252,252,31)',
    'disabled': 'rgba(252,252,252,100)', 'disabled_soft': 'rgba(252,252,252,80)',
    'selected': 'rgba(61,174,233,64)', 'selected_ink': '#d4eefc',
    'tooltip': '#31363b', 'tooltip_ink': '#fcfcfc',
    'arrow': '#a1a9b1', 'arrow_off': '#5c6166',
}

# Labels the settings pages and dialogs name: point size, weight, color, color when disabled.
LABELS = {
    'pageTitle': (15, QFont.Weight.DemiBold, None, None),
    'pageIntro': (None, None, 'muted', None),
    'groupTitle': (None, QFont.Weight.DemiBold, None, None),
    'rowTitle': (10.5, None, None, None),
    'rowDesc': (9, None, 'muted', 'disabled_soft'),
    'statusText': (9.5, None, 'strip_ink', None),
    'footerNote': (9.5, None, 'muted', None),
}
# Frames the settings pages and dialogs name, drawn by ThemeStyle.
NAMED_FRAMES = ('groupCard', 'rowSeparator', 'statusStrip', 'dialogFooter', 'settingsNav')

# Arrows on dropdowns and number boxes, as points in a 10 by 10 box.
DOWN = ((2, 3.5), (5, 6.5), (8, 3.5))
UP = ((2, 6.5), (5, 3.5), (8, 6.5))

# The colors in use, and whether the TVHplayer theme is on.
colors = LIGHT
_active = False
# Kept by apply(): the desktop's scheme, whether it is watched, the style,
# the app's font before the theme's, and the theme's font.
_scheme = None
_mode = SCHEME_SYSTEM
_watching = False
_style = None
_default_font = None
_theme_font = None

PE = QStyle.PrimitiveElement
CE = QStyle.ControlElement
CC = QStyle.ComplexControl
SC = QStyle.SubControl
SE = QStyle.SubElement
PM = QStyle.PixelMetric
CT = QStyle.ContentsType
State = QStyle.StateFlag


def is_active():
    return _active


def _palette(c):
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c['window'],
        QPalette.ColorRole.WindowText: c['ink'],
        QPalette.ColorRole.Base: c['base'],
        QPalette.ColorRole.AlternateBase: c['alt'],
        QPalette.ColorRole.Text: c['ink'],
        QPalette.ColorRole.Button: c['base'],
        QPalette.ColorRole.ButtonText: c['ink'],
        QPalette.ColorRole.Highlight: c['accent'],
        QPalette.ColorRole.HighlightedText: c['on_accent'],
        QPalette.ColorRole.ToolTipBase: c['tooltip'],
        QPalette.ColorRole.ToolTipText: c['tooltip_ink'],
        QPalette.ColorRole.PlaceholderText: c['placeholder'],
        QPalette.ColorRole.Link: c['link'],
        QPalette.ColorRole.Mid: c['list_edge'],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    disabled = _qcolor(c['disabled'])
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return pal


def _qcolor(value):
    """QColor from "#rrggbb" or "rgba(r,g,b,a)" with a from 0 to 255."""
    if value.startswith('rgba('):
        r, g, b, a = (int(part) for part in value[5:-1].split(','))
        return QColor(r, g, b, a)
    return QColor(value)


def color(name):
    """A color of the TVHplayer theme in use, for widgets that paint themselves."""
    return _qcolor(colors[name])


def _load_fonts():
    """Use bundled Noto Sans if it ships in fonts/, otherwise the system copy or the default."""
    global _theme_font
    if _theme_font is not None:
        return _theme_font
    fonts = Path(__file__).resolve().parent / 'fonts'
    if fonts.is_dir():
        for file in fonts.glob('*.ttf'):
            QFontDatabase.addApplicationFont(str(file))
    if 'Noto Sans' in QFontDatabase.families():
        _theme_font = QFont('Noto Sans', 10)
    return _theme_font


def polish_main_window(window):
    """With the TVHplayer theme, flatten the raised side panes and hide the splitter handle;
    without it, put them back. Call after the UI is built and after each theme change."""
    for name in ('left_pane', 'right_pane', 'tasks_pane'):
        pane = getattr(window, name, None)
        if pane is not None:
            if pane.property('tvhplayer_frame') is None:
                pane.setProperty('tvhplayer_frame', pane.frameStyle())
            pane.setFrameStyle(QFrame.Shape.NoFrame if _active else pane.property('tvhplayer_frame'))
            pane.setObjectName(name)
    splitter = getattr(window, 'splitter', None)
    if splitter is not None:
        # Invisible, but wide enough to grab; -1 is the style's own width.
        splitter.setHandleWidth(6 if _active else -1)


def _row_ends(view, index):
    """Whether ``index`` is in the first and the last visible column of its row."""
    if isinstance(view, QTableView):
        header = view.horizontalHeader()
    elif isinstance(view, QTreeView):
        header = view.header()
    else:
        return True, True
    shown = [header.logicalIndex(v) for v in range(header.count()) if not header.isSectionHidden(header.logicalIndex(v))]
    if not shown:
        return True, True
    return index.column() == shown[0], index.column() == shown[-1]


# Drawing ---------------------------------------------------------------------

def _box(painter, rect, radius, fill=None, edge=None, width=1):
    """A rounded box; the edge is drawn inside ``rect``."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(rect)
    if edge is not None:
        r = r.adjusted(width / 2, width / 2, -width / 2, -width / 2)
        radius = max(0.0, radius - width / 2)
        painter.setPen(QPen(edge, width))
    else:
        painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(r, radius, radius)
    painter.restore()


def _field(painter, rect, fill, focused):
    """Text fields, dropdowns and number boxes: a thin edge, a thicker accent one with focus."""
    if focused:
        _box(painter, rect, 4, fill, color('accent'), 2)
    else:
        _box(painter, rect, 4, fill, color('edge'))


def _chevron(painter, rect, points, ink, size):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size / 10
    center = QRectF(rect).center()
    path = QPainterPath()
    for i, (x, y) in enumerate(points):
        point = QPointF(center.x() + (x - 5) * scale, center.y() + (y - 5) * scale)
        path.moveTo(point) if i == 0 else path.lineTo(point)
    pen = QPen(ink, 1.6 * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


def _line(painter, x, y, width, height, name):
    painter.fillRect(QRect(x, y, width, height), color(name))


def _in_combo_popup(widget):
    parent = widget.parentWidget() if widget is not None else None
    return parent is not None and parent.inherits('QComboBoxPrivateContainer')


def _frame_kind(widget):
    """Which of the theme's frames ``widget`` gets, or None for the base style's."""
    if widget is None:
        return None
    name = widget.objectName()
    if name in NAMED_FRAMES:
        return name
    if isinstance(widget, QAbstractItemView) and not isinstance(widget, QHeaderView):
        return 'popup' if _in_combo_popup(widget) else 'list'
    if isinstance(widget, QScrollArea) or widget.inherits('QComboBoxPrivateContainer'):
        return 'none'
    return None


# What each frame leaves around its contents: left, top, right, bottom. A list's
# padding keeps its square header and rows inside the rounded edge.
FRAME_INSETS = {
    'list': (5, 5, 5, 5),
    'popup': (5, 5, 5, 5),
    'settingsNav': (10, 14, 11, 14),
    'groupCard': (1, 1, 1, 1),
    'statusStrip': (0, 1, 0, 0),
    'dialogFooter': (0, 1, 0, 0),
    'rowSeparator': (0, 0, 0, 0),
    'none': (0, 0, 0, 0),
}


def _draw_frame(kind, painter, rect):
    if kind == 'list':
        _box(painter, rect, 6, color('base'), color('list_edge'))
    elif kind == 'popup':
        _box(painter, rect, 4, color('base'), color('edge'))
    elif kind == 'settingsNav':
        # Edges are see-through: drawn over what is behind the frame, not over its fill.
        painter.fillRect(rect.adjusted(0, 0, -1, 0), color('nav'))
        _line(painter, rect.right(), rect.top(), 1, rect.height(), 'rule')
    elif kind == 'groupCard':
        _box(painter, rect, 8, color('base'), color('edge_soft'))
    elif kind == 'statusStrip':
        r = QRectF(rect.adjusted(0, 1, 0, 0))
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        top = QPainterPath()
        top.addRect(QRectF(r.x(), r.y(), r.width(), r.height() / 2))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(path.united(top), color('strip'))
        painter.restore()
        _line(painter, rect.left(), rect.top(), rect.width(), 1, 'hairline')
    elif kind == 'dialogFooter':
        painter.fillRect(rect.adjusted(0, 1, 0, 0), color('window'))
        _line(painter, rect.left(), rect.top(), rect.width(), 1, 'rule')
    elif kind == 'rowSeparator':
        painter.fillRect(rect, color('hairline'))


def _option_classes():
    import PyQt6.QtWidgets as widgets

    found = {}
    for name in dir(widgets):
        if name.startswith('QStyleOption') and not name.endswith('V2'):
            cls = getattr(widgets, name)
            kind = getattr(getattr(cls, 'StyleOptionType', None), 'Type', None)
            if kind is not None:
                found.setdefault(kind.value, cls)
    return found


OPTION_CLASSES = _option_classes()


def _typed(option):
    """``option`` as the class its type says.

    Qt makes options on the stack, and PyQt can hand on the Python object of
    an earlier option that lived at the same address, of another class.
    """
    cls = OPTION_CLASSES.get(option.type)
    if cls is None or type(option) is cls:
        return option
    # sip casts only up or down the class tree, so through the common base.
    return sip.cast(sip.cast(option, QStyleOption), cls)


def _primary(widget):
    return isinstance(widget, QPushButton) and bool(widget.property('primary'))


# What the look sets on widgets themselves ------------------------------------

def _keep(widget):
    """Remember the widget's own palette and font once, for _undress()."""
    if widget.property('theme_palette') is None:
        widget.setProperty('theme_palette', QPalette(widget.palette()))
        widget.setProperty('theme_font', QFont(widget.font()))


LIVE = (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive)
ALL = LIVE + (QPalette.ColorGroup.Disabled,)


def _set_ink(palette, role, name, groups=LIVE):
    for group in groups:
        palette.setColor(group, role, color(name))


def _dress(widget):
    """Give ``widget`` the colors and fonts the look needs that a style cannot draw.

    Done again after a light or dark change, as the colors are set on the
    widget; _undress() gives the widget back what it had.
    """
    name = widget.objectName()
    palette = font = None
    if isinstance(widget, QLabel) and name in LABELS:
        size, weight, ink, ink_off = LABELS[name]
        _keep(widget)
        if size or weight:
            font = QFont(QApplication.font())
            if size:
                font.setPointSizeF(size)
            if weight:
                font.setWeight(weight)
        if ink:
            palette = QPalette(widget.property('theme_palette'))
            _set_ink(palette, QPalette.ColorRole.WindowText, ink)
            if ink_off:
                _set_ink(palette, QPalette.ColorRole.WindowText, ink_off, (QPalette.ColorGroup.Disabled,))
    elif isinstance(widget, QHeaderView):
        _keep(widget)
        # On the header, not in its painting: Qt fits and shortens the titles with the header's font.
        font = QFont(widget.property('theme_font'))
        font.setWeight(QFont.Weight.DemiBold)
    elif isinstance(widget, QAbstractItemView):
        _keep(widget)
        palette = QPalette(widget.property('theme_palette'))
        # ThemeStyle draws the selected row as a light tint, so its text is dark, not white.
        _set_ink(palette, QPalette.ColorRole.HighlightedText, 'ink' if _in_combo_popup(widget) else 'selected_ink')
        if name == 'settingsNav':
            _set_ink(palette, QPalette.ColorRole.Base, 'nav', ALL)
        if isinstance(widget, QTableView) and widget.property('theme_grid') is None:
            # The theme draws no grid lines, which left a gap between cells.
            widget.setProperty('theme_grid', widget.showGrid())
            widget.setShowGrid(False)
    elif isinstance(widget, QLineEdit) and widget.property('mono'):
        _keep(widget)
        font = QFont(widget.property('theme_font'))
        font.setFamilies(['Noto Sans Mono', 'DejaVu Sans Mono', 'monospace'])
        font.setStyleHint(QFont.StyleHint.Monospace)
    elif isinstance(widget, QProgressBar) and not widget.isTextVisible():
        # Qt keeps a bar at least a line of text tall; the theme's has no text.
        if widget.property('theme_height') is None:
            widget.setProperty('theme_height', widget.maximumHeight())
        widget.setMaximumHeight(4)
    elif isinstance(widget, QComboBox):
        # Qt's own list delegate fills the whole row with the accent; a styled one lets
        # ThemeStyle draw the row. The combo's own is put back for other styles.
        delegate = widget.itemDelegate()
        if not isinstance(delegate, QStyledItemDelegate):
            widget.setProperty('theme_delegate', delegate)
            widget.setItemDelegate(QStyledItemDelegate(widget))
    if palette is not None:
        widget.setPalette(palette)
    if font is not None:
        widget.setFont(font)
    if isinstance(widget, QFrame) and _frame_kind(widget) is not None:
        # The frame's width was taken before the widget had its name, or from another style.
        widget.setFrameStyle(widget.frameStyle())


def _undress(widget):
    if widget.property('theme_palette') is not None:
        widget.setPalette(widget.property('theme_palette'))
        widget.setFont(widget.property('theme_font'))
        widget.setProperty('theme_palette', None)
        widget.setProperty('theme_font', None)
    if widget.property('theme_height') is not None:
        widget.setMaximumHeight(widget.property('theme_height'))
        widget.setProperty('theme_height', None)
    if widget.property('theme_grid') is not None:
        widget.setShowGrid(widget.property('theme_grid'))
        widget.setProperty('theme_grid', None)
    native = widget.property('theme_delegate')
    if native is not None:
        ours = widget.itemDelegate()
        # Qt picks the right delegate for the next style from this one.
        widget.setItemDelegate(native)
        widget.setProperty('theme_delegate', None)
        if ours is not native:
            ours.deleteLater()


# The style ---------------------------------------------------------------------

class ThemeStyle(QProxyStyle):
    """With the TVHplayer theme on, Fusion drawn in the app's own look; otherwise the style as it is.

    Each drawing call checks the theme, so that this style can stay under
    another Qt style for the app's own rules (see NoDialogButtonIconsStyle).
    """

    def __init__(self, key):
        super().__init__(key)
        self._busy = {}
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(33)
        self._busy_timer.timeout.connect(self._step_busy)

    # Widgets ---------------------------------------------------------------

    def polish(self, target):
        result = super().polish(target)
        if _active and isinstance(target, QWidget):
            _dress(target)
        return result

    def unpolish(self, target):
        # Not by _active: the theme is already off when the style it leaves unpolishes.
        if isinstance(target, QWidget):
            _undress(target)
        return super().unpolish(target)

    def _step_busy(self):
        for key, bar in list(self._busy.items()):
            if sip.isdeleted(bar) or not bar.isVisible() or bar.maximum() != bar.minimum():
                del self._busy[key]
            else:
                bar.update()
        if not self._busy:
            self._busy_timer.stop()

    # Sizes -------------------------------------------------------------------

    def pixelMetric(self, metric, option=None, widget=None):
        if _active:
            if metric == PM.PM_ScrollBarExtent:
                return 10
            if metric == PM.PM_ScrollBarSliderMin:
                return 30
            if metric in (PM.PM_MenuHMargin, PM.PM_MenuVMargin):
                return 4
            if metric == PM.PM_MenuPanelWidth:
                return 1
            if metric == PM.PM_MenuBarHMargin:
                return 6
            if metric == PM.PM_MenuBarVMargin:
                return 2
            if metric == PM.PM_MenuBarItemSpacing:
                return 6
            if metric == PM.PM_MenuBarPanelWidth:
                return 0
            if metric == PM.PM_ToolTipLabelFrameWidth:
                return 5
        return super().pixelMetric(metric, option, widget)

    def sizeFromContents(self, kind, option, size, widget=None):
        option = _typed(option)
        if not _active:
            return super().sizeFromContents(kind, option, size, widget)
        # Each adds the theme's padding and edge to what the widget needs for its text.
        if kind == CT.CT_PushButton:
            return QSize(size.width() + 30, size.height() + 10)
        if kind == CT.CT_ToolButton:
            return QSize(size.width() + 21, size.height() + 13)
        if kind == CT.CT_LineEdit and isinstance(option, QStyleOptionFrame) and option.lineWidth > 0:
            return QSize(size.width() + 18, size.height() + 10)
        if kind == CT.CT_ComboBox and isinstance(option, QStyleOptionComboBox) and option.frame:
            return QSize(size.width() + 44, size.height() + 10)
        if kind == CT.CT_SpinBox and isinstance(widget, QSpinBox):
            return QSize(size.width() + 76, size.height() + 9)
        if kind == CT.CT_ProgressBar and isinstance(option, QStyleOptionProgressBar) and not option.textVisible:
            return QSize(size.width(), 4)
        if kind == CT.CT_HeaderSection and isinstance(option, QStyleOptionHeader):
            base = super().sizeFromContents(kind, option, size, widget)
            return QSize(base.width() + 16, base.height() + 13)
        if kind == CT.CT_MenuBarItem:
            return QSize(size.width() + 20, size.height() + 10)
        if kind == CT.CT_MenuItem and isinstance(option, QStyleOptionMenuItem):
            base = super().sizeFromContents(kind, option, size, widget)
            if option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
                return QSize(base.width(), 9)
            return QSize(base.width() + 3, max(base.height(), option.fontMetrics.height() + 12))
        if kind == CT.CT_ItemViewItem and _in_combo_popup(widget):
            base = super().sizeFromContents(kind, option, size, widget)
            return QSize(base.width() + 18, option.fontMetrics.height() + 12)
        return super().sizeFromContents(kind, option, size, widget)

    def subElementRect(self, element, option, widget=None):
        option = _typed(option)
        if _active:
            if element in (SE.SE_ShapedFrameContents, SE.SE_FrameContents):
                kind = _frame_kind(widget)
                if kind is not None:
                    left, top, right, bottom = FRAME_INSETS[kind]
                    return option.rect.adjusted(left, top, -right, -bottom)
            elif (element == SE.SE_LineEditContents and isinstance(option, QStyleOptionFrame)
                  and option.lineWidth > 0):
                return option.rect.adjusted(9, 5, -9, -5)
            elif element == SE.SE_HeaderLabel and isinstance(option, QStyleOptionHeader):
                return option.rect.adjusted(8, 6, -8, -7)
            elif element == SE.SE_ItemViewItemText and _in_combo_popup(widget):
                r = super().subElementRect(element, option, widget)
                r.setLeft(r.left() + 12)
                return r
        return super().subElementRect(element, option, widget)

    def subControlRect(self, control, option, sub, widget=None):
        option = _typed(option)
        if not _active:
            return super().subControlRect(control, option, sub, widget)
        r = option.rect
        if control == CC.CC_ComboBox and isinstance(option, QStyleOptionComboBox) and option.frame:
            if sub == SC.SC_ComboBoxArrow:
                return QRect(r.right() - 24, r.top() + 1, 24, r.height() - 2)
            if sub == SC.SC_ComboBoxEditField:
                return QRect(r.left() + 9, r.top() + 5, r.width() - 34, r.height() - 10)
            if sub == SC.SC_ComboBoxFrame:
                return QRect(r)
        elif control == CC.CC_SpinBox and isinstance(widget, QSpinBox):
            half = r.height() // 2
            if sub == SC.SC_SpinBoxUp:
                return QRect(r.right() - 21, r.top() + 3, 20, half - 3)
            if sub == SC.SC_SpinBoxDown:
                return QRect(r.right() - 21, r.top() + half, 20, r.height() - half - 3)
            if sub == SC.SC_SpinBoxEditField:
                return QRect(r.left() + 9, r.top() + 5, r.width() - 32, r.height() - 10)
            if sub == SC.SC_SpinBoxFrame:
                return QRect(r)
        elif control == CC.CC_ScrollBar and isinstance(option, QStyleOptionSlider):
            return self._scroll_rect(option, sub)
        return super().subControlRect(control, option, sub, widget)

    @staticmethod
    def _scroll_rect(option, sub):
        """A bar with no arrow buttons: a rounded handle in a 2px margin."""
        groove = option.rect.adjusted(2, 2, -2, -2)
        if sub == SC.SC_ScrollBarGroove:
            return groove
        if sub not in (SC.SC_ScrollBarSlider, SC.SC_ScrollBarSubPage, SC.SC_ScrollBarAddPage):
            return QRect()
        horizontal = option.orientation == Qt.Orientation.Horizontal
        length = groove.width() if horizontal else groove.height()
        span = option.maximum - option.minimum
        handle = length if span <= 0 else max(30, length * option.pageStep // (span + option.pageStep))
        handle = min(handle, length)
        start = QStyle.sliderPositionFromValue(option.minimum, option.maximum, option.sliderPosition,
                                               length - handle, option.upsideDown)
        if sub == SC.SC_ScrollBarSlider:
            first, size = start, handle
        elif sub == SC.SC_ScrollBarSubPage:
            first, size = 0, start
        else:
            first, size = start + handle, length - start - handle
        if horizontal:
            return QRect(groove.left() + first, groove.top(), size, groove.height())
        return QRect(groove.left(), groove.top() + first, groove.width(), size)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        # Fusion opens a dropdown like a menu, over the dropdown; the theme opens a list below it.
        if _active and hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    # Painting ------------------------------------------------------------------

    def drawPrimitive(self, element, option, painter, widget=None):
        option = _typed(option)
        if _active and self._draw_primitive(element, option, painter, widget):
            return
        super().drawPrimitive(element, option, painter, widget)

    def _draw_primitive(self, element, option, painter, widget):
        """Draw ``element`` the theme's way; False leaves it to Fusion."""
        state = option.state
        if element == PE.PE_PanelButtonCommand:
            self._button(option, painter, widget)
        elif element == PE.PE_PanelButtonTool and isinstance(widget, QToolButton):
            self._button(option, painter, widget)
        elif element == PE.PE_FrameFocusRect:
            # Buttons and fields show focus with their edge; lists show none.
            return isinstance(widget, (QPushButton, QToolButton, QAbstractItemView, QComboBox))
        elif element == PE.PE_PanelLineEdit:
            if not isinstance(option, QStyleOptionFrame) or option.lineWidth <= 0:
                return False
            read_only = isinstance(widget, QLineEdit) and widget.isReadOnly()
            _field(painter, option.rect, color('read_only' if read_only else 'base'), state & State.State_HasFocus)
        elif element == PE.PE_PanelItemViewItem:
            if not (state & State.State_Selected and isinstance(widget, QAbstractItemView)
                    and isinstance(option, QStyleOptionViewItem)):
                return False
            self._selected_row(option, painter, widget)
        elif element == PE.PE_PanelItemViewRow:
            if not (state & State.State_Selected and isinstance(option, QStyleOptionViewItem)):
                return False
            # The selection is drawn on the cells, rounded at the row's ends.
            self._unselected(element, option, painter, widget)
        elif element == PE.PE_IndicatorBranch and state & State.State_Selected:
            # Only the arrow, for the same reason.
            self._unselected(element, option, painter, widget)
        elif element == PE.PE_PanelScrollAreaCorner:
            pass
        elif element == PE.PE_PanelMenu:
            if not isinstance(widget, QMenu):
                return False
            _box(painter, option.rect, 6, color('base'))
        elif element == PE.PE_FrameMenu:
            if not isinstance(widget, QMenu):
                return False
            _box(painter, option.rect, 6, None, color('menu_edge'))
        elif element == PE.PE_PanelMenuBar:
            pass
        elif element == PE.PE_PanelStatusBar:
            painter.fillRect(option.rect, color('window'))
            _line(painter, option.rect.left(), option.rect.top(), option.rect.width(), 1, 'rule')
        elif element == PE.PE_FrameStatusBarItem:
            pass
        elif element == PE.PE_PanelTipLabel:
            painter.fillRect(option.rect, color('tooltip'))
        else:
            return False
        return True

    def _unselected(self, element, option, painter, widget):
        state = option.state
        option.state = state & ~State.State_Selected
        super().drawPrimitive(element, option, painter, widget)
        option.state = state

    @staticmethod
    def _button(option, painter, widget):
        state = option.state
        enabled = bool(state & State.State_Enabled)
        focused = bool(state & State.State_HasFocus) and enabled
        if _primary(widget):
            fill = color('primary_off' if not enabled else
                         'primary_hover' if state & State.State_MouseOver else 'primary')
            edge = color('primary_off' if not enabled else 'primary_edge')
        else:
            fill = color('pressed' if state & State.State_Sunken else
                         'hover' if enabled and state & State.State_MouseOver else 'base')
            edge = color('accent' if focused or (enabled and state & State.State_MouseOver) else
                         'edge' if enabled else 'edge_soft')
        _box(painter, option.rect, 4, fill, edge, 2 if focused else 1)

    @staticmethod
    def _selected_row(option, painter, widget):
        """A selected row is one tint, rounded at its two ends.

        A table counts hidden columns, so with its first column hidden no
        visible cell would start the row: the ends are the visible ones.
        """
        first, last = _row_ends(widget, option.index)
        rect = QRectF(option.rect)
        # The rounded shape runs past the cell on a side that joins another cell, then is cut off.
        if not first:
            rect.setLeft(rect.left() - 8)
        if not last:
            rect.setRight(rect.right() + 8)
        painter.save()
        painter.setClipRect(option.rect)
        _box(painter, rect, 4, color('selected'))
        painter.restore()

    def drawControl(self, element, option, painter, widget=None):
        option = _typed(option)
        if _active and self._draw_control(element, option, painter, widget):
            return
        super().drawControl(element, option, painter, widget)

    def _draw_control(self, element, option, painter, widget):
        state = option.state
        if element == CE.CE_ShapedFrame:
            kind = _frame_kind(widget)
            if kind is None:
                return False
            _draw_frame(kind, painter, option.rect)
        elif (element == CE.CE_PushButtonBevel and isinstance(option, QStyleOptionButton)
              and option.features & QStyleOptionButton.ButtonFeature.Flat):
            # The theme gives flat buttons their edge too.
            features = option.features
            option.features = features & ~QStyleOptionButton.ButtonFeature.Flat
            super().drawControl(element, option, painter, widget)
            option.features = features
        elif element == CE.CE_PushButtonLabel and _primary(widget) and isinstance(option, QStyleOptionButton):
            label = QStyleOptionButton(option)
            label.palette = QPalette(option.palette)
            for group in ALL:
                label.palette.setColor(group, QPalette.ColorRole.ButtonText, color('on_accent'))
            super().drawControl(element, label, painter, widget)
        elif element == CE.CE_HeaderSection and isinstance(option, QStyleOptionHeader):
            r = option.rect
            if option.orientation == Qt.Orientation.Horizontal:
                _line(painter, r.left(), r.bottom(), r.width(), 1, 'edge')
        elif element == CE.CE_HeaderLabel and isinstance(option, QStyleOptionHeader):
            label = QStyleOptionHeader(option)
            label.palette = QPalette(option.palette)
            for group in LIVE:
                label.palette.setColor(group, QPalette.ColorRole.ButtonText, color('muted'))
            super().drawControl(element, label, painter, widget)
        elif element == CE.CE_HeaderEmptyArea:
            pass
        elif element == CE.CE_ProgressBar and isinstance(option, QStyleOptionProgressBar):
            if option.textVisible or not state & State.State_Horizontal:
                return False
            self._thin_progress(option, painter, widget)
        elif element == CE.CE_Splitter:
            pass
        elif element in (CE.CE_MenuBarEmptyArea, CE.CE_MenuBarItem) and isinstance(option, QStyleOptionMenuItem):
            self._menu_bar(element, option, painter, widget)
        elif element == CE.CE_MenuItem:
            if not (isinstance(widget, QMenu) and isinstance(option, QStyleOptionMenuItem)):
                return False
            self._menu_item(option, painter, widget)
        elif element == CE.CE_MenuEmptyArea:
            pass
        else:
            return False
        return True

    def _thin_progress(self, option, painter, widget):
        """The thin bar shown without a percentage: a track and an accent fill."""
        r = option.rect
        _box(painter, r, 2, color('track'))
        if option.maximum == option.minimum:
            # Busy: a piece of fill runs along the track.
            if isinstance(widget, QProgressBar):
                self._busy[id(widget)] = widget
                if not self._busy_timer.isActive():
                    self._busy_timer.start()
            size = max(r.width() * 3 // 10, 8)
            step = int(time.monotonic() * r.width() * 0.8) % (r.width() + size)
            chunk = QRect(r.left() + step - size, r.top(), size, r.height())
            painter.save()
            painter.setClipRect(r)
            _box(painter, chunk, 2, color('accent'))
            painter.restore()
            return
        done = (option.progress - option.minimum) / (option.maximum - option.minimum)
        width = round(r.width() * min(max(done, 0.0), 1.0))
        if width > 0:
            chunk = QRect(r.left(), r.top(), width, r.height())
            if option.invertedAppearance:
                chunk.moveRight(r.right())
            _box(painter, chunk, 2, color('accent'))

    def _menu_bar(self, element, option, painter, widget):
        titlebar = widget is not None and bool(widget.property('titlebar'))
        r = option.rect
        if not titlebar:
            painter.fillRect(r, color('window'))
            if widget is not None:
                _line(painter, r.left(), widget.height() - 1, r.width(), 1, 'rule')
        if element == CE.CE_MenuBarEmptyArea:
            return
        state = option.state
        if state & State.State_Enabled and state & (State.State_Selected | State.State_Sunken):
            _box(painter, r, 4, color('tint'))
        flags = (Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextShowMnemonic.value
                 | Qt.TextFlag.TextDontClip.value | Qt.TextFlag.TextSingleLine.value)
        if not self.styleHint(QStyle.StyleHint.SH_UnderlineShortcut, option, widget):
            flags |= Qt.TextFlag.TextHideMnemonic.value
        self.drawItemText(painter, r, flags, option.palette, bool(state & State.State_Enabled),
                          option.text, QPalette.ColorRole.WindowText)

    def _menu_item(self, option, painter, widget):
        r = option.rect
        if option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
            _line(painter, r.left() + 8, r.top() + r.height() // 2, r.width() - 16, 1, 'hairline')
            return
        if option.state & State.State_Selected and option.state & State.State_Enabled:
            _box(painter, r, 4, color('selected'))
        # Fusion draws the check, icon, text, shortcut and arrow on the theme's own highlight.
        state = option.state
        option.state = state & ~State.State_Selected
        super().drawControl(CE.CE_MenuItem, option, painter, widget)
        option.state = state

    def drawComplexControl(self, control, option, painter, widget=None):
        option = _typed(option)
        if _active and self._draw_complex(control, option, painter, widget):
            return
        super().drawComplexControl(control, option, painter, widget)

    def _draw_complex(self, control, option, painter, widget):
        state = option.state
        enabled = bool(state & State.State_Enabled)
        if control == CC.CC_ComboBox:
            if not (isinstance(option, QStyleOptionComboBox) and option.frame):
                return False
            _field(painter, option.rect, color('base'), state & State.State_HasFocus)
            arrow = self.subControlRect(control, option, SC.SC_ComboBoxArrow, widget)
            _chevron(painter, arrow, DOWN, color('arrow' if enabled else 'arrow_off'), 10)
        elif control == CC.CC_SpinBox:
            if not (isinstance(widget, QSpinBox) and isinstance(option, QStyleOptionSpinBox)):
                return False
            if option.frame:
                _field(painter, option.rect, color('base'), state & State.State_HasFocus)
            steps = QAbstractSpinBox.StepEnabledFlag
            for sub, points, step in ((SC.SC_SpinBoxUp, UP, steps.StepUpEnabled),
                                      (SC.SC_SpinBoxDown, DOWN, steps.StepDownEnabled)):
                r = self.subControlRect(control, option, sub, widget)
                live = enabled and bool(option.stepEnabled & step)
                if live and option.activeSubControls & sub and state & State.State_MouseOver:
                    _box(painter, r, 3, color('pressed'))
                _chevron(painter, r, points, color('arrow' if live else 'arrow_off'), 8)
        elif control == CC.CC_ScrollBar and isinstance(option, QStyleOptionSlider):
            if option.maximum == option.minimum:
                return True
            handle = self.subControlRect(control, option, SC.SC_ScrollBarSlider, widget)
            over = option.activeSubControls & SC.SC_ScrollBarSlider and state & (State.State_MouseOver | State.State_Sunken)
            _box(painter, handle, 3, color('scroll_hover' if over else 'scroll'))
        elif control == CC.CC_ToolButton and isinstance(option, QStyleOptionToolButton):
            if not state & State.State_AutoRaise:
                return False
            # The theme gives every tool button its edge, raised or not.
            self._button(option, painter, widget)
            super().drawComplexControl(control, option, painter, widget)
        else:
            return False
        return True


def style_names():
    """The Qt styles on this system, for the Theme setting."""
    return list(QStyleFactory.keys())


def style_key(theme):
    """The Qt style a theme runs on: Fusion for TVHplayer, else the style of that name, or None."""
    if theme == THEME_TVHPLAYER:
        return 'Fusion'
    for key in style_names():
        if key.casefold() == str(theme).casefold():
            return key
    return None


def _set_palette(app, palette):
    """The app's palette, for tooltips too.

    Qt gives tooltips a palette of their own, pale yellow with black text,
    which the app's palette does not change: the TVHplayer theme's dark tip
    had black text on it.
    """
    app.setPalette(palette)
    QToolTip.setPalette(palette)


def _apply_colors(app, dark):
    global colors
    colors = DARK if dark else LIGHT
    _set_palette(app, _palette(colors))
    # Labels and lists hold some of the colors themselves.
    for widget in app.allWidgets():
        if widget.property('theme_palette') is not None:
            _dress(widget)
        widget.update()


def _style_palette(c):
    """The palette a Qt style paints from: every role, in every state, from the TVHplayer colors.

    A style left with the desktop's palette paints it only in part: on GNOME
    Breeze and Oxygen got light or dark fills with the wrong shades, and the
    shade grid lines and borders are drawn in was white.
    """
    pal = _palette(c)
    roles = {
        QPalette.ColorRole.BrightText: c['accent'],
        QPalette.ColorRole.LinkVisited: c['link'],
        QPalette.ColorRole.Light: c['base'],
        QPalette.ColorRole.Midlight: c['alt'],
        QPalette.ColorRole.Mid: c['list_edge'],
        QPalette.ColorRole.Dark: c['muted'],
        QPalette.ColorRole.Shadow: c['list_edge'],
    }
    # Qt 6.6 and later.
    if hasattr(QPalette.ColorRole, 'Accent'):
        roles[QPalette.ColorRole.Accent] = c['accent']
    for role, value in roles.items():
        pal.setColor(role, _qcolor(value))
    return pal


def _follow_desktop(app, force=False):
    """Light or dark as the desktop is, or as set; ``force`` applies it again after a change.

    Qt is told the scheme too, which reaches the title bar Qt draws on GNOME.
    The TVHplayer colors follow, drawn by the TVHplayer theme or given to a
    Qt style as its palette.
    """
    global _scheme, colors
    if _mode == SCHEME_DARK:
        scheme = desktop.ColorScheme.Dark
    elif _mode == SCHEME_LIGHT:
        scheme = desktop.ColorScheme.Light
    else:
        scheme = desktop.system_color_scheme(app)
    # Unknown after the first answer is the app's own pin read back: no change.
    if scheme == desktop.ColorScheme.Unknown and _scheme is not None:
        scheme = _scheme
    if scheme == _scheme and not force:
        return
    _scheme = scheme
    hints = app.styleHints()
    # Qt 6.8 and later; older Qt keeps its own idea, and only the TVHplayer colors follow.
    if hasattr(hints, 'setColorScheme'):
        desktop.note_pinned(scheme)
        hints.setColorScheme(scheme)
    # KDE's styles read their scheme only when made, so the style is made again.
    if _kde_color_scheme(app, scheme) and not _active and _style is not None:
        app.setStyle(_style())
    if _active:
        _apply_colors(app, scheme == desktop.ColorScheme.Dark)
    else:
        colors = DARK if scheme == desktop.ColorScheme.Dark else LIGHT
        _set_palette(app, _style_palette(colors))


def _kde_color_scheme(app, scheme):
    """Give KDE's styles the light or dark Breeze color scheme; True if it changed.

    Breeze and Oxygen paint the menu bar and other parts from a KDE color
    scheme, not from Qt's palette, and outside KDE they find none and stay
    light. KDE apps choose one with this property. On KDE, following the
    desktop, the desktop's own scheme stays.
    """
    path = None
    on_kde = 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':')
    if not (on_kde and _mode == SCHEME_SYSTEM) and scheme != desktop.ColorScheme.Unknown:
        name = 'BreezeDark' if scheme == desktop.ColorScheme.Dark else 'BreezeLight'
        found = QStandardPaths.locate(QStandardPaths.StandardLocation.GenericDataLocation,
                                      f'color-schemes/{name}.colors')
        path = found or None
    if app.property('KDE_COLOR_SCHEME_PATH') == path:
        return False
    app.setProperty('KDE_COLOR_SCHEME_PATH', path)
    return True


def set_color_scheme(app, mode):
    """Light or dark as the desktop is (``system``), or always ``light`` or ``dark``, from now on."""
    global _mode
    _mode = mode if mode in (SCHEME_LIGHT, SCHEME_DARK) else SCHEME_SYSTEM
    if not _watching:
        return
    hints = app.styleHints()
    if _mode == SCHEME_SYSTEM and hasattr(hints, 'setColorScheme'):
        # Unpinned, Qt reports the desktop's scheme again where the portal and GTK say nothing.
        desktop.note_pinned(desktop.ColorScheme.Unknown)
        hints.setColorScheme(desktop.ColorScheme.Unknown)
    _follow_desktop(app, force=True)


def apply(app, theme, style_class=ThemeStyle):
    """Use ``theme``, TVHplayer or a Qt style's name, at startup or while the app runs.

    Returns False when there is no such style. Qt sends every widget a
    StyleChange, so widgets that set themselves up for a theme can follow;
    the main window's panes need polish_main_window() again.
    """
    global _active, _style, _default_font, _watching
    key = style_key(theme)
    if key is None:
        return False
    if _default_font is None:
        _default_font = app.font()
    _active = theme == THEME_TVHPLAYER
    if _active:
        app.setFont(_load_fonts() or _default_font)
    else:
        # The style's palette is set by _follow_desktop() below.
        app.setFont(_default_font)
    _style = lambda: style_class(key)
    app.setStyle(_style())
    app.setProperty('tvhplayer_theme', theme)
    _follow_desktop(app, force=True)
    if not _watching:
        _watching = True
        desktop.watch(app, lambda: _follow_desktop(app))
    return True

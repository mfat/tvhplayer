"""Themes: TVHplayer's own look, or a Qt style, light or dark as the desktop is.

The TVHplayer theme is Fusion with a palette and one stylesheet, built from a
light or a dark set of colors. Any other theme is a Qt style used as it is.
Every theme follows the desktop's light or dark setting while the app runs.
Under high contrast the system look stays in charge.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QRectF, QStandardPaths, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QProxyStyle,
    QStyle,
    QStyledItemDelegate,
    QStyleFactory,
    QTableView,
    QTreeView,
)

try:
    from . import system_color_scheme as desktop
    from .core.config import THEME_TVHPLAYER
except ImportError:
    import system_color_scheme as desktop
    from core.config import THEME_TVHPLAYER

LIGHT = {
    'ink': '#232629', 'muted': '#5d6166', 'placeholder': '#8a8d90', 'link': '#1d79b0',
    'window': '#eff0f1', 'base': '#fcfcfc', 'alt': '#f6f7f7', 'read_only': '#f3f4f5',
    'nav': '#e6e8ea', 'strip': '#f6f7f7', 'strip_ink': '#3b3f43',
    'accent': '#3daee9', 'primary': '#2c8fc9', 'primary_edge': '#2478aa', 'primary_hover': '#267fb4',
    'primary_off': '#9fcbe5', 'on_accent': '#ffffff',
    'hover': '#f2f8fc', 'pressed': '#e3f2fb',
    'edge': 'rgba(35,38,41,64)', 'edge_soft': 'rgba(35,38,41,36)', 'menu_edge': 'rgba(35,38,41,51)',
    'rule': 'rgba(35,38,41,31)', 'hairline': 'rgba(35,38,41,26)', 'tint': 'rgba(35,38,41,18)',
    # Solid, unlike the see-through edges: Qt draws each side of a border apart,
    # and a see-through one darkens where the sides meet.
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

STYLESHEET = """
QWidget {{ color: {ink}; }}
QWidget:disabled {{ color: {disabled}; }}
QToolTip {{ background: {tooltip}; color: {tooltip_ink}; border: none; padding: 5px 8px; border-radius: 4px; }}

/* Sizes come from padding, not min-height: a stylesheet min-height replaces a widget's fixed size. */
QPushButton {{
    padding: 4px 14px;
    background: {base}; border: 1px solid {edge}; border-radius: 4px;
}}
QPushButton:hover {{ background: {hover}; border-color: {accent}; }}
QPushButton:pressed {{ background: {pressed}; }}
QPushButton:focus {{ border: 2px solid {accent}; padding: 3px 13px; }}
QPushButton:disabled {{ color: {disabled}; border-color: {edge_soft}; background: {base}; }}
QPushButton[primary="true"] {{ background: {primary}; border-color: {primary_edge}; color: {on_accent}; }}
QPushButton[primary="true"]:hover {{ background: {primary_hover}; }}
QPushButton[primary="true"]:disabled {{ background: {primary_off}; border-color: {primary_off}; color: {on_accent}; }}

QLineEdit, QComboBox, QSpinBox {{
    padding: 4px 8px;
    background: {base}; border: 1px solid {edge}; border-radius: 4px;
    selection-background-color: {accent}; selection-color: {on_accent};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {accent}; padding: 3px 7px; }}
QLineEdit:read-only {{ background: {read_only}; }}
QLineEdit[mono="true"] {{ font-family: "Noto Sans Mono", "DejaVu Sans Mono", monospace; }}
QComboBox QAbstractItemView {{
    background: {base}; border: 1px solid {edge}; border-radius: 4px;
    selection-background-color: {selected}; selection-color: {ink}; outline: 0;
}}

QProgressBar[textVisible="false"] {{ max-height: 4px; min-height: 4px; border: none; border-radius: 2px; background: {track}; }}
QProgressBar[textVisible="false"]::chunk {{ background: {accent}; border-radius: 2px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {scroll}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {scroll}; border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {scroll_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* Main window */
QMenuBar {{ background: {window}; border-bottom: 1px solid {rule}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {tint}; }}
QMenu {{ background: {base}; border: 1px solid {menu_edge}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {selected}; color: {ink}; }}
QMenu::separator {{ height: 1px; background: {hairline}; margin: 4px 8px; }}
QSplitter::handle {{ background: transparent; }}
QToolButton {{ padding: 4px 8px; background: {base}; border: 1px solid {edge}; border-radius: 4px; }}
QToolButton:hover {{ border-color: {accent}; background: {hover}; }}
QToolButton:focus {{ border: 2px solid {accent}; padding: 3px 7px; }}
/* Padding keeps the square header and rows inside the rounded border. Selected rows
   are drawn by RowStyle, which knows the first and last visible column. */
QTableView, QTreeView, QListView {{
    background: {base}; border: 1px solid {list_edge}; border-radius: 6px; padding: 4px;
    gridline-color: transparent; selection-background-color: transparent; selection-color: {selected_ink};
    alternate-background-color: {alt}; outline: 0;
}}
QComboBox QAbstractItemView::item {{ padding: 6px 12px; }}
QComboBox QAbstractItemView::item:selected {{ background: {selected}; color: {ink}; border-radius: 4px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {muted}; font-weight: 600; padding: 6px 8px;
    border: none; border-bottom: 1px solid {edge};
}}
QStatusBar {{ background: {window}; border-top: 1px solid {rule}; color: {muted}; }}
QStatusBar::item {{ border: none; }}

/* Settings building blocks (settings_widgets.py) */
QLabel#pageTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#pageIntro {{ color: {muted}; }}
QLabel#groupTitle {{ font-weight: 600; }}
QLabel#rowTitle {{ font-size: 10.5pt; }}
QLabel#rowDesc {{ color: {muted}; font-size: 9pt; }}
QLabel#rowDesc:disabled {{ color: {disabled_soft}; }}
QFrame#groupCard {{ background: {base}; border: 1px solid {edge_soft}; border-radius: 8px; }}
QFrame#rowSeparator {{ background: {hairline}; border: none; }}
QFrame#statusStrip {{
    background: {strip}; border: none; border-top: 1px solid {hairline};
    border-bottom-left-radius: 7px; border-bottom-right-radius: 7px;
}}
QLabel#statusText {{ color: {strip_ink}; font-size: 9.5pt; }}
QListWidget#settingsNav {{
    background: {nav}; border: none; border-right: 1px solid {rule};
    padding: 14px 10px; outline: 0;
}}
QFrame#dialogFooter {{ background: {window}; border: none; border-top: 1px solid {rule}; }}
QLabel#footerNote {{ color: {muted}; font-size: 9.5pt; }}
QWidget#settingsPage {{ background: {window}; }}
"""


# Styling the arrow buttons turns off Qt's own arrows, so these rules come with their images.
# The @name@ tokens are replaced by the image files.
ARROWS = """
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url(@down@); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url(@down_disabled@); }
QSpinBox { padding-right: 22px; }
QSpinBox:focus { padding-right: 21px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 20px; border: none; background: transparent; }
QSpinBox::up-button { subcontrol-position: top right; margin: 3px 2px 0 0; }
QSpinBox::down-button { subcontrol-position: bottom right; margin: 0 2px 3px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: @hover@; border-radius: 3px; }
QSpinBox::up-arrow { image: url(@up@); width: 8px; height: 8px; }
QSpinBox::down-arrow { image: url(@down@); width: 8px; height: 8px; }
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off { image: url(@up_disabled@); }
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off { image: url(@down_disabled@); }
"""
CHEVRON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
DOWN = 'M2 3.5 5 6.5 8 3.5'
UP = 'M2 6.5 5 3.5 8 6.5'

# The colors in use, and whether the TVHplayer theme is on.
colors = LIGHT
_active = False


def is_active():
    return _active


def _arrow_rules(c, dark):
    """Qt stylesheets load images only from files or resources, so the arrows are written to the cache."""
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / 'theme'
    suffix = '-dark' if dark else ''
    rules = ARROWS.replace('@hover@', c['pressed'])
    images = {
        'down': (DOWN, c['arrow']),
        'up': (UP, c['arrow']),
        'down_disabled': (DOWN, c['arrow_off']),
        'up_disabled': (UP, c['arrow_off']),
    }
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, (path, color) in images.items():
            file = folder / f'{name}{suffix}.svg'
            svg = CHEVRON.format(path=path, color=color)
            if not file.exists() or file.read_text() != svg:
                file.write_text(svg)
            rules = rules.replace(f'@{name}@', file.as_posix())
    except OSError:
        # Without the images the base style draws the arrows.
        return ''
    return rules


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
    fonts = Path(__file__).resolve().parent / 'fonts'
    if fonts.is_dir():
        for file in fonts.glob('*.ttf'):
            QFontDatabase.addApplicationFont(str(file))
    if 'Noto Sans' in QFontDatabase.families():
        return QFont('Noto Sans', 10)
    return None


def polish_main_window(window):
    """Flatten the raised side panes and hide the splitter handle. Call after the UI is built."""
    from PyQt6.QtWidgets import QFrame
    for name in ('left_pane', 'right_pane', 'tasks_pane'):
        pane = getattr(window, name, None)
        if pane is not None:
            pane.setFrameStyle(QFrame.Shape.NoFrame)
            pane.setObjectName(name)
    splitter = getattr(window, 'splitter', None)
    if splitter is not None:
        # Invisible, but wide enough to grab.
        splitter.setHandleWidth(6)


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


class RowStyle(QProxyStyle):
    """With the TVHplayer theme on, a selected row is one tint rounded at its two ends.

    Style sheet ::item:first and :last cannot do it: a table counts hidden columns,
    so with the first column hidden no visible cell starts the row.
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        if (_active and element == QStyle.PrimitiveElement.PE_PanelItemViewItem
                and option.state & QStyle.StateFlag.State_Selected and isinstance(widget, QAbstractItemView)):
            first, last = _row_ends(widget, option.index)
            rect = QRectF(option.rect)
            # The rounded shape runs past the cell on a side that joins another cell, then is cut off.
            if not first:
                rect.setLeft(rect.left() - 8)
            if not last:
                rect.setRight(rect.right() + 8)
            painter.save()
            painter.setClipRect(option.rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color('selected'))
            painter.drawRoundedRect(rect, 4, 4)
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


class _ThemePolish(QObject):
    """Widget settings a style sheet cannot make, applied as each widget is polished."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Polish:
            if isinstance(obj, QTableView):
                # The theme hides grid lines, which left a gap between cells.
                obj.setShowGrid(False)
            elif isinstance(obj, QComboBox) and not isinstance(obj.itemDelegate(), QStyledItemDelegate):
                # Qt's own popup delegate draws items as menu items and ignores ::item rules.
                obj.setItemDelegate(QStyledItemDelegate(obj))
        return False


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


def _apply_colors(app, dark):
    global colors
    colors = DARK if dark else LIGHT
    app.setPalette(_palette(colors))
    app.setStyleSheet(STYLESHEET.format(**colors) + _arrow_rules(colors, dark))


def follow_desktop(app, use_theme):
    """Light or dark as the desktop is, now and whenever it changes.

    Qt is told the scheme too, which reaches Qt styles and the title bar Qt
    draws on GNOME. With ``use_theme`` the TVHplayer colors follow as well.
    """
    global _active
    state = {'scheme': None}

    schemes = desktop.ColorScheme

    def update():
        scheme = desktop.system_color_scheme(app)
        # Unknown after the first answer is the app's own pin read back: no change.
        if scheme == state['scheme'] or (scheme == schemes.Unknown and state['scheme'] is not None):
            return
        state['scheme'] = scheme
        hints = app.styleHints()
        # Qt 6.8 and later; older Qt keeps its own idea, and only the TVHplayer colors follow.
        if hasattr(hints, 'setColorScheme'):
            desktop.note_pinned(scheme)
            hints.setColorScheme(scheme)
        if use_theme:
            _apply_colors(app, scheme == schemes.Dark)

    if use_theme:
        _active = True
        app.installEventFilter(_ThemePolish(app))
        font = _load_fonts()
        if font is not None:
            app.setFont(font)
    update()
    desktop.watch(app, update)

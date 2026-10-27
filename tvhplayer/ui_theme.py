"""App-wide look: Fusion base, a light palette, Noto Sans, and one stylesheet.

Call ``apply_theme(app)`` right after the QApplication is created. Skip it when
the user asked for high contrast, so the system theme stays in charge.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QRectF, QStandardPaths
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QProxyStyle,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QTreeView,
)

INK = '#232629'
MUTED = '#5d6166'
WINDOW = '#eff0f1'
BASE = '#fcfcfc'
ACCENT = '#3daee9'
ACCENT_STRONG = '#2c8fc9'

STYLESHEET = f"""
QWidget {{ color: {INK}; }}
QWidget:disabled {{ color: rgba(35,38,41,110); }}
QToolTip {{ background: {INK}; color: white; border: none; padding: 5px 8px; border-radius: 4px; }}

/* Sizes come from padding, not min-height: a stylesheet min-height replaces a widget's fixed size. */
QPushButton {{
    padding: 4px 14px;
    background: {BASE}; border: 1px solid rgba(35,38,41,64); border-radius: 4px;
}}
QPushButton:hover {{ background: #f2f8fc; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #e3f2fb; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; padding: 3px 13px; }}
QPushButton:disabled {{ color: rgba(35,38,41,110); border-color: rgba(35,38,41,36); background: {BASE}; }}
QPushButton[primary="true"] {{ background: {ACCENT_STRONG}; border-color: #2478aa; color: white; }}
QPushButton[primary="true"]:hover {{ background: #267fb4; }}
QPushButton[primary="true"]:disabled {{ background: #9fcbe5; border-color: #9fcbe5; color: white; }}

QLineEdit, QComboBox, QSpinBox {{
    padding: 4px 8px;
    background: {BASE}; border: 1px solid rgba(35,38,41,64); border-radius: 4px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {ACCENT}; padding: 3px 7px; }}
QLineEdit:read-only {{ background: #f3f4f5; }}
QLineEdit[mono="true"] {{ font-family: "Noto Sans Mono", "DejaVu Sans Mono", monospace; }}
QComboBox QAbstractItemView {{
    background: {BASE}; border: 1px solid rgba(35,38,41,64); border-radius: 4px;
    selection-background-color: rgba(61,174,233,51); selection-color: {INK}; outline: 0;
}}

QProgressBar[textVisible="false"] {{ max-height: 4px; min-height: 4px; border: none; border-radius: 2px; background: rgba(35,38,41,31); }}
QProgressBar[textVisible="false"]::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(35,38,41,70); border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(35,38,41,110); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

/* Main window */
QMenuBar {{ background: {WINDOW}; border-bottom: 1px solid rgba(35,38,41,31); padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: rgba(35,38,41,18); }}
QMenu {{ background: {BASE}; border: 1px solid rgba(35,38,41,51); border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(61,174,233,51); color: {INK}; }}
QMenu::separator {{ height: 1px; background: rgba(35,38,41,26); margin: 4px 8px; }}
QSplitter::handle {{ background: rgba(35,38,41,31); }}
QSplitter::handle:horizontal {{ width: 1px; }}
QToolButton {{ padding: 4px 8px; background: {BASE}; border: 1px solid rgba(35,38,41,64); border-radius: 4px; }}
QToolButton:hover {{ border-color: {ACCENT}; background: #f2f8fc; }}
QToolButton:focus {{ border: 2px solid {ACCENT}; padding: 3px 7px; }}
/* Padding keeps the square header and rows inside the rounded border. Selected rows
   are drawn by RowStyle, which knows the first and last visible column. */
QTableView, QTreeView, QListView {{
    background: {BASE}; border: 1px solid #bcbdbf; border-radius: 6px; padding: 4px;
    gridline-color: transparent; selection-background-color: transparent; selection-color: #124a6a;
    alternate-background-color: #f6f7f7; outline: 0;
}}
QComboBox QAbstractItemView::item {{ padding: 6px 12px; }}
QComboBox QAbstractItemView::item:selected {{ background: rgba(61,174,233,51); color: {INK}; border-radius: 4px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {MUTED}; font-weight: 600; padding: 6px 8px;
    border: none; border-bottom: 1px solid rgba(35,38,41,64);
}}
QStatusBar {{ background: {WINDOW}; border-top: 1px solid rgba(35,38,41,31); color: {MUTED}; }}
QStatusBar::item {{ border: none; }}

/* Settings building blocks (settings_widgets.py) */
QLabel#pageTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#pageIntro {{ color: {MUTED}; }}
QLabel#groupTitle {{ font-weight: 600; }}
QLabel#rowTitle {{ font-size: 10.5pt; }}
QLabel#rowDesc {{ color: {MUTED}; font-size: 9pt; }}
QLabel#rowDesc:disabled {{ color: rgba(35,38,41,90); }}
QFrame#groupCard {{ background: {BASE}; border: 1px solid rgba(35,38,41,36); border-radius: 8px; }}
QFrame#rowSeparator {{ background: rgba(35,38,41,26); border: none; }}
QFrame#statusStrip {{
    background: #f6f7f7; border: none; border-top: 1px solid rgba(35,38,41,26);
    border-bottom-left-radius: 7px; border-bottom-right-radius: 7px;
}}
QLabel#statusText {{ color: #3b3f43; font-size: 9.5pt; }}
QListWidget#settingsNav {{
    background: #e6e8ea; border: none; border-right: 1px solid rgba(35,38,41,31);
    padding: 14px 10px; outline: 0;
}}
QFrame#dialogFooter {{ background: {WINDOW}; border: none; border-top: 1px solid rgba(35,38,41,31); }}
QLabel#footerNote {{ color: {MUTED}; font-size: 9.5pt; }}
QWidget#settingsPage {{ background: {WINDOW}; }}
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
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e3f2fb; border-radius: 3px; }
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
CHEVRONS = {
    'down': (DOWN, MUTED),
    'up': (UP, MUTED),
    'down_disabled': (DOWN, '#b8babc'),
    'up_disabled': (UP, '#b8babc'),
}


def _arrow_rules():
    """Qt stylesheets load images only from files or resources, so the arrows are written to the cache."""
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / 'theme'
    rules = ARROWS
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, (path, color) in CHEVRONS.items():
            file = folder / f'{name}.svg'
            svg = CHEVRON.format(path=path, color=color)
            if not file.exists() or file.read_text() != svg:
                file.write_text(svg)
            rules = rules.replace(f'@{name}@', file.as_posix())
    except OSError:
        # Without the images the base style draws the arrows.
        return ''
    return rules


def _palette():
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: WINDOW,
        QPalette.ColorRole.WindowText: INK,
        QPalette.ColorRole.Base: BASE,
        QPalette.ColorRole.AlternateBase: '#f3f4f5',
        QPalette.ColorRole.Text: INK,
        QPalette.ColorRole.Button: BASE,
        QPalette.ColorRole.ButtonText: INK,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: '#ffffff',
        QPalette.ColorRole.ToolTipBase: INK,
        QPalette.ColorRole.ToolTipText: '#ffffff',
        QPalette.ColorRole.PlaceholderText: '#8a8d90',
        QPalette.ColorRole.Link: '#1d79b0',
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(35, 38, 41, 110))
    return pal


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
    """Flatten the raised side panes and give the splitter a hairline. Call after the UI is built."""
    from PyQt6.QtWidgets import QFrame
    for name in ('left_pane', 'right_pane'):
        pane = getattr(window, name, None)
        if pane is not None:
            pane.setFrameStyle(QFrame.Shape.NoFrame)
            pane.setObjectName(name)
    splitter = getattr(window, 'splitter', None)
    if splitter is not None:
        splitter.setHandleWidth(1)


SELECTED_ROW = QColor(61, 174, 233, 51)
_rounded_rows = False


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
    """With the theme on, a selected row is one tint rounded at its two ends, as in the settings sidebar.

    Style sheet ::item:first and :last cannot do it: a table counts hidden columns,
    so with the first column hidden no visible cell starts the row.
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        if (_rounded_rows and element == QStyle.PrimitiveElement.PE_PanelItemViewItem
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
            painter.setPen(QColor(0, 0, 0, 0))
            painter.setBrush(SELECTED_ROW)
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


def apply_theme(app):
    global _rounded_rows
    _rounded_rows = True
    app.installEventFilter(_ThemePolish(app))
    app.setPalette(_palette())
    font = _load_fonts()
    if font is not None:
        app.setFont(font)
    app.setStyleSheet(STYLESHEET + _arrow_rules())

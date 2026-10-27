from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication


def _apply(monkeypatch, answers, theme, mode='system'):
    """Apply ``theme`` with the desktop's answers in turn; return the desktop's callback and what was applied."""
    from tvhplayer import ui_theme

    app = QApplication.instance()
    callbacks = []
    applied = []
    pinned = []
    styles = []
    answers = iter(answers)
    monkeypatch.setattr(ui_theme.desktop, 'system_color_scheme', lambda _app: next(answers))
    monkeypatch.setattr(ui_theme.desktop, 'watch', lambda _app, callback: callbacks.append(callback))
    monkeypatch.setattr(ui_theme, '_apply_colors', lambda _app, dark: applied.append(dark))
    monkeypatch.setattr(ui_theme, '_load_fonts', lambda: None)
    monkeypatch.setattr(ui_theme, '_ThemePolish', lambda _app: _NoFilter())
    monkeypatch.setattr(app.styleHints(), 'setColorScheme', pinned.append, raising=False)
    monkeypatch.setattr(app, 'setStyle', lambda style: styles.append(style.baseStyle().name()))
    for name, value in (('_active', False), ('_scheme', None), ('_watching', False),
                        ('_polish', None), ('_default_font', None), ('_mode', mode)):
        monkeypatch.setattr(ui_theme, name, value)
    monkeypatch.setattr(app, 'setProperty', lambda *_args: True)
    monkeypatch.setattr(app, 'setPalette', lambda _palette: None)
    assert ui_theme.apply(app, theme)
    return (callbacks[0] if callbacks else None), applied, pinned, styles


class _NoFilter(QObject):
    def eventFilter(self, *_args):
        return False

    def polish(self, _widget):
        pass


def test_tvhplayer_theme_follows_the_desktop_between_light_and_dark(monkeypatch):
    dark, light, unknown = Qt.ColorScheme.Dark, Qt.ColorScheme.Light, Qt.ColorScheme.Unknown
    changed, applied, pinned, styles = _apply(monkeypatch, [dark, dark, light, unknown], 'TVHplayer')
    assert styles == ['fusion']
    assert applied == [True]
    assert pinned == [dark]
    changed()  # Qt echoing the pin: same scheme, nothing to do.
    changed()
    assert applied == [True, False]
    changed()  # No answer any more: keep what is shown.
    assert applied == [True, False]
    assert pinned == [dark, light]


def test_a_qt_style_follows_the_desktop_without_the_tvhplayer_colors(monkeypatch):
    changed, applied, pinned, styles = _apply(monkeypatch, [Qt.ColorScheme.Dark], 'Fusion')
    assert applied == []
    assert pinned == [Qt.ColorScheme.Dark]


def test_a_theme_change_while_running_takes_the_tvhplayer_look_off_and_back(monkeypatch):
    from tvhplayer import ui_theme

    dark = Qt.ColorScheme.Dark
    _changed, applied, _pinned, styles = _apply(monkeypatch, [dark, dark, dark], 'TVHplayer')
    app = QApplication.instance()
    assert ui_theme.is_active() and ui_theme._polish is not None
    sheets = []
    monkeypatch.setattr(app, 'setStyleSheet', sheets.append)
    assert ui_theme.apply(app, 'Fusion')
    assert not ui_theme.is_active() and ui_theme._polish is None
    assert sheets == ['']
    assert ui_theme.apply(app, 'TVHplayer')
    assert ui_theme.is_active() and ui_theme._polish is not None
    # Each change applies the desktop's scheme again; only TVHplayer brings its colors.
    assert applied == [True, True]
    assert len(styles) == 3


def test_an_unknown_theme_changes_nothing(monkeypatch):
    from tvhplayer import ui_theme

    assert not ui_theme.apply(QApplication.instance(), 'No Such Style')


def test_style_key_finds_qt_styles_and_falls_back_for_unknown_names():
    from tvhplayer.ui_theme import style_key

    assert style_key('TVHplayer') == 'Fusion'
    assert style_key('fusion') == 'Fusion'
    assert style_key('No Such Style') is None


def test_both_color_sets_fill_the_stylesheet():
    from tvhplayer.ui_theme import DARK, LIGHT, STYLESHEET

    assert LIGHT.keys() == DARK.keys()
    for colors in (LIGHT, DARK):
        sheet = STYLESHEET.format(**colors)
        assert '{' in sheet and '{ink}' not in sheet


def test_tables_get_their_grid_back_with_a_qt_style(qapp):
    from PyQt6.QtWidgets import QTableWidget
    from tvhplayer import ui_theme

    table = QTableWidget(2, 2)
    ui_theme._ThemePolish.polish(table)
    assert not table.showGrid()
    ui_theme._restore_grids(qapp)
    assert table.showGrid()


def test_light_or_dark_can_be_set_over_the_desktop_and_given_back(monkeypatch):
    from tvhplayer import ui_theme

    dark, light = Qt.ColorScheme.Dark, Qt.ColorScheme.Light
    changed, applied, pinned, _styles = _apply(monkeypatch, [dark, dark, dark], 'TVHplayer')
    app = QApplication.instance()
    ui_theme.set_color_scheme(app, 'light')
    assert applied == [True, False]
    changed()  # The desktop changing has no say while Light is set.
    assert applied == [True, False]
    ui_theme.set_color_scheme(app, 'system')
    assert applied == [True, False, True]
    # Following the desktop again first takes off the app's own pin.
    assert pinned == [dark, light, Qt.ColorScheme.Unknown, dark]


def test_light_or_dark_set_before_start_is_used_from_the_first_paint(monkeypatch):
    _changed, applied, pinned, _styles = _apply(monkeypatch, [Qt.ColorScheme.Light], 'TVHplayer', mode='dark')
    assert applied == [True]
    assert pinned == [Qt.ColorScheme.Dark]

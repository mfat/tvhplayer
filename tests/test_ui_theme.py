from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication


def _apply(monkeypatch, answers, theme, mode='system', palettes=None):
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
    monkeypatch.setattr(ui_theme, '_kde_color_scheme', lambda _app, _scheme: False)
    monkeypatch.setattr(app.styleHints(), 'setColorScheme', pinned.append, raising=False)
    monkeypatch.setattr(app, 'setStyle', lambda style: styles.append(style.baseStyle().name()))
    for name, value in (('_active', False), ('_scheme', None), ('_watching', False),
                        ('_default_font', None), ('_mode', mode)):
        monkeypatch.setattr(ui_theme, name, value)
    monkeypatch.setattr(app, 'setProperty', lambda *_args: True)
    monkeypatch.setattr(app, 'setPalette', (palettes if palettes is not None else []).append)
    assert ui_theme.apply(app, theme)
    return (callbacks[0] if callbacks else None), applied, pinned, styles


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


def test_a_qt_style_paints_the_tvhplayer_colors_in_every_role(monkeypatch):
    from PyQt6.QtGui import QPalette
    from tvhplayer import ui_theme

    palettes = []
    changed, applied, pinned, styles = _apply(monkeypatch, [Qt.ColorScheme.Dark], 'Fusion', palettes=palettes)
    assert applied == []
    assert pinned == [Qt.ColorScheme.Dark]
    # Not the desktop's palette, which on GNOME has a white Mid for grid lines and borders.
    for group in ui_theme.ALL:
        assert palettes[-1].color(group, QPalette.ColorRole.Window) == ui_theme._qcolor(ui_theme.DARK['window'])
        assert palettes[-1].color(group, QPalette.ColorRole.Mid) == ui_theme._qcolor(ui_theme.DARK['list_edge'])
        assert palettes[-1].color(group, QPalette.ColorRole.Shadow) == ui_theme._qcolor(ui_theme.DARK['list_edge'])


def test_a_theme_change_while_running_takes_the_tvhplayer_look_off_and_back(monkeypatch):
    from tvhplayer import ui_theme

    dark = Qt.ColorScheme.Dark
    app = QApplication.instance()
    sheets = []
    monkeypatch.setattr(app, 'setStyleSheet', sheets.append)
    _changed, applied, _pinned, styles = _apply(monkeypatch, [dark, dark, dark], 'TVHplayer')
    assert ui_theme.is_active()
    assert ui_theme.apply(app, 'Fusion')
    assert not ui_theme.is_active()
    assert ui_theme.apply(app, 'TVHplayer')
    assert ui_theme.is_active()
    # The look is drawn by the style: Qt does not support a style sheet over a style of the app's own.
    assert sheets == []
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


def test_both_color_sets_have_every_color():
    from tvhplayer.ui_theme import DARK, LABELS, LIGHT, _qcolor

    assert LIGHT.keys() == DARK.keys()
    for colors in (LIGHT, DARK):
        assert all(_qcolor(value).isValid() for value in colors.values())
    for _size, _weight, ink, ink_off in LABELS.values():
        assert {ink, ink_off} - {None} <= LIGHT.keys()


def test_default_accent_and_window_color_keep_the_tvhplayer_colors():
    from tvhplayer.ui_theme import DARK, LIGHT, compose

    assert compose(False) == LIGHT
    assert compose(True) == DARK
    assert compose(True, 'No such accent', 'No such window') == DARK


def test_every_accent_and_window_color_gives_every_color(qapp):
    from tvhplayer.ui_theme import LIGHT, _qcolor, accent_choices, compose, window_color_choices

    for accent, _label in accent_choices():
        for window, _label in window_color_choices():
            for dark in (False, True):
                colors = compose(dark, accent, window)
                assert colors.keys() == LIGHT.keys()
                assert all(_qcolor(value).isValid() for value in colors.values()), (accent, window, dark)


def test_accent_reaches_every_theme_but_window_color_only_the_tvhplayer_theme(qapp, monkeypatch):
    from PyQt6.QtGui import QPalette
    from tvhplayer import ui_theme

    palettes = []
    monkeypatch.setattr(ui_theme, '_set_palette', lambda _app, palette: palettes.append(palette))
    monkeypatch.setattr(ui_theme, '_scheme', Qt.ColorScheme.Dark)
    monkeypatch.setattr(ui_theme, '_watching', True)
    monkeypatch.setattr(ui_theme, '_accent', ui_theme.ACCENT_DEFAULT)
    monkeypatch.setattr(ui_theme, '_window', ui_theme.WINDOW_DEFAULT)
    monkeypatch.setattr(ui_theme, 'colors', ui_theme.DARK)
    window = QPalette.ColorRole.Window
    highlight = QPalette.ColorRole.Highlight

    monkeypatch.setattr(ui_theme, '_active', False)
    ui_theme.set_window_color(qapp, 'cream')
    ui_theme.set_accent(qapp, 'Sage')
    assert palettes[-1].color(window) == ui_theme._qcolor(ui_theme.DARK['window'])
    assert palettes[-1].color(highlight) == QColor(ui_theme.ACCENTS['sage'][3])

    monkeypatch.setattr(ui_theme, '_active', True)
    ui_theme.set_window_color(qapp, 'cream')
    assert palettes[-1].color(window) == QColor(ui_theme.WINDOW_COLORS['cream'][2][0])
    assert palettes[-1].color(highlight) == QColor(ui_theme.ACCENTS['sage'][3])
    assert ui_theme.color('window') == QColor(ui_theme.WINDOW_COLORS['cream'][2][0])


def test_tables_get_their_grid_back_with_a_qt_style(qapp, monkeypatch):
    from PyQt6.QtWidgets import QTableWidget
    from tvhplayer import ui_theme

    style = ui_theme.ThemeStyle('Fusion')
    table = QTableWidget(2, 2)
    monkeypatch.setattr(ui_theme, '_active', True)
    style.polish(table)
    assert not table.showGrid()
    monkeypatch.setattr(ui_theme, '_active', False)
    style.unpolish(table)
    assert table.showGrid()


def test_dropdowns_get_the_style_s_own_list_back_after_the_tvhplayer_theme(qapp, monkeypatch):
    from PyQt6.QtWidgets import QComboBox
    from tvhplayer import ui_theme

    combo = QComboBox()
    native = combo.itemDelegate()
    style = ui_theme.ThemeStyle('Fusion')
    monkeypatch.setattr(ui_theme, '_active', True)
    style.polish(combo)
    assert combo.itemDelegate() is not native
    style.polish(combo)  # Polished again, as after a light or dark change: still the same one.
    ours = combo.itemDelegate()
    style.polish(combo)
    assert combo.itemDelegate() is ours
    monkeypatch.setattr(ui_theme, '_active', False)
    style.unpolish(combo)
    assert combo.itemDelegate() is native


def test_labels_take_the_new_colors_after_a_light_or_dark_change(qapp, monkeypatch):
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QLabel
    from tvhplayer import ui_theme

    label = QLabel('A description')
    label.setObjectName('rowDesc')
    style = ui_theme.ThemeStyle('Fusion')
    palette = qapp.palette()
    monkeypatch.setattr(ui_theme, '_active', True)
    monkeypatch.setattr(ui_theme, 'colors', ui_theme.LIGHT)
    try:
        style.polish(label)
        ink = QPalette.ColorRole.WindowText
        assert label.palette().color(ink) == ui_theme._qcolor(ui_theme.LIGHT['muted'])
        assert label.font().pointSizeF() == 9
        ui_theme._apply_colors(qapp, True)
        assert label.palette().color(ink) == ui_theme._qcolor(ui_theme.DARK['muted'])
        assert qapp.styleSheet() == ''
        monkeypatch.setattr(ui_theme, '_active', False)
        style.unpolish(label)
        assert label.palette().color(ink) == qapp.palette().color(ink)
    finally:
        qapp.setPalette(palette)


def test_an_option_wrapped_as_another_class_is_drawn_as_its_own(qapp):
    from PyQt6 import sip
    from PyQt6.QtWidgets import QStyleOption, QStyleOptionFrame, QStyleOptionViewItem
    from tvhplayer import ui_theme

    item = QStyleOptionViewItem()
    stale = sip.cast(sip.cast(item, QStyleOption), QStyleOptionFrame)
    assert type(ui_theme._typed(stale)) is QStyleOptionViewItem
    assert ui_theme._typed(item) is item


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


def test_kde_styles_get_a_dark_scheme_outside_kde_but_kde_keeps_its_own(qapp, monkeypatch):
    from tvhplayer import ui_theme

    monkeypatch.setattr(ui_theme.QStandardPaths, 'locate', lambda _where, name: f'/schemes/{name}')
    monkeypatch.setattr(qapp, 'setProperty', lambda _name, value: setattr(qapp, '_kde', value) or True)
    monkeypatch.setattr(qapp, 'property', lambda _name: getattr(qapp, '_kde', None))
    monkeypatch.setattr(qapp, '_kde', None, raising=False)
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'ubuntu:GNOME')
    monkeypatch.setattr(ui_theme, '_mode', 'system')
    assert ui_theme._kde_color_scheme(qapp, Qt.ColorScheme.Dark)
    assert qapp._kde == '/schemes/color-schemes/BreezeDark.colors'
    assert not ui_theme._kde_color_scheme(qapp, Qt.ColorScheme.Dark)  # No change, no new style.
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    assert ui_theme._kde_color_scheme(qapp, Qt.ColorScheme.Dark)
    assert qapp._kde is None
    monkeypatch.setattr(ui_theme, '_mode', 'light')
    ui_theme._kde_color_scheme(qapp, Qt.ColorScheme.Light)
    assert qapp._kde == '/schemes/color-schemes/BreezeLight.colors'


def test_tvhplayer_dropdowns_show_every_item_without_scrolling(qapp, monkeypatch):
    from PyQt6.QtWidgets import QComboBox, QStyle
    from tvhplayer import ui_theme

    style = ui_theme.ThemeStyle('Fusion')
    monkeypatch.setattr(ui_theme, '_active', True)
    assert style.styleHint(QStyle.StyleHint.SH_ComboBox_Popup, None, QComboBox()) == 0
    monkeypatch.setattr(ui_theme, '_active', False)
    assert style.styleHint(QStyle.StyleHint.SH_ComboBox_Popup, None, QComboBox()) == \
        ui_theme.QStyleFactory.create('Fusion').styleHint(QStyle.StyleHint.SH_ComboBox_Popup, None, QComboBox())


def test_tooltips_take_the_app_palette_after_qt_gives_them_the_desktops(qapp):
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QLabel, QToolTip
    from tvhplayer import ui_theme

    text = QPalette.ColorRole.ToolTipText
    app_palette, tip_palette = qapp.palette(), QToolTip.palette()
    ours = QPalette(app_palette)
    ours.setColor(text, QColor('#fcfcfc'))
    # At startup Qt's theme change gives tooltips the desktop's palette again, black text on GNOME.
    desktops = QPalette(tip_palette)
    desktops.setColor(text, QColor('#000000'))
    try:
        qapp.setPalette(ours)
        QToolTip.setPalette(desktops)
        tip = QLabel(None, Qt.WindowType.ToolTip)
        tip.setPalette(QToolTip.palette())
        ui_theme.ThemeStyle('Fusion').polish(tip)
        assert tip.palette().color(text) == QColor('#fcfcfc')
    finally:
        qapp.setPalette(app_palette)
        QToolTip.setPalette(tip_palette)

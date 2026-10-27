from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication


def _follow(monkeypatch, answers, use_theme):
    """Run follow_desktop with the desktop's answers in turn; return what was applied."""
    from tvhplayer import ui_theme

    app = QApplication.instance()
    callbacks = []
    applied = []
    pinned = []
    answers = iter(answers)
    monkeypatch.setattr(ui_theme.desktop, 'system_color_scheme', lambda _app: next(answers))
    monkeypatch.setattr(ui_theme.desktop, 'watch', lambda _app, callback: callbacks.append(callback))
    monkeypatch.setattr(ui_theme, '_apply_colors', lambda _app, dark: applied.append(dark))
    monkeypatch.setattr(ui_theme, '_load_fonts', lambda: None)
    monkeypatch.setattr(ui_theme, '_ThemePolish', lambda _app: _NoFilter())
    monkeypatch.setattr(app.styleHints(), 'setColorScheme', pinned.append, raising=False)
    monkeypatch.setattr(ui_theme, '_active', False)
    ui_theme.follow_desktop(app, use_theme=use_theme)
    return callbacks[0], applied, pinned


class _NoFilter(QObject):
    def eventFilter(self, *_args):
        return False


def test_tvhplayer_theme_follows_the_desktop_between_light_and_dark(monkeypatch):
    dark, light, unknown = Qt.ColorScheme.Dark, Qt.ColorScheme.Light, Qt.ColorScheme.Unknown
    changed, applied, pinned = _follow(monkeypatch, [dark, dark, light, unknown], use_theme=True)
    assert applied == [True]
    assert pinned == [dark]
    changed()  # Qt echoing the pin: same scheme, nothing to do.
    changed()
    assert applied == [True, False]
    changed()  # No answer any more: keep what is shown.
    assert applied == [True, False]
    assert pinned == [dark, light]


def test_a_qt_style_follows_the_desktop_without_the_tvhplayer_colors(monkeypatch):
    changed, applied, pinned = _follow(monkeypatch, [Qt.ColorScheme.Dark], use_theme=False)
    assert applied == []
    assert pinned == [Qt.ColorScheme.Dark]


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

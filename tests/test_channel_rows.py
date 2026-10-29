import os
import time


def _app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _view(channels):
    from tvhplayer.channel_view import ChannelDelegate, ChannelTableModel, ChannelTableView

    app = _app()
    model = ChannelTableModel()
    model.set_channels(channels)
    view = ChannelTableView()
    view.setModel(model)
    delegate = ChannelDelegate(view)
    view.setItemDelegate(delegate)
    view.verticalHeader().setVisible(False)
    view.resize(400, 300)
    return app, model, view, delegate


def test_rows_grow_with_density_and_a_second_line():
    from tvhplayer.channel_view import row_height

    heights = [row_height(density, 18) for density in ('compact', 'comfortable', 'spacious')]
    assert heights == sorted(heights) and len(set(heights)) == 3
    assert row_height('comfortable', 18, two_line=True) > row_height('comfortable', 18)
    # Unknown sizes fall back to Comfortable.
    assert row_height('huge', 18) == row_height('comfortable', 18)


def test_row_style_sets_row_height_and_logo_size():
    from tvhplayer.channel_view import DENSITY_STYLE, row_height
    from tvhplayer.core.models import Channel

    app, model, view, _ = _view([Channel(uuid='a', name='A', number=1)])
    spacing = view.fontMetrics().lineSpacing()
    for density in ('compact', 'spacious', 'comfortable'):
        view.set_row_style(density, False)
        assert view.verticalHeader().defaultSectionSize() == row_height(density, spacing)
        assert view.rowHeight(0) == row_height(density, spacing)
        assert view.iconSize() == DENSITY_STYLE[density][0]
    view.set_row_style('comfortable', True)
    assert view.rowHeight(0) == row_height('comfortable', spacing, two_line=True)


def test_ctrl_wheel_steps_the_row_size_once_per_notch():
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from tvhplayer.core.models import Channel

    app, model, view, _ = _view([Channel(uuid='a', name='A', number=1)])
    steps = []
    view.density_step.connect(steps.append)

    def wheel(delta, modifiers=Qt.KeyboardModifier.ControlModifier):
        event = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, delta),
            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False,
        )
        view.wheelEvent(event)

    wheel(120)
    wheel(-120)
    # A touchpad's small steps add up to one notch.
    for _ in range(4):
        wheel(30)
    wheel(120, Qt.KeyboardModifier.NoModifier)
    assert steps == [1, -1, 1]


def test_model_gives_playing_state_programme_and_scalable_logos():
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon, QPixmap
    from tvhplayer.channel_view import COL_NAME, COL_NOW, PLAYING_ROLE, SUBTITLE_ROLE
    from tvhplayer.core.channel_info import NowNext
    from tvhplayer.core.models import Channel, EpgEvent

    now = int(time.time())
    news = Channel(uuid='news', name='News', number=1, icon='imagecache/1')
    sport = Channel(uuid='sport', name='Sport', number=2)
    app, model, view, _ = _view([news, sport])
    model.set_channels([news, sport], ['imagecache/1', ''])
    model.set_programmes({'news': NowNext(EpgEvent(now - 60, now + 60, 'Headlines'))}, True, fetched=True)
    model.set_marks(news, set())
    logo = QPixmap(56, 32)
    logo.fill(Qt.GlobalColor.red)
    model.set_logos(True, {'imagecache/1': logo}, QIcon())

    assert model.index(0, COL_NOW).data(PLAYING_ROLE) is True
    assert model.index(1, COL_NAME).data(PLAYING_ROLE) is False
    assert model.index(0, COL_NAME).data(SUBTITLE_ROLE) == 'Headlines'
    assert model.index(1, COL_NAME).data(SUBTITLE_ROLE) == ''
    icon = model.index(0, COL_NAME).data(Qt.ItemDataRole.DecorationRole)
    assert isinstance(icon, QIcon)
    assert icon.actualSize(view.iconSize()) == view.iconSize()


def test_delegate_marks_the_playing_row_at_its_first_shown_column():
    from PyQt6.QtGui import QColor, QImage, QPalette
    from tvhplayer.channel_view import COL_NUMBER
    from tvhplayer.core.models import Channel

    news = Channel(uuid='news', name='News', number=1)
    app, model, view, delegate = _view([news, Channel(uuid='sport', name='Sport', number=2)])
    view.set_row_style('spacious', True)
    view.setAlternatingRowColors(True)
    model.set_marks(news, set())
    view.show()
    app.processEvents()

    def grab():
        image = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        view.viewport().render(image)
        return image

    accent = view.palette().color(QPalette.ColorRole.Highlight)
    middle = view.rowHeight(0) // 2
    x = view.columnViewportPosition(COL_NUMBER) + 2
    assert grab().pixelColor(x, middle) == accent
    # The second row is not playing.
    assert grab().pixelColor(x, view.rowHeight(0) + middle) != accent

    delegate.mark_playing = False
    view.viewport().update()
    app.processEvents()
    assert grab().pixelColor(x, middle) != QColor(accent)
    view.close()

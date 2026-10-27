from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem


def test_theme_keeps_row_colors():
    from tvhplayer.ui_theme import STYLESHEET

    app = QApplication.instance()
    app.setStyleSheet(STYLESHEET)
    try:
        table = QTableWidget(2, 1)
        table.resize(200, 120)
        for row, name in enumerate(('TV3', 'IRINN2')):
            table.setItem(row, 0, QTableWidgetItem(name))
        # The playing channel's row: light text on a dark background.
        playing = table.item(0, 0)
        playing.setBackground(QBrush(QColor('#1e3a8a')))
        playing.setForeground(QBrush(QColor('#ffffff')))
        table.show()
        table.selectRow(1)
        app.processEvents()

        rect = table.visualItemRect(playing)
        point = table.viewport().mapTo(table, rect.center())
        point.setX(table.viewport().mapTo(table, rect.topRight()).x() - 5)
        assert table.grab().toImage().pixelColor(point).name() == '#1e3a8a'
        table.close()
    finally:
        app.setStyleSheet('')

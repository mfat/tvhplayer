"""About TVHplayer: name, version, links, credits, and the license behind a disclosure."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

WEBSITE = 'https://github.com/mfat/tvhplayer'
GUIDE = 'https://github.com/mfat/tvhplayer/wiki/User-Guide'
ISSUES = 'https://github.com/mfat/tvhplayer/issues'
LICENSE_TEXT = (
    'This program is free software: you can redistribute it and/or modify it under the terms of the '
    'GNU General Public License as published by the Free Software Foundation, either version 3 of the '
    'License, or (at your option) any later version.<br><br>'
    'This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without '
    'even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU '
    'General Public License for more details.<br><br>'
    'You should have received a copy of the GNU General Public License along with this program. '
    "If not, see <a href='https://www.gnu.org/licenses/'>https://www.gnu.org/licenses/</a>."
)
ENGINE_NAMES = {'mpv': 'mpv', 'vlc': 'VLC'}


def _link_button(text, url, primary=False):
    button = QPushButton(text)
    if primary:
        button.setProperty('primary', True)
    button.setToolTip(url)
    button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return button


class AboutDialog(QDialog):
    def __init__(self, version, icon_path, engine=None, parent=None):
        super().__init__(parent)
        self._version = version
        self._engine = ENGINE_NAMES.get(engine or '', '')
        self.setWindowTitle('About TVHplayer')
        self.setAccessibleName('About TVHplayer')
        self.setAccessibleDescription(f'TVHplayer version {version}, created by mFat.')
        self.setFixedWidth(460)

        header = QVBoxLayout()
        header.setContentsMargins(28, 32, 28, 20)
        header.setSpacing(6)
        header.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon = QLabel()
        icon.setPixmap(QIcon(icon_path).pixmap(QSize(72, 72)))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel('TVHplayer')
        name.setObjectName('pageTitle')
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver = QLabel(f'Version {version}')
        ver.setObjectName('rowDesc')
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline = QLabel('A powerful and user-friendly TVHeadend client application.')
        tagline.setWordWrap(True)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        links = QHBoxLayout()
        links.setSpacing(8)
        links.addStretch(1)
        links.addWidget(_link_button('Project &Website', WEBSITE, primary=True))
        links.addWidget(_link_button('User &Guide', GUIDE))
        links.addWidget(_link_button('&Report a Bug', ISSUES))
        links.addStretch(1)
        header.addWidget(icon)
        header.addSpacing(8)
        header.addWidget(name)
        header.addWidget(ver)
        header.addSpacing(4)
        header.addWidget(tagline)
        header.addSpacing(12)
        header.addLayout(links)

        card = QFrame()
        card.setObjectName('groupCard')
        rows = QVBoxLayout(card)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        rows.addWidget(self._fact('Created by', QLabel('mFat')))
        rows.addWidget(self._separator())
        self.license_btn = QPushButton('Show')
        self.license_btn.setFlat(True)
        self.license_btn.setAccessibleName('Show the license')
        license_value = QWidget()
        license_row = QHBoxLayout(license_value)
        license_row.setContentsMargins(0, 0, 0, 0)
        license_row.addWidget(QLabel('GNU GPL v3 or later'), 1)
        license_row.addWidget(self.license_btn)
        rows.addWidget(self._fact('License', license_value))
        self.license_strip = QFrame()
        self.license_strip.setObjectName('statusStrip')
        strip_layout = QVBoxLayout(self.license_strip)
        strip_layout.setContentsMargins(16, 12, 16, 14)
        license_label = QLabel(LICENSE_TEXT)
        license_label.setObjectName('statusText')
        license_label.setTextFormat(Qt.TextFormat.RichText)
        license_label.setWordWrap(True)
        license_label.setOpenExternalLinks(True)
        strip_layout.addWidget(license_label)
        self.license_strip.hide()
        rows.addWidget(self.license_strip)
        self.license_btn.clicked.connect(self._toggle_license)

        card_wrap = QVBoxLayout()
        card_wrap.setContentsMargins(20, 0, 20, 20)
        card_wrap.addWidget(card)

        footer = QFrame()
        footer.setObjectName('dialogFooter')
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 10, 16, 10)
        self.copy_btn = QPushButton('&Copy Version Info')
        self.copy_btn.setFlat(True)
        self.copy_btn.clicked.connect(self._copy)
        close = QPushButton('Close')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        footer_row.addWidget(self.copy_btn)
        footer_row.addStretch(1)
        footer_row.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addLayout(card_wrap)
        layout.addWidget(footer)
        self._fit_height()

    @staticmethod
    def _separator():
        line = QFrame()
        line.setObjectName('rowSeparator')
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _fact(label, value):
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(16, 10, 16, 10)
        grid.setHorizontalSpacing(16)
        name = QLabel(label)
        name.setObjectName('rowDesc')
        name.setFixedWidth(104)
        grid.addWidget(name, 0, 0)
        grid.addWidget(value, 0, 1)
        return row

    def _fit_height(self):
        # The wrapped text needs its height worked out for the fixed width.
        self.setFixedHeight(self.layout().totalHeightForWidth(self.width()))

    def _toggle_license(self):
        show = self.license_strip.isHidden()
        self.license_strip.setVisible(show)
        self.license_btn.setText('Hide' if show else 'Show')
        self.license_btn.setAccessibleName('Hide the license' if show else 'Show the license')
        self._fit_height()

    def _copy(self):
        text = f'TVHplayer {self._version}'
        if self._engine:
            text += f', playing with {self._engine}'
        QGuiApplication.clipboard().setText(text)
        self.copy_btn.setText('Copied')
        QTimer.singleShot(1500, lambda: self.copy_btn.setText('&Copy Version Info'))

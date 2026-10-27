"""Render icons/tvhplayer.svg into the icon file a build needs.

    render_icon.py OUTPUT

OUTPUT ending in .png is a 1024x1024 image (PyInstaller makes the macOS .icns
from it); ending in .ico, a Windows icon with every size Windows asks for.
Needs PyQt6, and Pillow for .ico.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'icons' / 'tvhplayer.svg'
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def render(size):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise SystemExit(f'Cannot read {SVG}')
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    del app
    return image


def main(output):
    output = Path(output)
    if output.suffix == '.png':
        if not render(1024).save(str(output)):
            raise SystemExit(f'Cannot write {output}')
    elif output.suffix == '.ico':
        from PIL import Image

        png = output.with_suffix('.png')
        render(256).save(str(png))
        Image.open(png).save(output, sizes=ICO_SIZES)
        png.unlink()
    else:
        raise SystemExit('OUTPUT must end in .png or .ico')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])

#!/usr/bin/env python3
"""Smoke-test an installed tvhplayer .deb/.rpm.

Checks that the files are in place, that every module imports (so a missing
runtime dependency fails here instead of on a user's machine), and that the
built-in Tvheadend starts, answers with its generated login, and stops.
Run from outside the source tree so the installed copy is imported.
"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

APP_DIR = Path('/usr/share/tvhplayer')
REQUIRED_PATHS = (
    '/usr/bin/tvhplayer',
    '/usr/libexec/tvhplayer/tvheadend',
    '/usr/share/tvhplayer/tvheadend/src/webui/static',
    '/usr/share/tvhplayer/tvheadend/data/dvb-scan',
    '/usr/share/tvhplayer/tvhplayer.py',
    '/usr/share/tvhplayer/icons/play.svg',
    '/usr/share/applications/io.github.mfat.tvhplayer.desktop',
    '/usr/share/metainfo/io.github.mfat.tvhplayer.metainfo.xml',
    '/usr/share/icons/hicolor/scalable/apps/io.github.mfat.tvhplayer.svg',
)

missing = [path for path in REQUIRED_PATHS if not Path(path).exists()]
if missing:
    sys.exit('Missing from package: ' + ', '.join(missing))

# The launcher runs tvhplayer.py from APP_DIR, which imports core.* as top-level modules.
sys.path.insert(0, str(APP_DIR))
modules = [
    'tvhplayer', 'builtin_supervisor', 'a11y', 'file_manager', 'player_bar', 'settings_dialog', 'settings_widgets',
    'sleep_inhibit', 'setup_wizard', 'guide_dialogs', 'ui_theme',
]
modules += [f'core.{path.stem}' for path in sorted((APP_DIR / 'core').glob('*.py')) if path.stem != '__init__']
for name in modules:
    module = importlib.import_module(name)
    if not str(getattr(module, '__file__', '')).startswith(str(APP_DIR)):
        sys.exit(f'Imported {name} from {module.__file__}, not the installed package')

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from builtin_supervisor import BuiltinSupervisor  # noqa: E402
from core.builtin_server import find_bundled_binary, serverinfo_ok  # noqa: E402

binary = find_bundled_binary()
if binary != Path('/usr/libexec/tvhplayer/tvheadend'):
    sys.exit(f'The app found {binary}, not the packaged Tvheadend')

app = QCoreApplication([])
with tempfile.TemporaryDirectory() as config_dir:
    supervisor = BuiltinSupervisor(binary, Path(config_dir) / 'tvheadend')
    outcome = []
    loop = QEventLoop()
    supervisor.ready.connect(lambda http_port, _htsp: (outcome.append(('ready', http_port)), loop.quit()))
    supervisor.failed.connect(lambda reason: (outcome.append(('failed', reason)), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    supervisor.start()
    loop.exec()
    try:
        if not outcome or outcome[0][0] != 'ready':
            sys.exit(f'Built-in server did not start: {outcome}\n{supervisor.log_text()}')
        http_port = outcome[0][1]
        if not serverinfo_ok(http_port, username=supervisor.username, password=supervisor.password):
            sys.exit('Built-in server did not accept its generated login')
        if serverinfo_ok(http_port):
            sys.exit('Built-in server answered without a login')
    finally:
        supervisor.stop()

print(f'OK: {len(modules)} modules import from {APP_DIR}; built-in Tvheadend started on port {http_port}')

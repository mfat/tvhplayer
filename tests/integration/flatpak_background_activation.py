"""Run owner then activate in separate Flatpak invocations using a test profile.

This starts no player or server and requests no background permission.
"""

import argparse
from pathlib import Path
import sys

from PyQt6.QtCore import QCoreApplication, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tvhplayer.app_instance import AppInstance

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=('owner', 'activate'))
parser.add_argument('profile', help='Shared, disposable config directory inside the app sandbox')
args = parser.parse_args()
app = QCoreApplication([])
instance = AppInstance(args.profile)
owner = instance.acquire()
if args.mode == 'activate':
    assert not owner, 'A second invocation became an owner instead of activating the first'
    print('ACTIVATION SENT', flush=True)
else:
    assert owner
    activated = []
    def shown():
        activated.append(True)
        print('ACTIVATED', flush=True)
        app.quit()
    instance.show_requested.connect(shown)
    QTimer.singleShot(15000, app.quit)
    print('READY', flush=True)
    app.exec()
    instance.close()
    assert activated, 'No activation arrived'

"""Run inside a Flatpak sandbox with the TVHplayer source on PYTHONPATH.

This deliberately uses the real Settings button and native QFileDialog. The
host must select a folder in the portal (manually or through desktop automation).
Run `choose`, then `check` in a new process; rename/delete/revoke the host folder
and run `stale`, then `choose` again to recover. No chooser or filesystem mocks.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from tvhplayer.core.config import ConfigStore
from tvhplayer.tvhplayer import TVHeadendClient, in_flatpak, recording_dir_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['choose', 'check', 'stale'])
    parser.add_argument('--marker', default='child-recording-probe.txt')
    parser.add_argument('--allow-same-folder', action='store_true')
    args = parser.parse_args()
    assert in_flatpak(), 'This integration check requires a real Flatpak sandbox'
    assert Path(args.marker).name == args.marker
    store = ConfigStore()
    store.data.update(check_for_updates=False, builtin_autostart=False, setup_offered=True)
    store.save()
    app = QApplication([])
    window = TVHeadendClient()
    previous = window.config.get('local_recording_dir', '')
    outcome = {'phase': args.phase, 'previous': previous}
    seen_messages = set()
    message_timer = QTimer()

    def report_messages():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible() and widget.text() not in seen_messages:
                seen_messages.add(widget.text())
                print('DIALOG ' + widget.text(), flush=True)

    message_timer.timeout.connect(report_messages)
    message_timer.start(100)

    def run():
        try:
            if args.phase == 'choose':
                dialog = window.show_settings()
                dialog.nav.setCurrentRow(3)
                dialog.folder_btn.click()
                assert dialog.folder_edit.text() == window.local_recording_dir()
                assert args.allow_same_folder or window.local_recording_dir() != previous, 'Choose a different folder'
            folder = window.local_recording_dir()
            error = recording_dir_error(folder)
            outcome.update(folder=folder, error=error)
            if args.phase == 'stale':
                assert error, 'Expected the saved path to have become inaccessible'
                dialog = window.show_settings()
                assert 'Cannot save recordings here:' in dialog.folder_status.text()
                assert folder in dialog.folder_status.text(), 'Settings must identify the stale path'
            else:
                assert not error, error
                assert ConfigStore().data['local_recording_dir'] == folder
                subprocess.run([
                    sys.executable, '-c',
                    'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b"child process recording probe")',
                    str(Path(folder) / args.marker),
                ], check=True)
            outcome['ok'] = True
        except Exception as exc:
            outcome.update(ok=False, failure=str(exc))
        finally:
            print('RESULT ' + json.dumps(outcome), flush=True)
            window._confirm_quit = lambda: True
            window.close()
            app.exit(0 if outcome.get('ok') else 1)

    QTimer.singleShot(0, run)
    QTimer.singleShot(90000, lambda: app.exit(2))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

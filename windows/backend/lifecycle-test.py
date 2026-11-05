"""Explicit Windows test for real port collisions, duplicate windows and crash recovery."""
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal
from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
from tvhplayer.core.builtin_server import pick_port_pair


class Signals(QObject):
    restart = pyqtSignal()
    abort = pyqtSignal(str)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'windows/backend/dist')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--orphan-child', action='store_true')
    args = parser.parse_args()
    config = args.config or ROOT / 'windows/build' / ('lifecycle-' + uuid.uuid4().hex) / 'config'
    app = QCoreApplication([])
    s = WslcBuiltinSupervisor(config, args.bundle)
    s.recordings_dir = str(config.parent / 'recordings')
    if args.orphan_child:
        # Intentionally simulate a killed UI. Only this test's owned container
        # and private config are used; the parent verifies recovery and cleanup.
        s.ready.connect(lambda *_ports: os._exit(0))
        s.failed.connect(lambda _message: os._exit(1))
        QTimer.singleShot(60000, lambda: os._exit(2))
        s.start()
        return app.exec()
    signals = Signals()
    signals.restart.connect(s.start)
    state = {'phase': 0, 'error': '', 'orphan': None}
    held = socket.socket()
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        held.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    for _ in range(20):
        http, htsp = pick_port_pair()
        try:
            held.bind(('127.0.0.1', http))
            break
        except OSError:
            continue
    else:
        raise RuntimeError('Could not reserve a test port')
    held.listen()
    s.http_port, s.htsp_port = http, htsp

    def fail(message):
        state['error'] = message
        app.quit()
    signals.abort.connect(fail)

    def ready(*_ports):
        try:
            if state['phase'] == 0:
                assert s.http_port != http, 'Backend did not retry the occupied HTTP port'
                held.close()
                duplicate = WslcBuiltinSupervisor(config, args.bundle)
                errors = []
                duplicate.failed.connect(errors.append)
                duplicate.start()
                assert errors and 'Another TVHplayer' in errors[0] and s.is_running()
                print('PASS: real port collision retry and duplicate window rejection', flush=True)
                state['phase'] = 1
            else:
                previous = state['orphan']
                assert s.runtime.inspect_owned(previous['name'], previous['owner'], missing_ok=True) is None
                assert json.loads((config / 'wslc-owner.json').read_text())['owner'] != previous['owner']
                print('PASS: killed UI orphan verified, stopped and replaced safely', flush=True)
                state['phase'] = 2
            s.stop()
        except Exception as exc:
            fail(str(exc) or type(exc).__name__)

    def completed(error):
        if error:
            fail(error)
        elif state['phase'] == 1:
            def create_orphan():
                try:
                    result = subprocess.run([sys.executable, __file__, '--orphan-child', '--bundle', str(args.bundle),
                                             '--config', str(config)], timeout=65, capture_output=True, text=True,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode:
                        raise RuntimeError('Orphan fixture could not start: ' + result.stderr[-1000:])
                    state['orphan'] = json.loads((config / 'wslc-owner.json').read_text())
                    signals.restart.emit()
                except Exception as exc:
                    signals.abort.emit(str(exc))
            threading.Thread(target=create_orphan, daemon=True).start()
        else:
            app.quit()
    s.ready.connect(ready)
    s._completed.connect(completed)
    QTimer.singleShot(150000, lambda: fail('Lifecycle test timed out'))
    s.start()
    try:
        app.exec()
    finally:
        held.close()
        s.shut_down()
        app.processEvents()
        if state['orphan']:
            s.runtime.stop_owned(state['orphan']['name'], state['orphan']['owner'])
        record = config / 'wslc-owner.json'
        if record.exists():
            previous = json.loads(record.read_text())
            s.runtime.stop_owned(previous['name'], previous['owner'])
            record.unlink()
    if state['error']:
        print(state['error'], file=sys.stderr)
    return 0 if state['phase'] == 2 and not state['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

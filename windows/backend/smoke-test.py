"""Explicit real-host test: provision, authenticate, verify ports, stop owned backend."""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtCore import QCoreApplication, QTimer
from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
from tvhplayer.core.windows_wslc import WslcRuntimeAdapter


def main():
    root = Path(__file__).resolve().parents[2]
    folder = root / 'windows' / 'build' / ('wslc-smoke-' + uuid.uuid4().hex)
    app = QCoreApplication([])
    class DiagnosticRuntime(WslcRuntimeAdapter):
        def verify_running(self, name, owner, ports, udp_ports=()):
            data = self.inspect_owned(name, owner)
            (folder / 'inspect.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
            return super().verify_running(name, owner, ports, udp_ports)
    supervisor = WslcBuiltinSupervisor(folder / 'config', root / 'windows/backend/dist',
                                      runtime=DiagnosticRuntime())
    supervisor.recordings_dir = str(folder / 'recordings')
    result = {'ready': False, 'error': ''}
    supervisor.status_changed.connect(lambda status: print('Backend:', status, flush=True))

    def ready(http, htsp):
        print(f'Authenticated backend ready: HTTP 127.0.0.1:{http}, HTSP 127.0.0.1:{htsp}', flush=True)
        result['ready'] = True
        supervisor.stop()

    def failed(message):
        result['error'] = message
        print('Backend error:', message, flush=True)
        app.quit()

    def completed(error):
        if error:
            result['error'] = error
        app.quit()

    def timeout():
        result['error'] = 'Smoke test timed out'
        app.quit()

    supervisor.ready.connect(ready)
    supervisor.failed.connect(failed)
    supervisor._completed.connect(completed)
    QTimer.singleShot(120000, timeout)
    supervisor.start()
    try:
        app.exec()
    finally:
        supervisor.shut_down()
        app.processEvents()
    if result['error']:
        print(result['error'], file=sys.stderr)
    return 0 if result['ready'] and not result['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

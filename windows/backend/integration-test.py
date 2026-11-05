"""Real Windows acceptance test using an isolated config and synthetic IPTV channel.

Requires the local offline backend bundle and WSLc. Does not use RF tuners or
change remote servers, Windows networking, or unrelated containers.
"""
import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QCoreApplication, QTimer
import requests
import psutil
from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
from tvhplayer.core.http_backend import HttpBackend
from tvhplayer.core.htsp_backend import HtspBackend
from tvhplayer.core.htsp_connection import HtspConnection
from tvhplayer.core.errors import TvhAuthError
from tvhplayer.core.models import ServerConfig
from tvhplayer.core.playlist import parse_playlist, plan_channels
from tvhplayer.core.playlist_sync import PlaylistSource, sync_playlist, wait_for_checks, NETWORK_CONF
from tvhplayer.core.tvh_admin import TvhAdmin
from tvhplayer.core.logs import sanitize


def wait_for(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.5)
    raise AssertionError('Timed out waiting for the backend test condition')


def exercise(s, recordings):
    server = ServerConfig('Integration', f'http://127.0.0.1:{s.http_port}',
                          s.username, s.password, 'htsp', s.htsp_port, True)
    base = server.url
    listeners = [row for row in psutil.net_connections(kind='tcp')
                 if row.status == psutil.CONN_LISTEN and row.laddr.port in (s.http_port, s.htsp_port)]
    assert {row.laddr.port for row in listeners} == {s.http_port, s.htsp_port}
    assert all(row.laddr.ip == '127.0.0.1' for row in listeners)
    print('PASS: Windows socket table confirms IPv4 loopback-only listeners', flush=True)
    with requests.Session() as session:
        session.trust_env = False
        assert session.get(base + '/api/serverinfo', timeout=5).status_code == 401
    print('PASS: unauthenticated administrative HTTP access denied', flush=True)
    rejected = HtspConnection('127.0.0.1', s.htsp_port)
    try:
        rejected.connect()
        rejected.hello()
        try:
            rejected.authenticate(s.username, 'wrong-password')
        except TvhAuthError:
            pass
        else:
            raise AssertionError('HTSP accepted an incorrect password')
    finally:
        rejected.close()
    print('PASS: incorrect HTSP credentials denied', flush=True)
    command = ('pipe:///usr/bin/ffmpeg -nostdin -loglevel error -re -f lavfi '
               '-i testsrc2=size=320x180:rate=25 -f lavfi -i sine=frequency=1000 '
               '-c:v mpeg2video -c:a mp2 -mpegts_service_id 1 -f mpegts pipe:1')
    plans, skipped = plan_channels(parse_playlist('#EXTM3U\n#EXTINF:-1,Integration Pattern\n' + command + '\n'),
                                   '/usr/bin/ffmpeg', 'Integration', allow_commands=True)
    assert not skipped and len(plans) == 1
    NETWORK_CONF['max_timeout'] = 15
    source = PlaylistSource('Integration', 'integration.m3u', 'builtin')
    with TvhAdmin(server) as admin:
        result = sync_playlist(admin, source, plans)
        deadline = time.monotonic() + 50
        wait_for_checks(admin, source, result, cancelled=lambda: time.monotonic() > deadline)
        assert result.working == 1 and not result.check_stopped, str(result)
    http, htsp = HttpBackend(server), HtspBackend(server)
    try:
        channel = wait_for(lambda: next((c for c in http.get_channels() if c.name == 'Integration Pattern'), None))
        print('PASS: playlist imported and channel scanned', flush=True)
        with requests.Session() as session:
            session.trust_env = False
            with session.get(http.stream_url(channel, 'pass'), stream=True, timeout=20) as response:
                response.raise_for_status()
                data = response.raw.read(188 * 100)
                assert len(data) == 188 * 100 and all(data[i] == 0x47 for i in range(0, len(data), 188))
        print('PASS: authenticated HTTP MPEG-TS streaming', flush=True)
        htsp_channel = next(c for c in htsp.get_channels() if c.name == channel.name)
        htsp._conn.rpc('subscribe', {'subscriptionId': 1, 'channelId': htsp_channel.htsp_id, 'weight': 1})
        try:
            packet = htsp._conn.recv_until(lambda msg: msg.get('method') == 'muxpkt' and msg.get('payload'), timeout=20)
            assert packet['payload']
        finally:
            htsp._conn.rpc('unsubscribe', {'subscriptionId': 1})
        print('PASS: authenticated HTSP media packets', flush=True)
        now = int(time.time())
        http.create_dvr_entry(channel, now + 2, now + 12, 'Integration recording')
        wait_for(lambda: any(entry.title == 'Integration recording' for entry in http.list_dvr_entries()))
        wait_for(lambda: any(path.is_file() and path.stat().st_size > 1024 for path in recordings.rglob('*')), timeout=35)
        wait_for(lambda: any(entry.title == 'Integration recording' and entry.sched_status == 'completed'
                            for entry in http.list_dvr_entries()), timeout=35)
        media = next(path for path in recordings.rglob('*') if path.is_file() and path.stat().st_size > 1024)
        owner = json.loads((s.config_dir / 'wslc-owner.json').read_text())
        guest = '/recordings/' + media.relative_to(recordings).as_posix()
        duration = s.runtime.command('exec', owner['name'], '/usr/bin/ffprobe', '-v', 'error', '-show_entries',
                                     'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', guest)
        assert float(duration) > 1
        print('PASS: completed recording in Windows folder, readable by FFprobe', flush=True)
        return channel.name, media, s.password
    finally:
        http.close()
        htsp.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'windows/backend/dist')
    args = parser.parse_args()
    folder = ROOT / 'windows/build' / ('acceptance-' + uuid.uuid4().hex)
    recordings = folder / 'TV recordings مهدی'
    app = QCoreApplication([])
    supervisor = WslcBuiltinSupervisor(folder / 'config مهدی', args.bundle)
    supervisor.recordings_dir = str(recordings)
    supervisor.padding = (0, 0)
    state = {'phase': 0, 'error': '', 'saved': None, 'diagnostics': ''}

    def ready(*_ports):
        def worker():
            try:
                if state['phase'] == 0:
                    state['saved'] = exercise(supervisor, recordings)
                    state['phase'] = 1
                else:
                    name, media, password = state['saved']
                    assert supervisor.password == password and media.exists()
                    backend = HttpBackend(ServerConfig('Integration', f'http://127.0.0.1:{supervisor.http_port}',
                                                       supervisor.username, supervisor.password))
                    try:
                        assert any(c.name == name for c in backend.get_channels())
                        assert any(entry.title == 'Integration recording' for entry in backend.list_dvr_entries())
                    finally:
                        backend.close()
                    print('PASS: credentials, channels and recording survive container restart', flush=True)
                    state['phase'] = 2
            except Exception as exc:
                import traceback
                traceback.print_exc()
                state['error'] = str(exc) or type(exc).__name__
                try:
                    owner = json.loads((supervisor.config_dir / 'wslc-owner.json').read_text())
                    state['diagnostics'] = sanitize(supervisor.runtime.logs_owned(owner['name'], owner['owner']))
                except Exception:
                    pass
            finally:
                supervisor.stop()
        threading.Thread(target=worker, daemon=True).start()

    def completed(error):
        state['error'] = state['error'] or error
        if not state['error'] and state['phase'] == 1:
            QTimer.singleShot(0, supervisor.start)
        else:
            app.quit()

    def timeout():
        state['error'] = 'Acceptance test timed out'
        app.quit()

    supervisor.ready.connect(ready)
    supervisor._completed.connect(completed)
    QTimer.singleShot(180000, timeout)
    supervisor.start()
    try:
        app.exec()
    finally:
        supervisor.shut_down()
        app.processEvents()
    if state['error']:
        (folder / 'backend.log').write_text(state['diagnostics'] or supervisor.log_text(), encoding='utf-8')
        print(state['error'], file=sys.stderr)
    print('Test artifacts:', folder)
    return 0 if state['phase'] == 2 and not state['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

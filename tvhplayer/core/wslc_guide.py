"""XMLTV transfer into one captured WSLc container, from the guide worker only."""
import subprocess
import time
from types import SimpleNamespace

from .guide_feeds import GuideError
from .windows_wslc import WslcRuntimeAdapter, WslcError


class ContainerGuide:
    def __init__(self, identity, cancelled, runtime=None):
        self.name, self.owner = identity
        self.cancelled = cancelled
        self.runtime = runtime or WslcRuntimeAdapter()
        self.runtime.cancel = SimpleNamespace(is_set=cancelled)

    def check(self, path):
        if self.cancelled():
            raise GuideError('Stopped.')
        if not path or not path.startswith('/config/') or '\x00' in path:
            raise GuideError('The built-in server did not provide its XMLTV socket path.')
        try:
            data = self.runtime.inspect_owned(self.name, self.owner)
            if not data.get('State', {}).get('Running'):
                raise GuideError('The built-in server stopped before the guide could be loaded.')
            self.runtime.command('exec', self.name, 'test', '-S', path, timeout=5)
        except WslcError as exc:
            raise GuideError(f'Cannot access the built-in server XMLTV socket: {exc}') from exc

    def send(self, path, file_path):
        self.check(path)
        # data demux/mux and stream copy preserve XML bytes without decoding.
        # Guest timeout also bounds a process left behind by a crashed host.
        argv = [self.runtime.executable, 'exec', '-i', self.name,
                'timeout', '600', 'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'data', '-i', 'pipe:0', '-map', '0:0', '-c', 'copy',
                '-f', 'data', '-rw_timeout', '5000000', 'unix:' + path]
        try:
            with open(file_path, 'rb') as source:
                with subprocess.Popen(argv, stdin=source, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
                    deadline = time.monotonic() + 600
                    try:
                        while True:
                            if self.cancelled():
                                raise GuideError('Stopped.')
                            if time.monotonic() >= deadline:
                                raise GuideError('Sending the TV guide to the built-in server timed out.')
                            try:
                                code = process.wait(timeout=.1)
                                break
                            except subprocess.TimeoutExpired:
                                continue
                        if code:
                            raise GuideError('The built-in server could not receive the XMLTV guide.')
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GuideError(f'Could not send the TV guide to the built-in server: {exc}') from exc

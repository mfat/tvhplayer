from pathlib import Path
from types import SimpleNamespace

import pytest

from tvhplayer.core.guide_feeds import GuideCache, GuideError, GuideSource
from tvhplayer.core.guide_update import update_server_guide
from tvhplayer.core.wslc_guide import ContainerGuide
from tests.test_guide_update import FakeAdmin, _guide, NOW


def test_container_import_bypasses_host_socket_and_sends_both_passes(monkeypatch, tmp_path):
    received = []
    admin = FakeAdmin('/config/data/epggrab/xmltv.sock', received)
    checked = []
    monkeypatch.setattr(ContainerGuide, 'check', lambda self, path: checked.append(path))
    monkeypatch.setattr(ContainerGuide, 'send', lambda self, path, file: received.append(Path(file).read_text()))
    location = _guide(tmp_path)
    server = {'builtin': True, '_guide_container': ('tvhplayer-' + 'a' * 32, 'a' * 32)}
    cache = GuideCache(tmp_path / 'cache')
    sources = [GuideSource(location, 'builtin')]
    report = update_server_guide(admin, server, cache, sources, {}, now=NOW)
    assert report.covered == 2
    assert len(received) == 2 and received[0] == received[1]
    assert checked == [admin.socket_path]
    assert update_server_guide(admin, server, cache, sources, {}, now=NOW).unchanged
    assert len(received) == 2


@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancel', 'timeout'])
def test_transfer_closes_process_and_input(monkeypatch, tmp_path, outcome):
    from tvhplayer.core import wslc_guide
    source = tmp_path / 'guide.xml'
    source.write_bytes(b'<tv/>')
    captured = {}
    class Process:
        killed = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def poll(self): return None if outcome in ('cancel', 'timeout') and not self.killed else 0
        def kill(self): self.killed = True
        def wait(self, timeout): return 1 if outcome == 'failure' else 0
    process = Process()
    def spawn(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return process
    monkeypatch.setattr(wslc_guide.subprocess, 'Popen', spawn)
    monkeypatch.setattr(ContainerGuide, 'check', lambda *args: None)
    ticks = iter([0, 601]) if outcome == 'timeout' else iter([0, 0])
    monkeypatch.setattr(wslc_guide.time, 'monotonic', lambda: next(ticks))
    transport = ContainerGuide(('name', 'owner'), lambda: outcome == 'cancel', SimpleNamespace(executable='wslc.exe'))
    if outcome == 'success':
        transport.send('/config/data/epggrab/xmltv.sock', source)
    else:
        with pytest.raises(GuideError):
            transport.send('/config/data/epggrab/xmltv.sock', source)
    assert captured['stdin'].closed
    assert captured['argv'][:4] == ['wslc.exe', 'exec', '-i', 'name']
    assert process.killed == (outcome in ('cancel', 'timeout'))


@pytest.mark.parametrize('path', ['', '/tmp/not-ours', None])
def test_missing_socket_path_is_rejected(path):
    with pytest.raises(GuideError):
        ContainerGuide(('name', 'owner'), lambda: False).check(path)


def test_stopped_container_is_rejected():
    runtime = SimpleNamespace(inspect_owned=lambda *args: {'State': {'Running': False}})
    with pytest.raises(GuideError, match='stopped'):
        ContainerGuide(('name', 'owner'), lambda: False, runtime).check('/config/data/epggrab/xmltv.sock')


def test_cancelled_import_does_not_link_or_save_completion(monkeypatch, tmp_path):
    cancelled = []
    admin = FakeAdmin('/config/data/epggrab/xmltv.sock', [])
    monkeypatch.setattr(ContainerGuide, 'check', lambda *args: None)
    monkeypatch.setattr(ContainerGuide, 'send', lambda *args: cancelled.append(True))
    cache = GuideCache(tmp_path / 'cache')
    source = GuideSource(_guide(tmp_path), 'builtin')
    with pytest.raises(GuideError, match='Stopped'):
        update_server_guide(admin, {'builtin': True, '_guide_container': ('name', 'owner')},
                            cache, [source], {}, now=NOW, cancelled=lambda: bool(cancelled))
    assert not admin.saved
    assert not list(cache.folder.glob('loaded-*.json'))


def test_replaced_or_wrong_owner_container_is_rejected():
    from tvhplayer.core.windows_wslc import WslcError
    def inspect(*args):
        raise WslcError('Cannot verify TVHplayer container ownership.')
    with pytest.raises(GuideError, match='ownership'):
        ContainerGuide(('name', 'owner'), lambda: False,
                       SimpleNamespace(inspect_owned=inspect)).check('/config/data/epggrab/xmltv.sock')

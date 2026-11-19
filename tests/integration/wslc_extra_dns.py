"""Live WSLc check that an extra DNS server is used in addition to Windows DNS.

Not part of the hermetic suite. Set TVHPLAYER_WSLC_DNS_INTEGRATION=1 on Windows
with WSL Containers and the offline backend image installed. The test publishes
no ports. Server startup and HDHomeRun UDP streaming stay in
``windows/backend/smoke-test.py`` and ``windows/backend/integration-test.py``.
"""
import os
import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('TVHPLAYER_WSLC_DNS_INTEGRATION') != '1' or sys.platform != 'win32',
    reason='set TVHPLAYER_WSLC_DNS_INTEGRATION=1 on Windows to resolve through WSLc',
)


def test_container_resolves_with_windows_dns_plus_an_extra_server():
    from tvhplayer.core.backend_bundle import read_manifest
    from tvhplayer.core.builtin_runtime import windows_backend_dir
    from tvhplayer.core.windows_dns import discover_windows_dns, merge_dns_servers
    from tvhplayer.core.windows_wslc import WslcRuntimeAdapter

    inherited = discover_windows_dns()
    extra = os.environ.get('TVHPLAYER_WSLC_TEST_DNS', '1.1.1.1')
    servers = merge_dns_servers(inherited, extra)
    assert servers[0] == extra
    assert all(server in servers for server in inherited)
    assert len(servers) == len(set(servers))
    directory = windows_backend_dir()
    if not (directory / 'manifest.json').is_file():
        pytest.skip('offline backend image is not installed')
    image = read_manifest(directory)['image']
    runtime = WslcRuntimeAdapter()
    name = 'tvhplayer-dns-' + uuid.uuid4().hex[:12]
    args = ['run', '--rm', '--pull', 'never', '--name', name, '--entrypoint', '/bin/sh']
    for address in servers:
        args += ['--dns', address]
    try:
        output = runtime.command(
            *args, image, '-c', 'getent hosts one.one.one.one || getent hosts example.com', timeout=90)
    finally:
        try:
            runtime.command('remove', name, timeout=10)
        except Exception:
            pass
    assert output.strip()

"""Setup blockers and reboot persistence without changing Windows features."""
import json
import subprocess

import pytest

from tvhplayer.core import windows_prerequisites as prerequisites


@pytest.mark.parametrize('state,action', [
    ({'firmware': False, 'hypervisor': False, 'feature': 2}, 'bios'),
    ({'firmware': True, 'feature': 2}, 'repair'),
    ({'firmware': True, 'feature': 3}, 'repair'),
    ({'firmware': True, 'feature': 1, 'reboot_pending': True, 'hypervisor': False}, 'reboot'),
])
def test_reports_specific_blocker(state, action):
    assert prerequisites.prerequisite_issue(state)[1] == action


@pytest.mark.parametrize('state', [{}, {'feature': None, 'firmware': None},
    {'feature': 1, 'firmware': False, 'hypervisor': True, 'reboot_pending': True}])
def test_unknown_or_active_hypervisor_does_not_block_runtime_check(state):
    assert prerequisites.prerequisite_issue(state) is None


def test_probe_handles_unavailable_cim():
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    assert prerequisites.probe_windows(runner) == {}


def test_probe_reads_structured_state_without_elevation():
    def runner(args, **kwargs):
        assert '-Verb RunAs' not in args[-1]
        assert 'Enable-' not in args[-1]
        assert kwargs['timeout'] == 20
        return subprocess.CompletedProcess(args, 0, json.dumps({'feature': 2, 'firmware': True}))
    assert prerequisites.prerequisite_issue(prerequisites.probe_windows(runner))[1] == 'repair'


def test_app_restart_does_not_clear_required_windows_restart(tmp_path, monkeypatch):
    config = tmp_path / 'config'
    monkeypatch.setattr(prerequisites, 'windows_boot_time', lambda: 1000.)
    prerequisites.save_setup(config, 'restart_required', 'install')
    assert prerequisites.restart_still_required(config)
    monkeypatch.setattr(prerequisites, 'windows_boot_time', lambda: 2000.)
    assert not prerequisites.restart_still_required(config)
    assert prerequisites.pending_setup(config)  # Only a ready server clears progress.


@pytest.mark.parametrize('content', ['[]', 'null', '{bad json', '{"schema":2}'])
def test_invalid_resume_data_is_ignored(tmp_path, content):
    prerequisites.setup_file(tmp_path / 'config').write_text(content)
    assert prerequisites.pending_setup(tmp_path / 'config') is None


def test_enabled_feature_does_not_offer_repeated_repair():
    from tvhplayer.core.windows_wslc import WslcPrerequisiteError, WslcRuntimeAdapter
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, '', 'HCS_E_HYPERV_NOT_INSTALLED')
    runtime = WslcRuntimeAdapter('wslc.exe', runner)
    runtime._prerequisite_state = {'feature': 1}
    with pytest.raises(WslcPrerequisiteError) as error:
        runtime.command('inspect')
    assert error.value.action == 'diagnose'


def test_reboot_marker_blocks_start_before_runtime_is_touched(tmp_path, monkeypatch, qapp):
    from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
    class Runtime:
        def check(self):
            pytest.fail('Do not retry WSL until Windows has restarted')
    monkeypatch.setattr(prerequisites, 'windows_boot_time', lambda: 1000.)
    prerequisites.save_setup(tmp_path / 'config', 'restart_required', 'repair')
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle', runtime=Runtime())
    supervisor.start()
    supervisor._thread.join(5)
    qapp.processEvents()
    assert supervisor.setup_issue.action == 'reboot'
    assert supervisor.status == 'failed'


def test_setup_marker_cleared_only_when_server_is_ready(tmp_path, qapp):
    from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
    config = tmp_path / 'config'
    prerequisites.save_setup(config, 'check_required', 'install')
    supervisor = WslcBuiltinSupervisor(config, tmp_path / 'bundle')
    supervisor._on_ready()
    assert prerequisites.pending_setup(config) is None


def test_virtualization_blocker_disables_future_checks_until_explicit_retry(tmp_path, qapp):
    from tvhplayer.core.windows_wslc import WslcPrerequisiteError
    from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor
    calls = []
    class Runtime:
        setup_checks = prerequisites.setup_checks({'firmware': False, 'feature': 1}, True, (3, 0, 3))
        def check(self):
            calls.append('check')
            raise WslcPrerequisiteError('Firmware virtualization is unavailable', 'bios')
    config = tmp_path / 'config'
    supervisor = WslcBuiltinSupervisor(config, tmp_path / 'bundle', runtime=Runtime())
    supervisor.start()
    supervisor._thread.join(5)
    qapp.processEvents()
    assert supervisor.disabled
    assert prerequisites.pending_setup(config)['stage'] == 'disabled'
    supervisor.start()
    assert calls == ['check']
    reopened = WslcBuiltinSupervisor(config, tmp_path / 'bundle', runtime=Runtime())
    assert reopened.disabled
    assert reopened.setup_checks == supervisor.setup_checks
    reopened.start()
    assert reopened._thread is None
    assert calls == ['check']
    reopened.enable_and_check()
    reopened._thread.join(5)
    qapp.processEvents()
    assert calls == ['check', 'check']
    assert reopened.disabled  # Still blocked; automatic checks stay off.


def test_report_checks_wsl_version_without_starting_vm_when_virtualization_is_off(monkeypatch):
    from tvhplayer.core.windows_wslc import WslcPrerequisiteError, WslcRuntimeAdapter
    monkeypatch.setattr('sys.platform', 'win32')
    monkeypatch.setattr(prerequisites, 'probe_windows', lambda: {'firmware': False, 'feature': 1})
    runtime = WslcRuntimeAdapter('wslc.exe')
    calls = []
    def command(name):
        calls.append(name)
        assert name == 'version', 'No VM operations while firmware virtualization is off'
        return 'WSLc 3.0.3'
    monkeypatch.setattr(runtime, 'command', command)
    with pytest.raises(WslcPrerequisiteError) as error:
        runtime.check()
    assert error.value.action == 'bios'
    assert calls == ['version']
    report = {row['key']: row['status'] for row in runtime.setup_checks}
    assert report == {'wsl': 'passed', 'version': 'passed', 'virtualization': 'failed',
                      'platform': 'passed', 'server': 'pending'}


def test_unknown_probe_never_reports_virtualization_or_windows_support_passed():
    report = {row['key']: row['status'] for row in prerequisites.setup_checks({}, True, None)}
    assert report['wsl'] == 'passed'
    assert all(report[key] == 'pending' for key in ('version', 'virtualization', 'platform', 'server'))

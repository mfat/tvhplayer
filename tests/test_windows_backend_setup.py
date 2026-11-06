from PyQt6.QtCore import QProcess

from tvhplayer.core.windows_wslc import WslcPrerequisiteError
from tvhplayer.windows_backend_setup import WindowsBackendSetup
from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor


def test_success_without_reboot_prompt_still_requires_windows_restart(tmp_path, qapp):
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle')
    supervisor.setup_issue = WslcPrerequisiteError('WSL missing', 'install')
    dialog = WindowsBackendSetup(supervisor)
    dialog._installed(0, QProcess.ExitStatus.NormalExit)
    assert 'even if Windows did not show a reboot prompt' in dialog.message.text()
    from tvhplayer.core.windows_prerequisites import pending_setup
    assert pending_setup(supervisor.config_dir)['stage'] == 'restart_required'
    assert dialog.install.isHidden()
    dialog.reject()


def test_unknown_state_requires_check_before_offering_install(tmp_path, qapp):
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle')
    dialog = WindowsBackendSetup(supervisor)
    assert dialog.install.isHidden()
    assert dialog.check.isEnabled()
    dialog.reject()


def test_bios_blocker_cannot_launch_installer_and_can_transition_to_repair(tmp_path, qapp, monkeypatch):
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle')
    supervisor.setup_issue = WslcPrerequisiteError('Enable BIOS virtualization', 'bios')
    dialog = WindowsBackendSetup(supervisor)
    calls = []
    monkeypatch.setattr(QProcess, 'start', lambda *args: calls.append(args))
    dialog._install()
    assert calls == []
    assert dialog.install.isHidden()
    supervisor.setup_issue = WslcPrerequisiteError('Enable Virtual Machine Platform', 'repair')
    supervisor.failed.emit(str(supervisor.setup_issue))
    assert not dialog.install.isHidden()
    assert dialog.install.isEnabled()
    assert 'Virtual Machine Platform' in dialog.install.text()
    dialog.reject()


def test_update_success_rechecks_server_instead_of_declaring_setup_complete(tmp_path, qapp, monkeypatch):
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle')
    supervisor.setup_issue = WslcPrerequisiteError('Old WSL', 'update')
    calls = []
    monkeypatch.setattr(supervisor, 'start', lambda: calls.append('check'))
    dialog = WindowsBackendSetup(supervisor)
    dialog._installed(0, QProcess.ExitStatus.NormalExit)
    assert calls == ['check']
    assert dialog.progress.isHidden() is False
    dialog.reject()


def test_reopening_app_resumes_saved_setup_even_without_autostart(tmp_path, qapp):
    from types import SimpleNamespace
    from tvhplayer.tvhplayer import TVHeadendClient
    from tvhplayer.core.windows_prerequisites import save_setup
    calls = []
    supervisor = SimpleNamespace(config_dir=tmp_path / 'config', is_running=lambda: False,
                                 start=lambda: calls.append('verify_and_start'))
    host = SimpleNamespace(builtin=supervisor,
                           show_windows_backend_setup=lambda: calls.append('show_setup'))
    TVHeadendClient._resume_windows_backend_setup(host)
    assert calls == []
    save_setup(supervisor.config_dir, 'restart_required', 'repair')
    TVHeadendClient._resume_windows_backend_setup(host)
    assert calls == ['show_setup', 'verify_and_start']


def test_disabled_backend_never_resumes_setup_on_launch(tmp_path, qapp):
    from types import SimpleNamespace
    from tvhplayer.tvhplayer import TVHeadendClient
    from tvhplayer.core.windows_prerequisites import save_setup
    calls = []
    supervisor = SimpleNamespace(config_dir=tmp_path / 'config', disabled=True,
                                 start=lambda: calls.append('start'))
    host = SimpleNamespace(builtin=supervisor,
                           show_windows_backend_setup=lambda: calls.append('dialog'))
    save_setup(supervisor.config_dir, 'disabled', 'bios')
    TVHeadendClient._resume_windows_backend_setup(host)
    assert calls == []

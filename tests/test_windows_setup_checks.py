from PyQt6.QtCore import QProcess
from PyQt6.QtGui import QDesktopServices

from tvhplayer.core.windows_prerequisites import failed_checks, setup_checks
from tvhplayer.core.windows_wslc import WslcPrerequisiteError
from tvhplayer.windows_setup_checks import WindowsSetupChecks
from tvhplayer.windows_backend_setup import WindowsBackendSetup
from tvhplayer.wslc_builtin_supervisor import WslcBuiltinSupervisor


def test_failed_row_has_inline_help_and_other_rows_show_only_results(qapp):
    widget = WindowsSetupChecks()
    rows = failed_checks(setup_checks({'firmware': False, 'feature': 1}, True, (3, 0, 3)), 'bios')
    widget.set_checks(rows)
    assert set(widget.labels) == {'wsl', 'version', 'virtualization', 'platform', 'image', 'server'}
    assert 'Passed:' in widget.labels['wsl'].accessibleName()
    assert 'Pending:' in widget.labels['server'].accessibleName()
    assert set(widget.help_labels) == {'virtualization'}
    assert 'BIOS/UEFI' in widget.help_labels['virtualization'].text()
    assert widget.buttons['bios'].text() == 'How to turn it on'
    assert 'checks are off' not in ' '.join(label.text() for label in widget.labels.values())


def test_bios_help_opens_instructions_without_running_windows_setup(tmp_path, qapp, monkeypatch):
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle')
    supervisor.setup_issue = WslcPrerequisiteError('Virtualization off', 'bios')
    calls = []
    urls = []
    monkeypatch.setattr(QProcess, 'start', lambda *args: calls.append(args))
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: urls.append(url.toString()))
    dialog = WindowsBackendSetup(supervisor)
    dialog.checklist.buttons['bios'].click()
    assert calls == []
    assert len(urls) == 1 and urls[0].startswith('https://support.microsoft.com/')
    dialog.reject()


def test_inline_windows_feature_button_runs_real_repair_command(tmp_path, qapp, monkeypatch):
    supervisor = WslcBuiltinSupervisor(tmp_path / 'config', tmp_path / 'bundle')
    supervisor.setup_issue = WslcPrerequisiteError('Feature off', 'repair')
    calls = []
    monkeypatch.setattr(QProcess, 'start', lambda self, program, args: calls.append((program, args)))
    monkeypatch.setattr('tvhplayer.windows_backend_setup.shutil.which', lambda name: 'powershell.exe')
    dialog = WindowsBackendSetup(supervisor)
    assert calls == []
    dialog.checklist.buttons['repair'].click()
    assert len(calls) == 1
    assert 'dism.exe' in calls[0][1][-1]
    assert '/featurename:VirtualMachinePlatform' in calls[0][1][-1]
    assert '-Verb RunAs' in calls[0][1][-1]
    dialog.reject()


def test_channel_checklist_is_hidden_during_normal_startup_and_remote_messages(qapp):
    from tvhplayer.tvhplayer import ChannelListState
    state = ChannelListState()
    assert state.checklist.isHidden()
    state.checklist.set_checks(failed_checks([], 'bios'))
    state.checklist.show()
    state.show_state('Connecting to the living room server', busy=True)
    assert state.checklist.isHidden()


def test_diagnostics_are_collapsed_copyable_and_redacted(qapp):
    from PyQt6.QtWidgets import QApplication
    widget = WindowsSetupChecks()
    widget.set_checks(failed_checks([], 'diagnose'))
    widget.set_diagnostics('Cannot secure the backend: password=private-value token=private-token')
    assert widget.details_text.isReadOnly()
    assert widget.details_text.isHidden()
    widget.details_toggle.click()
    assert not widget.details_text.isHidden()
    assert 'private-value' not in widget.details_text.toPlainText()
    widget.copy_details.click()
    assert QApplication.clipboard().text() == widget.details_text.toPlainText()
    widget.set_checks(failed_checks([], 'image'))
    qapp.processEvents()
    widget.set_checks(failed_checks([], 'diagnose'))
    assert 'Cannot secure the backend' in widget.details_text.toPlainText()


def test_import_timeout_is_not_misclassified_as_port_conflict():
    from tvhplayer.windows_setup_checks import problem_summary
    assert 'too long' in problem_summary('Image import timed out')

"""Tests for showing files in the desktop file manager."""
import os

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtDBus import QDBusUnixFileDescriptor

from tvhplayer import file_manager


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "recording.ts"
    path.write_bytes(b"ts")
    return path


def _session_bus(monkeypatch, *answers):
    answers = list(answers)
    calls = []

    def call(_service, _path, interface, method, arguments):
        calls.append((interface, method, arguments))
        return answers.pop(0)

    monkeypatch.setattr(file_manager, "_call_session_bus", call)
    return calls


def test_linux_asks_the_portal_to_show_the_file(monkeypatch, recording):
    calls = _session_bus(monkeypatch, True)
    monkeypatch.setattr(file_manager.QDesktopServices, "openUrl", lambda url: False)

    assert file_manager.show_in_file_manager(str(recording), "linux") is True

    ((interface, method, arguments),) = calls
    assert (interface, method) == ("org.freedesktop.portal.OpenURI", "OpenDirectory")
    assert arguments[0] == ""
    assert isinstance(arguments[1], QDBusUnixFileDescriptor)
    assert arguments[2] == {}


def test_linux_falls_back_to_the_file_manager_then_the_folder(monkeypatch, recording):
    calls = _session_bus(monkeypatch, False, True)
    opened = []
    monkeypatch.setattr(
        file_manager.QDesktopServices, "openUrl", lambda url: opened.append(url) or False
    )

    assert file_manager.show_in_file_manager(str(recording), "linux") is True
    assert calls[1] == (
        "org.freedesktop.FileManager1",
        "ShowItems",
        [[QUrl.fromLocalFile(str(recording)).toString()], ""],
    )
    assert opened == []

    calls = _session_bus(monkeypatch, False, False)
    opened.clear()
    monkeypatch.setattr(
        file_manager.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url) or True,
    )
    assert file_manager.show_in_file_manager(str(recording), "linux") is True
    assert opened == [QUrl.fromLocalFile(str(recording.parent))]


def test_windows_and_macos_select_the_file(monkeypatch, recording):
    calls = _session_bus(monkeypatch)
    started = []

    def start(program, arguments):
        started.append((program, arguments))
        return True

    monkeypatch.setattr(file_manager, "_start_detached", start)
    assert file_manager.show_in_file_manager(str(recording), "win32") is True
    assert file_manager.show_in_file_manager(str(recording), "darwin") is True
    assert started == [
        ("explorer", ["/select,", os.path.normpath(str(recording))]),
        ("open", ["-R", str(recording)]),
    ]
    assert calls == []


def test_missing_files_are_not_shown(monkeypatch, recording):
    _session_bus(monkeypatch)
    opened = []
    monkeypatch.setattr(
        file_manager.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
    )
    missing = recording.with_name("gone.ts")
    assert file_manager.show_in_file_manager(str(missing), "linux") is False
    assert opened == []

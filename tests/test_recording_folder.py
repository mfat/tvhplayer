import errno
import os

import pytest

from tvhplayer.core import recording_folder


def test_write_probe_creates_directory_and_leaves_no_files(tmp_path):
    folder = tmp_path / 'recordings'
    recording_folder.validate_recording_folder(str(folder))
    assert list(folder.iterdir()) == []


def test_flatpak_probe_never_creates_missing_directory(tmp_path):
    folder = tmp_path / 'missing'
    with pytest.raises(FileNotFoundError):
        recording_folder.validate_recording_folder(str(folder), create_missing=False)
    assert not folder.exists()


def test_error_identifies_destination_instead_of_random_probe(tmp_path):
    folder = tmp_path / 'missing'
    with pytest.raises(FileNotFoundError) as caught:
        recording_folder.validate_recording_folder(str(folder), create_missing=False)
    assert caught.value.filename == str(folder)
    assert 'write-check-' not in str(caught.value)


@pytest.mark.parametrize('error', [errno.EACCES, errno.EROFS, errno.ENOSPC])
def test_failed_write_is_rejected_even_when_access_reports_writable(monkeypatch, tmp_path, error):
    monkeypatch.setattr(os, 'access', lambda *_args: True)

    def fail(*_args, **_kwargs):
        raise OSError(error, os.strerror(error), str(tmp_path))

    monkeypatch.setattr(recording_folder.tempfile, 'NamedTemporaryFile', fail)
    with pytest.raises(OSError) as caught:
        recording_folder.validate_recording_folder(str(tmp_path))
    assert caught.value.errno == error


def test_disk_full_during_flush_cleans_up_probe(monkeypatch, tmp_path):
    def full(_fd):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(recording_folder.os, 'fsync', full)
    with pytest.raises(OSError) as caught:
        recording_folder.validate_recording_folder(str(tmp_path))
    assert caught.value.errno == errno.ENOSPC
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == 'nt' or getattr(os, 'geteuid', lambda: 0)() == 0,
                    reason='Requires POSIX permissions and an unprivileged user')
def test_real_read_only_directory(tmp_path):
    folder = tmp_path / 'read-only'
    folder.mkdir(mode=0o555)
    try:
        with pytest.raises(PermissionError):
            recording_folder.validate_recording_folder(str(folder))
    finally:
        folder.chmod(0o755)


def test_portal_display_uses_host_path_only_for_presentation(monkeypatch):
    folder = '/run/user/1000/doc/abc/RECORDINGS'
    monkeypatch.setattr(os, 'getxattr', lambda *_: b'/media/Storage/RECORDINGS\0', raising=False)
    assert recording_folder.recording_folder_display(folder) == '/media/Storage/RECORDINGS'


def test_disconnected_drive_keeps_saved_display(monkeypatch):
    def missing(*_):
        raise FileNotFoundError()
    monkeypatch.setattr(os, 'getxattr', missing, raising=False)
    folder = '/run/user/1000/doc/abc/RECORDINGS'
    assert recording_folder.recording_folder_display(folder, '/media/Storage/RECORDINGS') == '/media/Storage/RECORDINGS'
    assert recording_folder.recording_folder_display(folder) == 'RECORDINGS'
    assert recording_folder.recording_folder_display('/home/user/Videos', 'old') == '/home/user/Videos'


@pytest.mark.parametrize('code', [errno.ENOENT, errno.ENOTCONN, errno.ENODEV, errno.ESTALE])
def test_unavailable_portal_folder_explains_drive_recovery(code):
    message = recording_folder.recording_folder_error('/run/user/1000/doc/abc/RECORDINGS', OSError(code, 'failure'))
    assert 'mount the drive' in message
    assert 'Browse' in message
    assert 'kept' in message


def test_disk_full_is_not_reported_as_lost_access():
    error = OSError(errno.ENOSPC, 'No space left on device')
    assert recording_folder.recording_folder_error('/run/user/1000/doc/abc/RECORDINGS', error) == str(error)


@pytest.mark.parametrize('suffix,expected', [
    ('/RECORDINGS', '/media/Storage/RECORDINGS'),
    ('/RECORDINGS/TV', '/media/Storage/RECORDINGS/TV'),
    ('', '/media/Storage/RECORDINGS'),
])
def test_gethostpaths_recovers_display_when_drive_is_missing(monkeypatch, suffix, expected):
    def missing(*_):
        raise FileNotFoundError()
    monkeypatch.setattr(os, 'getxattr', missing, raising=False)
    requested = []
    def lookup(doc_id):
        requested.append(doc_id)
        return '/media/Storage/RECORDINGS'
    folder = '/run/user/1000/doc/abc' + suffix
    assert recording_folder.recording_folder_display(folder, '', lookup) == expected
    assert requested == ['abc']


def test_older_portal_keeps_saved_display(monkeypatch):
    def missing(*_):
        raise FileNotFoundError()
    monkeypatch.setattr(os, 'getxattr', missing, raising=False)
    assert recording_folder.recording_folder_display(
        '/run/user/1000/doc/abc/Recordings', '/media/Recordings', lambda _: '') == '/media/Recordings'

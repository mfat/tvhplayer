"""Validate recording destinations using the same filesystem operations as a writer."""

import errno
import os
import tempfile


def validate_recording_folder(folder, *, create_missing=True):
    """Raise OSError if a temporary recording cannot be written and removed.

    Flatpak callers disable directory creation to avoid making an apparently
    usable destination in the sandbox's transient home directory.
    """
    if not folder:
        raise OSError(errno.ENOENT, 'Choose a folder for recordings', folder)
    try:
        if create_missing:
            os.makedirs(folder, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.tvhplayer-write-check-', dir=folder) as probe:
            probe.write(b'TVHplayer recording folder check\n')
            probe.flush()
            os.fsync(probe.fileno())
    except OSError as exc:
        # Explain the destination, rather than showing a random probe filename.
        raise OSError(exc.errno, exc.strerror or str(exc), os.fspath(folder)) from exc

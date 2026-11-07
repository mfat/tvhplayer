"""Validate recording destinations using the same filesystem operations as a writer."""

import errno
import os
import re
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


def is_portal_folder(folder):
    """Whether a path belongs to a document-portal grant."""
    return bool(re.match(r'^/run/(?:user/\d+|flatpak)/doc/[^/]+(?:/|$)', folder or ''))


def recording_folder_display(folder, saved_display='', host_lookup=None):
    """Use the host name for display only; writers must keep the portal path."""
    if not is_portal_folder(folder):
        return folder
    try:
        host = os.fsdecode(os.getxattr(folder, 'user.document-portal.host-path')).rstrip('\0')
        if host:
            return host
    except (AttributeError, OSError):
        pass
    if host_lookup is not None:
        match = re.match(r'^/run/(?:user/\d+|flatpak)/doc/([^/]+)(?:/(.*))?$', folder)
        if match:
            host = host_lookup(match[1])
            if host:
                tail = (match[2] or '').split('/')
                # The first component names the exported entry, not a child.
                if tail[0] == os.path.basename(host.rstrip('/')):
                    return os.path.join(host, *tail[1:])
                if not match[2]:
                    return host
    return saved_display or os.path.basename(folder.rstrip('/'))


def recording_folder_error(folder, error):
    """Explain unavailable grants without implying that access was revoked."""
    if is_portal_folder(folder):
        if error.errno in (errno.ENOENT, errno.ENOTCONN, errno.ENODEV, errno.ESTALE):
            return ('The selected folder is unavailable. If it is on an external drive, '
                    'connect and mount the drive. If the folder was moved or access was removed, '
                    'use Browse to select it again. Your folder selection has been kept.')
        if error.errno in (errno.EACCES, errno.EPERM):
            return 'Access to this folder is denied. Use Browse to select it again and grant access.'
    return str(error)

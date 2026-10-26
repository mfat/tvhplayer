"""Free space where recordings are saved. No Qt imports."""

from __future__ import annotations

import shutil
from typing import Optional

GB = 1000 ** 3


def free_bytes(folder: str) -> Optional[int]:
    """Free space on the disk holding ``folder``, or None when it cannot be read."""
    if not folder:
        return None
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def format_size(num_bytes: int) -> str:
    if num_bytes >= 100 * GB:
        return f'{num_bytes / GB:.0f} GB'
    if num_bytes >= GB:
        return f'{num_bytes / GB:.1f} GB'
    return f'{num_bytes / 1000 ** 2:.0f} MB'


def low_space_message(free: Optional[int], limit_gb: int) -> str:
    """A warning when less than ``limit_gb`` is free, else ''. A limit of 0 never warns."""
    if free is None or limit_gb <= 0 or free >= limit_gb * GB:
        return ''
    return f'Only {format_size(free)} free for recordings'

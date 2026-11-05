"""Runtime selection without importing Qt or starting WSL during app startup."""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path


def windows_backend_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'backend'
    return Path(__file__).resolve().parents[2] / 'windows' / 'backend' / 'dist'


def windows_backend_enabled() -> bool:
    if sys.platform != 'win32':
        return False
    override = os.environ.get('TVHPLAYER_EXPERIMENTAL_WSLC')
    if override in ('0', '1'):
        return override == '1'
    # A complete packaged backend is installable even before WSL is installed.
    # Hash the archive on first use, not while launching the remote-server UI.
    from .backend_bundle import TVHEADEND_COMMIT
    try:
        manifest = json.loads((windows_backend_dir() / 'manifest.json').read_text(encoding='utf-8-sig'))
        return (manifest.get('schema') == 2 and manifest.get('architecture') == 'amd64'
                and manifest.get('tvheadend_commit') == TVHEADEND_COMMIT)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def create_supervisor(binary, config_dir, http_port=0, htsp_port=0):
    if windows_backend_enabled():
        try:
            from ..wslc_builtin_supervisor import WslcBuiltinSupervisor
        except ImportError:
            from wslc_builtin_supervisor import WslcBuiltinSupervisor
        return WslcBuiltinSupervisor(config_dir, windows_backend_dir(), http_port, htsp_port)
    try:
        from ..builtin_supervisor import BuiltinSupervisor
    except ImportError:
        from builtin_supervisor import BuiltinSupervisor
    return BuiltinSupervisor(binary, config_dir, http_port, htsp_port)

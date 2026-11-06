"""Read-only Windows prerequisite checks and persisted first-run progress."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


def setup_file(config_dir):
    return Path(config_dir).parent / 'wslc-setup.json'


def pending_setup(config_dir):
    try:
        data = json.loads(setup_file(config_dir).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and data.get('schema') == 1 else None
    except (OSError, ValueError):
        return None


def save_setup(config_dir, stage, action):
    path = setup_file(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'schema': 1, 'stage': stage, 'action': action,
                                     'boot_time': windows_boot_time()}), encoding='utf-8')
    temporary.replace(path)


def windows_boot_time():
    try:
        import ctypes
        uptime = ctypes.windll.kernel32.GetTickCount64
        uptime.restype = ctypes.c_ulonglong
        return time.time() - uptime() / 1000
    except (AttributeError, OSError):
        return None


def restart_still_required(config_dir):
    pending = pending_setup(config_dir) or {}
    previous, current = pending.get('boot_time'), windows_boot_time()
    return (pending.get('stage') == 'restart_required' and
            isinstance(previous, (float, int)) and current is not None and
            abs(previous - current) < 2)


def probe_windows(runner=subprocess.run):
    """CIM queries need no elevation. Unknown data never masquerades as disabled."""
    script = r"""$ErrorActionPreference = 'Stop'
 $feature = Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform'"
 $computer = Get-CimInstance Win32_ComputerSystem
 $cpu = @(Get-CimInstance Win32_Processor)
 $pending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
 @{feature = $feature.InstallState; hypervisor = $computer.HypervisorPresent;
   firmware = $cpu[0].VirtualizationFirmwareEnabled; reboot_pending = $pending} | ConvertTo-Json -Compress
 """
    try:
        result = runner(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                        capture_output=True, encoding='utf-8', errors='replace', timeout=20,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        data = json.loads(result.stdout) if result.returncode == 0 else {}
        return data if isinstance(data, dict) else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def prerequisite_issue(state):
    """Return a specific next step only when the probe establishes the blocker."""
    if state.get('firmware') is False and state.get('hypervisor') is not True:
        return ('Hardware virtualization is disabled or unavailable. Enable Intel VT-x or '
                'AMD-V / SVM in BIOS/UEFI, then restart Windows. In Task Manager > '
                'Performance > CPU, Virtualization should say Enabled. If Windows runs '
                'inside a virtual machine, ask its host administrator to enable nested virtualization.', 'bios')
    if state.get('reboot_pending') is True and state.get('hypervisor') is not True:
        return ('Windows has pending feature changes. Save your work and restart Windows '
                '(restarting TVHplayer is not enough), then reopen TVHplayer to resume setup.', 'reboot')
    if state.get('feature') in (2, 3):
        return ('Virtual Machine Platform is disabled. Choose Enable Virtual Machine Platform, '
                'accept the administrator prompt, then restart Windows even if no reboot prompt appears.', 'repair')
    return None

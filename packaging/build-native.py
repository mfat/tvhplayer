#!/usr/bin/env python3
"""Compile the C decoder tvhplayer/core/_htsmsg.c next to the Python code.

Every package runs this before copying tvhplayer/, with the Python it ships:

    python3 packaging/build-native.py

On Linux and macOS it compiles with the compiler and flags that Python was
built with (sysconfig) plus CFLAGS/LDFLAGS from the environment, so no
setuptools is needed. On Windows it uses setuptools' build_ext (MSVC).
It then imports the module and decodes a message, and exits non-zero if
anything fails: without the module the app still works, but decodes large
channel lists several times slower, so a package must not lose it unnoticed.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tvhplayer' / 'core' / '_htsmsg.c'
TARGET = SOURCE.with_name('_htsmsg' + sysconfig.get_config_var('EXT_SUFFIX'))


def run(command):
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, check=True)


def build_posix():
    cc = shlex.split(sysconfig.get_config_var('CC') or 'cc')
    ldshared = shlex.split(sysconfig.get_config_var('LDSHARED') or 'cc -shared')
    cflags = shlex.split(sysconfig.get_config_var('CCSHARED') or '-fPIC')
    cflags += ['-O2', '-Wall', '-I' + sysconfig.get_paths()['include']]
    cflags += shlex.split(os.environ.get('CPPFLAGS', '')) + shlex.split(os.environ.get('CFLAGS', ''))
    ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    obj = TARGET.with_suffix('.o')
    try:
        run(cc + cflags + ['-c', str(SOURCE), '-o', str(obj)])
        run(ldshared + [str(obj)] + ldflags + ['-o', str(TARGET)])
    finally:
        if obj.exists():
            obj.unlink()


def build_windows():
    run([sys.executable, str(ROOT / 'setup.py'), 'build_ext', '--inplace'])


def check():
    """Load the built module and decode a message as the Python decoder does.

    Both are loaded from their files, without the rest of the app, whose
    dependencies a package build may not have on its path yet.
    """
    code = (
        'import importlib.util, sys\n'
        'def load(name, path):\n'
        '    spec = importlib.util.spec_from_file_location(name, path)\n'
        '    module = importlib.util.module_from_spec(spec)\n'
        '    spec.loader.exec_module(module)\n'
        '    return module\n'
        'native = load("_htsmsg", sys.argv[1])\n'
        'python = load("htsmsg_check", sys.argv[2])\n'
        'native.set_binary_type(python.Binary)\n'
        'm = {"channelName": "Test \\u2713", "channelNumber": -1, "services": [{"type": "SDTV"}],\n'
        '     "tags": [1, 2], "on": True, "x": 0.5, "blob": python.Binary(b"\\x00\\xff")}\n'
        'body = python.serialize(m)[4:]\n'
        'assert native.deserialize(body, False) == python.python_deserialize(body) == m\n'
        'print("C decoder:", sys.argv[1])\n'
    )
    subprocess.run([sys.executable, '-c', code, str(TARGET),
                    str(ROOT / 'tvhplayer' / 'core' / 'htsmsg.py')], check=True)


def main():
    if os.name == 'nt':
        build_windows()
    else:
        build_posix()
    check()


if __name__ == '__main__':
    main()

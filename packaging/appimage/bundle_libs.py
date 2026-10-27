"""Copy the shared libraries that ELF files need into a folder of the AppImage.

    bundle_libs.py EXCLUDELIST DEST [--link] FILE...

Each library ``ldd`` resolves outside the AppDir goes to DEST, unless the
excludelist says the host provides it. Copied libraries look next to
themselves first. With ``--link``, the FILEs also get DEST on their run path;
without it they must already find DEST, as PyQt's Qt files find Qt6/lib.
"""

import os
import re
import shutil
import subprocess
import sys

LDD_LINE = re.compile(r'^\s*(\S+) => (\S+) \(0x[0-9a-f]+\)$')


def excluded_names(path):
    names = set()
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.split('#', 1)[0].strip()
            if line:
                names.add(line)
    return names


def dependencies(elf):
    """``(name, path)`` for each library ``ldd`` finds, and the names it cannot find."""
    result = subprocess.run(['ldd', elf], capture_output=True, text=True, check=False)
    found, missing = [], []
    for line in result.stdout.splitlines():
        match = LDD_LINE.match(line)
        if match:
            found.append((match.group(1), match.group(2)))
        elif 'not found' in line:
            missing.append(line.split()[0])
    return found, missing


def patchelf(*args):
    subprocess.run(['patchelf', *args], check=True)


def add_run_path(elf, folder):
    relative = os.path.relpath(folder, os.path.dirname(os.path.abspath(elf)))
    entry = '$ORIGIN' if relative == '.' else f'$ORIGIN/{relative}'
    patchelf('--add-rpath', entry, elf)


def main(argv):
    excludelist, dest, *files = argv
    link = '--link' in files
    files = [f for f in files if f != '--link']
    excluded = excluded_names(excludelist)
    appdir = os.path.abspath(os.environ['APPDIR'])
    os.makedirs(dest, exist_ok=True)
    copied, missing = 0, set()
    for elf in files:
        found, not_found = dependencies(elf)
        missing.update(not_found)
        for name, path in found:
            if name in excluded or os.path.abspath(path).startswith(appdir + os.sep):
                continue
            target = os.path.join(dest, name)
            if os.path.exists(target):
                continue
            shutil.copy2(os.path.realpath(path), target)
            os.chmod(target, 0o755)
            patchelf('--set-rpath', '$ORIGIN', target)
            copied += 1
        if link:
            add_run_path(elf, dest)
    print(f'bundle_libs: {len(files)} files, {copied} libraries copied to {dest}')
    # The host provides what the excludelist names; anything else would be missing there too.
    missing -= excluded
    for name in sorted(missing):
        print(f'bundle_libs: not found on the build system: {name}')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

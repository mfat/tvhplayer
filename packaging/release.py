"""Release helpers for .github/workflows/release.yml and flathub.yml.

    release.py check VERSION              print the current version; fail unless VERSION is higher
    release.py bump VERSION DATE < NOTES  write VERSION into the app, setup.py, rpm.spec and the
                                          metainfo, with NOTES (one per line) as the release notes
    release.py flathub-pin MANIFEST TAG COMMIT
                                          point the manifest's TVHplayer source at TAG and COMMIT

debian/changelog is stamped by the package build, not here.
"""

import datetime
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

APP = 'tvhplayer/tvhplayer.py'
SETUP = 'setup.py'
SPEC = 'rpm.spec'
METAINFO = 'io.github.mfat.tvhplayer.metainfo.xml'

VERSION = re.compile(r'^\d+(\.\d+){1,2}$')
APP_VERSION = re.compile(r'^APP_VERSION = "([^"]+)"$', re.M)
SETUP_VERSION = re.compile(r'^(\s*version=)"([^"]+)",$', re.M)
SPEC_VERSION = re.compile(r'^Version:(\s+)(\S+)$', re.M)
APP_SOURCE = re.compile(
    r'^([ \t]*)url: "?https://github\.com/mfat/tvhplayer\.git"?[ \t]*\n'
    r'(?:[ \t]*tag:[^\n]*\n)?'
    r'[ \t]*commit:[ \t]*[0-9a-fA-F]+[ \t]*$',
    re.M,
)


class ReleaseError(Exception):
    pass


def _key(version):
    return tuple(int(part) for part in version.split('.')) + (0,) * (3 - version.count('.') - 1)


def current_version(root):
    root = Path(root)
    found = {
        APP: APP_VERSION.search((root / APP).read_text(encoding='utf-8')),
        SETUP: SETUP_VERSION.search((root / SETUP).read_text(encoding='utf-8')),
        SPEC: SPEC_VERSION.search((root / SPEC).read_text(encoding='utf-8')),
    }
    versions = {name: match.group(match.re.groups) for name, match in found.items() if match}
    if len(versions) != len(found):
        raise ReleaseError(f'No version found in {", ".join(sorted(set(found) - set(versions)))}')
    if len(set(versions.values())) != 1:
        raise ReleaseError(f'The files disagree on the version: {versions}')
    return versions[APP]


def check_version(root, version):
    """Return the current version; raise unless ``version`` is a valid, higher one."""
    current = current_version(root)
    if not VERSION.match(version or ''):
        raise ReleaseError(f'"{version}" is not a version like 4.1 or 4.1.2')
    if _key(version) <= _key(current):
        raise ReleaseError(f'{version} is not higher than the current {current}')
    return current


def _replace(path, pattern, replacement):
    text = path.read_text(encoding='utf-8')
    new, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ReleaseError(f'Could not update {path.name}')
    path.write_text(new, encoding='utf-8')


def bump(root, version, date, notes):
    root = Path(root)
    notes = [line.strip() for line in notes if line.strip()]
    if not notes:
        raise ReleaseError('The release notes are empty')
    day = datetime.date.fromisoformat(date)

    _replace(root / APP, APP_VERSION, f'APP_VERSION = "{version}"')
    _replace(root / SETUP, SETUP_VERSION, lambda m: f'{m.group(1)}"{version}",')
    _replace(root / SPEC, SPEC_VERSION, lambda m: f'Version:{m.group(1)}{version}')
    entry = f'* {day.strftime("%a %b %d %Y")} mFat <newmfat@gmail.com> - {version}-1\n'
    entry += ''.join(f'- {line}\n' for line in notes)
    _replace(root / SPEC, re.compile(r'^%changelog\n', re.M), lambda m: f'%changelog\n{entry}\n')

    items = ''.join(f'          <li>{escape(line)}</li>\n' for line in notes)
    release = (
        f'    <release version="{version}" date="{date}">\n'
        '      <description>\n'
        '        <ul>\n'
        f'{items}'
        '        </ul>\n'
        '      </description>\n'
        '    </release>\n'
    )
    _replace(root / METAINFO, re.compile(r'^  <releases>\n', re.M), lambda m: f'  <releases>\n{release}')


def flathub_pin(manifest, tag, commit):
    """``manifest`` with the TVHplayer git source pinned to ``tag`` and ``commit``."""
    def pin(match):
        indent = match.group(1)
        return (
            f'{indent}url: "https://github.com/mfat/tvhplayer.git"\n'
            f'{indent}tag: {tag}\n'
            f'{indent}commit: {commit}'
        )

    pinned, count = APP_SOURCE.subn(pin, manifest)
    if count != 1:
        raise ReleaseError(f'Expected one TVHplayer git source in the manifest, found {count}')
    return pinned


def main(argv):
    command, *args = argv or ['']
    root = Path.cwd()
    if command == 'check' and len(args) == 1:
        print(check_version(root, args[0]))
    elif command == 'bump' and len(args) == 2:
        bump(root, args[0], args[1], sys.stdin.read().splitlines())
    elif command == 'flathub-pin' and len(args) == 3:
        path = Path(args[0])
        path.write_text(flathub_pin(path.read_text(encoding='utf-8'), args[1], args[2]), encoding='utf-8')
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except ReleaseError as error:
        print(f'release.py: {error}', file=sys.stderr)
        sys.exit(1)

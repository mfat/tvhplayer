import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging'))
import release  # noqa: E402

FILES = ('tvhplayer/tvhplayer.py', 'setup.py', 'rpm.spec', 'io.github.mfat.tvhplayer.metainfo.xml')


@pytest.fixture
def tree(tmp_path):
    for name in FILES + ('io.github.mfat.tvhplayer.yml',):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, target)
    return tmp_path


def test_current_version_agrees_across_files(tree):
    assert release.current_version(tree) == release.current_version(ROOT)


def test_a_new_version_must_be_higher(tree):
    current = release.current_version(tree)
    major = int(current.split('.')[0])
    assert release.check_version(tree, f'{major + 1}.0') == current
    for wrong in (current, '1.0', 'v9', '9.x', ''):
        with pytest.raises(release.ReleaseError):
            release.check_version(tree, wrong)


def test_bump_writes_the_version_and_notes_everywhere(tree):
    release.bump(tree, '99.1', '2027-01-02', ['Faster guide', 'Fixes for <tags> & such'])
    assert release.current_version(tree) == '99.1'
    assert 'APP_VERSION = "99.1"' in (tree / 'tvhplayer/tvhplayer.py').read_text()
    assert 'version="99.1",' in (tree / 'setup.py').read_text()
    spec = (tree / 'rpm.spec').read_text()
    assert 'Version:        99.1\n' in spec
    assert '%changelog\n* Sat Jan 02 2027 mFat <newmfat@gmail.com> - 99.1-1\n- Faster guide\n' in spec
    metainfo = (tree / 'io.github.mfat.tvhplayer.metainfo.xml').read_text()
    newest = metainfo.index('<release version="99.1" date="2027-01-02">')
    assert newest < metainfo.index('<release version="4.0"')
    assert '<li>Fixes for &lt;tags&gt; &amp; such</li>' in metainfo


def test_bump_needs_notes(tree):
    with pytest.raises(release.ReleaseError):
        release.bump(tree, '99.1', '2027-01-02', ['  '])


def test_flathub_pin_points_the_app_source_at_the_tag(tree):
    manifest = (tree / 'io.github.mfat.tvhplayer.yml').read_text()
    sha = 'a' * 40
    pinned = release.flathub_pin(manifest, 'v99.1', sha)
    source = pinned[pinned.index('url: "https://github.com/mfat/tvhplayer.git"'):]
    assert source.splitlines()[1:3] == [f'        tag: v99.1', f'        commit: {sha}']
    # Only the app's own source changes.
    assert pinned.count(sha) == 1
    assert len(pinned.splitlines()) == len(manifest.splitlines())


def test_flathub_pin_adds_a_missing_tag_line():
    manifest = 'sources:\n  - type: git\n    url: "https://github.com/mfat/tvhplayer.git"\n    commit: 1234abcd\n'
    pinned = release.flathub_pin(manifest, 'v5.0', 'b' * 40)
    assert pinned.endswith(f'    url: "https://github.com/mfat/tvhplayer.git"\n    tag: v5.0\n    commit: {"b" * 40}\n')

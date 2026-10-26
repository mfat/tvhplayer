"""The Flatpak, deb, and rpm packages must carry the same built-in Tvheadend."""

import shlex
from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / 'packaging' / 'tvheadend' / 'pins.env'
MANIFEST = ROOT / 'io.github.mfat.tvhplayer.yml'


def load_pins():
    pins = {}
    for line in PINS.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, _, value = line.partition('=')
        pins[key] = ' '.join(shlex.split(value))
    return pins


def manifest_module(name):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding='utf-8'))
    for module in manifest['modules']:
        if isinstance(module, dict) and module.get('name') == name:
            return module
    raise AssertionError(f'{name} is not a module in {MANIFEST.name}')


def test_flatpak_builds_the_pinned_tvheadend():
    pins = load_pins()
    module = manifest_module('tvheadend')
    git = next(source for source in module['sources'] if source['type'] == 'git')
    assert git['url'] == pins['TVHEADEND_REPO'] + '.git'
    assert git['commit'] == pins['TVHEADEND_COMMIT']
    scan = next(source for source in module['sources'] if source.get('dest') == 'data/dvb-scan')
    assert pins['DTV_SCAN_TABLES_COMMIT'] in scan['url']
    assert scan['sha256'] == pins['DTV_SCAN_TABLES_SHA256']
    assert module['config-opts'] == pins['TVHEADEND_CONFIGURE_FLAGS'].split()


def test_flatpak_builds_the_pinned_libdvbcsa():
    pins = load_pins()
    archive = manifest_module('libdvbcsa')['sources'][0]
    assert f"libdvbcsa-{pins['LIBDVBCSA_VERSION']}.tar.gz" in archive['url']
    assert archive['sha256'] == pins['LIBDVBCSA_SHA256']


def test_flatpak_builds_the_pinned_libhdhomerun():
    pins = load_pins()
    archive = manifest_module('libhdhomerun')['sources'][0]
    assert archive['url'].endswith(f"/libhdhomerun_{pins['LIBHDHOMERUN_VERSION']}.tgz")
    assert archive['sha256'] == pins['LIBHDHOMERUN_SHA256']


SPEC = ROOT / 'rpm.spec'
PYPI_DEPENDENCIES = ROOT / 'pypi-dependencies.yaml'


def spec_globals():
    values = {}
    for line in SPEC.read_text(encoding='utf-8').splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == '%global':
            values[parts[1]] = parts[2]
    return values


def test_rpm_builds_the_pinned_tvheadend():
    pins = load_pins()
    spec = spec_globals()
    assert spec['tvh_repo'] == pins['TVHEADEND_REPO']
    assert spec['tvh_commit'] == pins['TVHEADEND_COMMIT']
    assert spec['scan_commit'] == pins['DTV_SCAN_TABLES_COMMIT']
    assert spec['dvbcsa_version'] == pins['LIBDVBCSA_VERSION']
    assert spec['hdhomerun_version'] == pins['LIBHDHOMERUN_VERSION']
    # rpm spells 4.3-2901~gcc1b558b5 as 4.3^2901.gcc1b558b5.
    assert spec['tvh_version'] == pins['TVHEADEND_VERSION'].replace('-', '^').replace('~', '.')


def test_rpm_bundles_the_flatpak_python_vlc():
    spec = spec_globals()
    modules = yaml.safe_load(PYPI_DEPENDENCIES.read_text(encoding='utf-8'))['modules']
    wheel = next(
        source
        for module in modules if module['name'] == 'python3-python-vlc'
        for source in module['sources']
    )
    assert wheel['url'].endswith('/' + spec['vlc_wheel'])
    assert wheel['sha256'] == spec['vlc_wheel_sha256']
    assert wheel['url'] in SPEC.read_text(encoding='utf-8').replace('%{vlc_wheel}', spec['vlc_wheel'])

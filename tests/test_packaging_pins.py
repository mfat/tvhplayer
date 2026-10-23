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

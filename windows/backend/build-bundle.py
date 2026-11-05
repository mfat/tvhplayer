"""Build the runtime and complete offline release bundle with Docker or WSLc."""
import argparse
import ipaddress
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tvhplayer.core.backend_bundle import TVHEADEND_COMMIT, RELEASE_ARTIFACTS, file_digest, verify_bundle


def build(engine, output, dns=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    pins = (ROOT / 'packaging/tvheadend/pins.env').read_text()
    if re.search(r'^TVHEADEND_COMMIT=(\w+)$', pins, re.M)[1] != TVHEADEND_COMMIT:
        raise ValueError('Update the runtime source pin alongside packaging/tvheadend/pins.env')
    wslc = Path(engine).stem.lower() == 'wslc'
    tag = 'tvhplayer-backend:' + TVHEADEND_COMMIT
    def command(*args):
        subprocess.run([engine, *map(str, args)], check=True)
    def prepare_dns():
        if dns:
            if not wslc:
                raise ValueError('--dns is a WSLc session workaround; configure your Docker builder DNS separately')
            address = str(ipaddress.IPv4Address(dns))
            # Explicit build-host option, never called by the application runtime.
            # Refresh before each build because WSLc can recycle an idle session
            # during archive export. This does not change Windows adapter settings.
            command('system', 'session', 'run', 'sh', '-c', f'echo nameserver {address} > /etc/resolv.conf')
    # WSLc may enumerate excluded files before applying .dockerignore. Use an
    # isolated build context to avoid unrelated NTFS ACLs and private files.
    with tempfile.TemporaryDirectory(prefix='tvhplayer-backend-') as temporary:
        context = Path(temporary)
        packaging = context / 'packaging/tvheadend'
        packaging.mkdir(parents=True)
        for path in (ROOT / 'packaging/tvheadend').iterdir():
            if path.suffix == '.sh' or path.name == 'pins.env':
                shutil.copy2(path, packaging / path.name)
        backend = context / 'windows/backend'
        backend.mkdir(parents=True)
        for name in ('Containerfile', 'debian.sources', 'base-sources.sources', 'entrypoint.sh'):
            # Normalize Windows checkouts before sending the context to Linux.
            data = (ROOT / 'windows/backend' / name).read_text(encoding='utf-8')
            (backend / name).write_text(data, encoding='utf-8', newline='\n')
        build_args = ['build', '--progress', 'plain', '-f', str(backend / 'Containerfile')]
        if not wslc:
            build_args += ['--platform', 'linux/amd64']
        prepare_dns()
        command(*build_args, '-t', tag, context)
        command('save', '--output', output / 'tvheadend.tar', tag)
        raw = subprocess.check_output([engine, 'inspect', '--type', 'image', tag], text=True)
        image = json.loads(raw)[0]['Id']
        exported = output / 'source-export.tar'
        prepare_dns()
        command(*build_args, '--target', 'source-export', '--output', f'type=tar,dest={exported}', context)
        with tarfile.open(exported) as archive:
            for member in archive:
                name = Path(member.name).name
                if name in {'packages.tsv', 'licenses.tar.gz', 'corresponding-source.tar.gz'} and member.isfile():
                    with archive.extractfile(member) as source, (output / name).open('wb') as target:
                        shutil.copyfileobj(source, target)
        exported.unlink()
    packages = []
    for index, line in enumerate((output / 'packages.tsv').read_text().splitlines()):
        name, version, source, source_version, architecture = line.split('\t')
        packages.append({'SPDXID': f'SPDXRef-Package-{index}', 'name': name, 'versionInfo': version,
                         'downloadLocation': 'https://snapshot.debian.org/', 'filesAnalyzed': False,
                         'licenseConcluded': 'NOASSERTION', 'licenseDeclared': 'NOASSERTION',
                         'copyrightText': 'NOASSERTION',
                         'sourceInfo': f'Debian source {source} {source_version}; architecture {architecture}'})
    packages.append({'SPDXID': 'SPDXRef-TVHeadend', 'name': 'tvheadend', 'versionInfo': TVHEADEND_COMMIT,
                     'downloadLocation': f'https://github.com/mfat/tvheadend/archive/{TVHEADEND_COMMIT}.tar.gz',
                     'filesAnalyzed': False, 'licenseConcluded': 'NOASSERTION', 'licenseDeclared': 'GPL-3.0-or-later',
                     'copyrightText': 'NOASSERTION'})
    for name, prefix, url, license_id in (
        ('libhdhomerun', 'LIBHDHOMERUN_VERSION', 'https://download.silicondust.com/hdhomerun/', 'LGPL-2.1-or-later'),
        ('dtv-scan-tables', 'DTV_SCAN_TABLES_COMMIT', 'https://github.com/tvheadend/dtv-scan-tables', 'NOASSERTION'),
    ):
        version = re.search(r'^' + prefix + r'=(\S+)$', pins, re.M)[1]
        packages.append({'SPDXID': 'SPDXRef-' + name, 'name': name, 'versionInfo': version,
                         'downloadLocation': url, 'filesAnalyzed': False,
                         'licenseConcluded': 'NOASSERTION', 'licenseDeclared': license_id,
                         'copyrightText': 'NOASSERTION'})
    sbom = {'spdxVersion': 'SPDX-2.3', 'dataLicense': 'CC0-1.0', 'SPDXID': 'SPDXRef-DOCUMENT',
            'name': 'TVHplayer Windows Linux backend', 'documentNamespace': 'https://tvhplayer.org/spdx/' + uuid.uuid4().hex,
            'creationInfo': {'created': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                             'creators': ['Tool: TVHplayer-backend-builder']}, 'packages': packages,
            'relationships': [{'spdxElementId': 'SPDXRef-DOCUMENT', 'relationshipType': 'DESCRIBES',
                               'relatedSpdxElement': package['SPDXID']} for package in packages]}
    (output / 'sbom.spdx.json').write_text(json.dumps(sbom, indent=2), encoding='utf-8')
    artifacts = {name: file_digest(output / name) for name in sorted(RELEASE_ARTIFACTS)}
    manifest = {'schema': 2, 'image': image, 'sha256': artifacts['tvheadend.tar'],
                'tvheadend_commit': TVHEADEND_COMMIT, 'architecture': 'amd64', 'artifacts': artifacts}
    manifest['base_image'] = re.search(r'^ARG BASE_IMAGE=(.+)$', (ROOT / 'windows/backend/Containerfile').read_text(), re.M)[1]
    manifest['ffmpeg_version'] = next(package['versionInfo'] for package in packages if package['name'] == 'ffmpeg')
    manifest['debian_snapshot'] = '20261104T000000Z'
    manifest['base_sources_snapshot'] = '20261105T000000Z'
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    shutil.copy2(ROOT / 'LICENSE', output / 'TVHplayer-LICENSE.txt')
    shutil.copy2(ROOT / 'docs/tvheadend-source.md', output / 'tvheadend-source.md')
    verify_bundle(output, release=True)
    print('Verified offline backend bundle:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default='docker')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'dist')
    parser.add_argument('--dns', help='Explicit WSLc build-session DNS workaround; never changes Windows adapter settings')
    args = parser.parse_args()
    build(args.engine, args.output, args.dns)

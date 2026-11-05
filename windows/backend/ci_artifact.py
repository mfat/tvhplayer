#!/usr/bin/env python3
"""CI helper: fingerprint, lookup, download, publish, or resolve the backend bundle."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND_DIR))

import artifact_store
import fingerprint


def _output(name: str, value: str) -> None:
    path = os.environ.get('GITHUB_OUTPUT')
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(f'{name}={value}\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('fingerprint', help='Print the backend input fingerprint')

    lookup = sub.add_parser('lookup', help='Check whether a verified release exists')
    lookup.add_argument('--fingerprint')

    download = sub.add_parser('download', help='Download and verify a published backend release')
    download.add_argument('--fingerprint')
    download.add_argument('--output', type=Path, default=BACKEND_DIR / 'dist')

    publish = sub.add_parser('publish', help='Publish a local bundle as backend-<fingerprint>')
    publish.add_argument('--fingerprint')
    publish.add_argument('--directory', type=Path, default=BACKEND_DIR / 'dist')
    publish.add_argument('--target-commitish')

    resolve = sub.add_parser('resolve', help='Reuse or build(+publish) a backend bundle')
    resolve.add_argument('--output', type=Path, default=BACKEND_DIR / 'dist')
    resolve.add_argument('--fingerprint')
    resolve.add_argument('--force-rebuild', action='store_true')
    resolve.add_argument('--publish', action='store_true')
    resolve.add_argument('--target-commitish')
    resolve.add_argument('--engine', default='docker')

    args = parser.parse_args(argv)
    if args.command == 'fingerprint':
        value = fingerprint.compute_fingerprint(ROOT)
        print(value)
        _output('fingerprint', value)
        _output('tag', fingerprint.release_tag(value))
        return 0

    fp = getattr(args, 'fingerprint', None) or fingerprint.compute_fingerprint(ROOT)
    if args.command == 'lookup':
        hit = artifact_store.release_exists(fp)
        _output('fingerprint', fp)
        _output('tag', fingerprint.release_tag(fp))
        _output('hit', 'true' if hit else 'false')
        return 0 if hit else 1

    if args.command == 'download':
        artifact_store.download_release(fp, args.output)
        _output('fingerprint', fp)
        _output('tag', fingerprint.release_tag(fp))
        _output('hit', 'true')
        return 0

    if args.command == 'publish':
        tag = artifact_store.publish_release(
            fp, args.directory, target_commitish=args.target_commitish,
        )
        print(tag)
        _output('tag', tag)
        return 0

    if args.command == 'resolve':
        def build():
            subprocess.run(
                [sys.executable, str(BACKEND_DIR / 'build-bundle.py'),
                 '--engine', args.engine, '--output', str(args.output)],
                check=True,
            )

        result = artifact_store.resolve_bundle(
            args.output,
            fingerprint=fp,
            force_rebuild=args.force_rebuild,
            allow_publish=args.publish,
            build_command=build,
            target_commitish=args.target_commitish,
        )
        print(json.dumps(result))
        _output('fingerprint', result['fingerprint'])
        _output('tag', result['tag'])
        _output('hit', 'true' if result['reused'] else 'false')
        return 0

    raise AssertionError(args.command)


if __name__ == '__main__':
    raise SystemExit(main())

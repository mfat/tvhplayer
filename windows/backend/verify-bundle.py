"""Validate a build artifact before including it in either Windows release format."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tvhplayer.core.backend_bundle import verify_bundle


def verify(folder):
    return verify_bundle(folder, release=True)


if __name__ == '__main__':
    verify(sys.argv[1])

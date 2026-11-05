"""Conservative WSLc bind mounts. UNC, device and ambiguous paths are unsupported."""
from pathlib import PureWindowsPath


def bind_mount(host: str, guest: str) -> str:
    path = PureWindowsPath(host)
    if (not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ':'
            or any(c in str(path) for c in ',\r\n\x00"') or '..' in path.parts
            or ':' in str(path)[2:]):
        raise ValueError('Choose an absolute folder on a local Windows drive (without commas).')
    if guest not in ('/config', '/recordings'):
        raise ValueError('Unsupported backend mount destination.')
    return f'type=bind,source={path},target={guest}'

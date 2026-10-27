import io
import tarfile

import pytest

from tvhplayer.core.picons import PiconIndex, extract_pack, latest_tag, name_keys, pack_url, picon_key


def test_keys():
    assert picon_key('Sky Sports+') == 'skysportsplus'
    assert picon_key('RTÉ One') == 'rtéone'
    assert picon_key('Tom & Jerry') == 'tomandjerry'
    assert name_keys('BBC One HD') == ['bbconehd', 'bbcone', 'bbconehdhd']
    assert name_keys('Comedy Central (UK)') == ['comedycentraluk', 'comedycentral', 'comedycentralhd']
    assert name_keys('') == []
    assert name_keys('(HD)') == []


def test_index_finds_loosely(tmp_path):
    for name in ('bbcone.png', 'bbc one lon hd.png', 'daserstehd.png', 'sky sports+.png', 'notes.txt'):
        (tmp_path / name).write_bytes(b'png')
    index = PiconIndex(tmp_path)
    assert len(index) == 4
    assert index.find('BBC One').name == 'bbcone.png'
    assert index.find('BBC ONE HD').name == 'bbcone.png'
    assert index.find('Das Erste').name == 'daserstehd.png'
    assert index.find('Sky Sports +').name == 'sky sports+.png'
    assert index.find('Unknown') is None
    assert len(PiconIndex(tmp_path / 'missing')) == 0


def test_index_keys_match_picon_key(tmp_path):
    names = ('arte.png', 'ARTE HD.png', 'zdf2.png', 'rtéone.png', '.red.png', 'kika.PNG')
    for name in names:
        (tmp_path / name).write_bytes(b'png')
    index = PiconIndex(tmp_path)
    assert sorted(index._files) == sorted(['arte', 'artehd', 'zdf2', 'rtéone', 'red'])
    assert index.find('Arte HD') == tmp_path / 'ARTE HD.png'
    assert index.find('RTÉ One') == tmp_path / 'rtéone.png'
    assert index.find('.red') == tmp_path / '.red.png'


def test_pack_address_from_the_latest_release():
    location = 'https://github.com/picons/picons/releases/tag/2026-10-25--00-12-17'
    assert latest_tag(location) == '2026-10-25--00-12-17'
    assert latest_tag('https://github.com/picons/picons/releases') == ''
    assert pack_url('2026-10-25--00-12-17', 'light') == (
        'https://github.com/picons/picons/releases/download/2026-10-25--00-12-17/'
        'utf8snp-full.100x60-86x46.light.on.transparent_2026-10-25--00-12-17.symlink.tar.xz'
    )


def _archive(path, members):
    with tarfile.open(path, 'w:xz') as tar:
        for name, data, link in members:
            info = tarfile.TarInfo(name)
            if link:
                info.type = tarfile.SYMTYPE
                info.linkname = link
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))


def test_extract_keeps_links_inside(tmp_path):
    archive = tmp_path / 'pack.tar.xz'
    _archive(archive, [
        ('pack/logos/bbcone.png', b'png', None),
        ('pack/bbc one.png', b'', 'logos/bbcone.png'),
    ])
    extract_pack(archive, tmp_path / 'out')
    assert (tmp_path / 'out/pack/bbc one.png').read_bytes() == b'png'

    bad = tmp_path / 'bad.tar.xz'
    _archive(bad, [('../escape.png', b'x', None)])
    with pytest.raises(tarfile.TarError):
        extract_pack(bad, tmp_path / 'out2')
    assert not (tmp_path / 'escape.png').exists()

import hashlib

from tvhplayer.core.htsp_connection import htsp_digest


def test_digest_is_sha1_of_password_plus_challenge():
    challenge = b'\x11' * 32
    digest = htsp_digest('secret', challenge)
    assert digest == hashlib.sha1(b'secret' + challenge).digest()
    assert len(digest) == 20


def test_empty_password_still_hashes_challenge():
    challenge = b'\x22' * 32
    assert htsp_digest('', challenge) == hashlib.sha1(challenge).digest()

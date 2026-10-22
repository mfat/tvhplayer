from tvhplayer.core.htsmsg import Binary, deserialize, serialize


def _roundtrip(msg):
    encoded = serialize(msg)
    body = encoded[4:]
    assert int.from_bytes(encoded[:4], 'big') == len(body)
    return deserialize(body)


def test_empty_map():
    assert _roundtrip({}) == {}


def test_strings_and_ints():
    msg = {'method': 'hello', 'htspversion': 38, 'seq': 1}
    assert _roundtrip(msg) == msg


def test_zero_int_encodes_empty_payload():
    encoded = serialize({'n': 0})
    # type, namelen, datalen=0, name 'n'
    body = encoded[4:]
    assert body[0] == 2  # HMF_S64
    assert body[1] == 1
    assert int.from_bytes(body[2:6], 'big') == 0
    assert _roundtrip({'n': 0}) == {'n': 0}


def test_negative_int_uses_eight_bytes():
    assert _roundtrip({'n': -1}) == {'n': -1}


def test_nested_map_and_list():
    msg = {
        'args': {'limit': 10000, 'sort': 'number'},
        'events': [{'title': 'News'}, {'title': 'Sport'}],
    }
    assert _roundtrip(msg) == msg


def test_binary_digest():
    digest = Binary(b'\x00\x01\x02' + b'\xff' * 17)
    out = _roundtrip({'digest': digest})
    assert isinstance(out['digest'], Binary)
    assert bytes(out['digest']) == digest


def test_bools():
    assert _roundtrip({'on': True, 'off': False}) == {'on': True, 'off': False}


def test_bool_is_not_encoded_as_int():
    encoded = serialize({'flag': True})
    body = encoded[4:]
    assert body[0] == 7  # HMF_BOOL

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


def test_ints_of_every_width():
    msg = {'values': [1, 255, 256, 65535, 2**31, 2**40, 2**62, -2, -2**63]}
    assert _roundtrip(msg) == msg


def test_deeply_nested_with_doubles_and_strings():
    msg = {'a': [{'b': [{'c': 1.5, 'd': 'ünïcode'}], 'e': []}], 'f': {}}
    assert _roundtrip(msg) == msg


def test_truncated_field_is_refused():
    import pytest
    body = serialize({'name': 'value'})[4:]
    with pytest.raises(ValueError, match='Truncated'):
        deserialize(body[:-1])


def test_truncated_nested_field_is_refused():
    import pytest
    body = bytearray(serialize({'outer': {'name': 'value'}})[4:])
    # The inner field claims one byte more than its map holds.
    inner = 6 + len('outer')
    body[inner + 5] += 1
    with pytest.raises(ValueError, match='Truncated'):
        deserialize(bytes(body))


def test_trailing_bytes_are_refused():
    import pytest
    body = serialize({'n': 1})[4:]
    with pytest.raises(ValueError, match='Trailing'):
        deserialize(body + b'\x00')

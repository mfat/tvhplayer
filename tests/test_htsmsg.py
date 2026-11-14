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


def test_field_names_decode_the_same_however_often_they_repeat():
    from tvhplayer.core import htsmsg
    messages = [{'channelName': f'Channel {i}', 'services': [{'name': 'svc', 'type': 'SDTV'}],
                 f'unique{i}': -i, 'ü-name': i} for i in range(htsmsg._NAMES_MAX + 50)]
    for msg in messages:
        assert deserialize(serialize(msg)[4:]) == msg
    # A server sending ever-new names cannot grow the name cache without bound.
    assert len(htsmsg._NAMES) <= htsmsg._NAMES_MAX


def test_c_decoder_matches_the_python_one_including_errors():
    import random
    import struct

    import pytest
    from tvhplayer.core import htsmsg
    if htsmsg._native is None:
        pytest.skip('C decoder not built (python3 packaging/build-native.py)')
    native = htsmsg._native

    def outcome(fn, *args):
        try:
            return 'ok', repr(fn(*args))  # repr: NaN equals itself, and types show
        except Exception as exc:
            return type(exc).__name__, str(exc)

    def same(body, is_list=False):
        assert outcome(native.deserialize, body, is_list) == \
            outcome(htsmsg.python_deserialize, body, htsmsg.HMF_LIST if is_list else htsmsg.HMF_MAP)

    rng = random.Random(1)

    def value(depth=0):
        kind = rng.randrange(8 if depth < 3 else 5)
        if kind == 0:
            return rng.choice(['', 'plain', 'ünïcödé ✓', 'x' * 300])
        if kind == 1:
            return rng.choice([0, 1, -1, 2**63 - 1, -2**63, rng.randrange(-2**40, 2**40)])
        if kind == 2:
            return rng.choice([True, False])
        if kind == 3:
            return rng.uniform(-1e9, 1e9)
        if kind == 4:
            return Binary(bytes(rng.randrange(256) for _ in range(rng.randrange(9))))
        if kind in (5, 6):
            return {rng.choice(['a', 'é', '', 'name']): value(depth + 1) for _ in range(rng.randrange(4))}
        return [value(depth + 1) for _ in range(rng.randrange(4))]

    for _ in range(3000):
        body = serialize({f'k{i}': value() for i in range(rng.randrange(5))})[4:]
        same(body)
        if body:
            same(body[:rng.randrange(len(body))])
            flipped = bytearray(body)
            flipped[rng.randrange(len(flipped))] = rng.randrange(256)
            same(bytes(flipped))
        same(bytes(rng.randrange(256) for _ in range(rng.randrange(30))), rng.random() < 0.5)
    for body in (
        struct.pack('>BBI', 8, 1, 16) + b'u' + bytes(range(16)),   # UUID
        struct.pack('>BBI', 3, 1, 2) + b's' + b'\xff\x41',           # invalid UTF-8
        struct.pack('>BBI', 2, 1, 9) + b'n' + b'\xff' * 9,           # wider than 8 bytes
        struct.pack('>BBI', 6, 1, 4) + b'd' + b'\0' * 4,             # bad double
        struct.pack('>BBI', 9, 1, 0) + b'x',                         # unknown type
        b'\x01\x00\x00',                                             # trailing bytes
    ):
        same(body)
        same(body, True)

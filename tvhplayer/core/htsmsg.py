"""HTSMSG binary codec used by HTSP.

Wire format matches Tvheadend `src/htsmsg_binary.c` and Kodi `pvr.hts`
(`lib/libhts`). Root messages are maps. Integers are little-endian variable
length with no sign-extension; -1 must occupy 8 bytes.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Union

HMF_MAP = 1
HMF_S64 = 2
HMF_STR = 3
HMF_BIN = 4
HMF_LIST = 5
HMF_DBL = 6
HMF_BOOL = 7
HMF_UUID = 8

Message = Union[Dict[str, Any], List[Any]]


class Binary(bytes):
    """Distinct type so binary blobs are not encoded as UTF-8 strings."""


def _s64_bytes(value: int) -> bytes:
    if value == 0:
        return b''
    if value < 0:
        unsigned = value & 0xFFFFFFFFFFFFFFFF
    else:
        unsigned = value
    out = bytearray()
    while unsigned:
        out.append(unsigned & 0xFF)
        unsigned >>= 8
    return bytes(out)


def _decode_s64(data: bytes) -> int:
    unsigned = 0
    for index in range(len(data) - 1, -1, -1):
        unsigned = (unsigned << 8) | data[index]
    if len(data) == 8 and unsigned >= 2**63:
        return unsigned - 2**64
    return unsigned


def _encode_field(name: str, value: Any) -> bytes:
    encoded_name = name.encode('utf-8') if name else b''
    payload, type_id = _encode_value(value)
    header = struct.pack('>BBI', type_id, len(encoded_name), len(payload))
    return header + encoded_name + payload


def _encode_value(value: Any):
    if isinstance(value, bool):
        payload = b'\x01' if value else b''
        return payload, HMF_BOOL
    if isinstance(value, Binary):
        return bytes(value), HMF_BIN
    if isinstance(value, bytes):
        return value, HMF_BIN
    if isinstance(value, dict):
        return _encode_body(value), HMF_MAP
    if isinstance(value, list):
        return _encode_body(value), HMF_LIST
    if isinstance(value, str):
        return value.encode('utf-8'), HMF_STR
    if isinstance(value, int):
        return _s64_bytes(int(value)), HMF_S64
    if isinstance(value, float):
        return struct.pack('<d', value), HMF_DBL
    raise TypeError(f'Unsupported HTSMSG type: {type(value)!r}')


def _encode_body(msg: Message) -> bytes:
    chunks = []
    if isinstance(msg, list):
        for item in msg:
            chunks.append(_encode_field('', item))
    else:
        for key, item in msg.items():
            chunks.append(_encode_field(str(key), item))
    return b''.join(chunks)


def serialize(msg: dict) -> bytes:
    """Serialize a root map, prefixed with the 4-byte body length."""
    if not isinstance(msg, dict):
        raise TypeError('HTSMSG root must be a map')
    body = _encode_body(msg)
    return struct.pack('>I', len(body)) + body


def deserialize(body: bytes, type_id: int = HMF_MAP) -> Message:
    """Deserialize a body (no 4-byte length prefix)."""
    is_list = type_id == HMF_LIST
    msg: Message = [] if is_list else {}
    view = memoryview(body)
    offset = 0
    length = len(body)
    while offset + 6 <= length:
        field_type = view[offset]
        name_len = view[offset + 1]
        data_len = struct.unpack('>I', view[offset + 2:offset + 6].tobytes())[0]
        offset += 6
        if offset + name_len + data_len > length:
            raise ValueError('Truncated HTSMSG field')
        name = view[offset:offset + name_len].tobytes().decode('utf-8', 'replace')
        offset += name_len
        data = view[offset:offset + data_len].tobytes()
        offset += data_len
        item = _decode_value(field_type, data)
        if is_list:
            msg.append(item)
        else:
            msg[name] = item
    if offset != length:
        raise ValueError('Trailing bytes in HTSMSG body')
    return msg


def _decode_value(type_id: int, data: bytes):
    if type_id == HMF_STR:
        return data.decode('utf-8', 'replace')
    if type_id == HMF_BIN:
        return Binary(data)
    if type_id == HMF_S64:
        return _decode_s64(data)
    if type_id in (HMF_MAP, HMF_LIST):
        return deserialize(data, type_id)
    if type_id == HMF_BOOL:
        return bool(data[0]) if data else False
    if type_id == HMF_DBL:
        if len(data) != 8:
            raise ValueError('Invalid HTSMSG double')
        return struct.unpack('<d', data)[0]
    if type_id == HMF_UUID:
        return data.hex()
    raise ValueError(f'Unknown HTSMSG type {type_id}')


def read_message(recv_exact):
    """Read one length-prefixed message using recv_exact(n) -> bytes."""
    header = recv_exact(4)
    if len(header) != 4:
        raise ConnectionError('Connection closed while reading HTSMSG length')
    (size,) = struct.unpack('>I', header)
    if size > 16 * 1024 * 1024:
        raise ValueError(f'HTSMSG too large ({size} bytes)')
    body = recv_exact(size) if size else b''
    if len(body) != size:
        raise ConnectionError('Connection closed while reading HTSMSG body')
    return deserialize(body, HMF_MAP)

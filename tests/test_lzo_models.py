import struct

import pytest

from decompassets import lzo1x
from decompassets.n64.lzo_models import meshes


def test_lzo_literal_overlap_and_bounds():
    encoded = b'\x15ABCD\x40\x00\x11\x00\x00'
    assert lzo1x.unpack(encoded) == (b'ABCDDDD', len(encoded))
    with pytest.raises(ValueError):
        lzo1x.unpack(encoded[:-1])
    with pytest.raises(ValueError):
        lzo1x.unpack(encoded, limit=6)
    with pytest.raises(ValueError):
        lzo1x.unpack(b'\x40\xff\x11\x00\x00')


def test_bounded_parts_need_valid_indices_and_sizes():
    data = bytearray(188)
    struct.pack_into('>HII', data, 2, 1, 3, 1)
    struct.pack_into('>3I', data, 32, 120, 144, 188)
    struct.pack_into('>HHI', data, 60, 3, 1, 144)
    for i, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0))):
        struct.pack_into('>3h', data, 120+i*6, *point)
    struct.pack_into('>H', data, 144, 0x25)
    struct.pack_into('>3H', data, 152, 0, 1, 2)
    assert meshes(data)[0][1] == [(0, 1, 2)]
    struct.pack_into('>H', data, 156, 3)
    assert meshes(data) == []
    struct.pack_into('>H', data, 156, 2)
    struct.pack_into('>I', data, 40, 189)
    assert meshes(data) == []

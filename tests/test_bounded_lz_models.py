import struct

import pytest

from decompassets import bounded_lz, formats
from decompassets.n64 import bounded_lz_models as models


def model():
    data = bytearray(0x68+8+4*8)
    struct.pack_into('>5I', data, 0, 0, 1, 0x20, 0x18, 0x68)
    struct.pack_into('>I', data, 0x20, 4)
    for i, point in enumerate(((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0))):
        struct.pack_into('>3h', data, 0x28+i*16, *point)
    struct.pack_into('>I', data, 0x68, 4)
    struct.pack_into('>II', data, 0x70, 0x00070000, 0xffffffff)
    struct.pack_into('>II', data, 0x78, 0x00080200, 0)
    packed = sum(index << shift for index, shift in zip((0, 1, 2, 0, 2, 3), (35, 28, 21, 14, 7, 0)))
    struct.pack_into('>II', data, 0x80, 0x000a0000 | (packed >> 32), packed & 0xffffffff)
    return data


def test_lz_literals_backreferences_and_bounds():
    stream = b'\x04\0\0\0\x20AB\x01'
    assert bounded_lz.unpack(stream) == (b'ABAB', len(stream))
    with pytest.raises(formats.AssetError):
        bounded_lz.unpack(stream[:-1])
    with pytest.raises(formats.AssetError):
        bounded_lz.unpack(stream[:-1] + b'\x7f')


def test_vertex_cache_commands_and_table_bounds(monkeypatch):
    data = model()
    vertices, faces = models.geometry(data)
    assert len(vertices) == 4
    assert faces == [(0, 1, 2), (0, 2, 3)]
    image = bytearray(0x10200)
    struct.pack_into('>II', image, 0, 0x10100, 0x10200)
    image[0x10100:0x10104] = (128).to_bytes(4, 'little')
    monkeypatch.setattr(models.bounded_lz, 'unpack', lambda _: (data, 20))
    asset, = models.regions(image)
    assert models.preview(image, asset, {})['triangles'] == 2
    struct.pack_into('>I', data, 0x7c, 3)
    assert models.geometry(data) is None

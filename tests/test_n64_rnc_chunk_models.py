import struct

from decompassets.n64 import rnc_chunk_models as models


def fixture():
    data = bytearray(0x98)
    words = {0: 1, 4: 16, 8: len(data), 0x28: 1, 0x2c: 8,
             0x30: 3, 0x34: 24, 0x38: 24, 0x3c: 40, 0x40: 104,
             0x48: 2, 0x4c: 1, 0x58: 64, 0x5c: 1, 0x60: 16, 0x64: 3}
    for at, value in words.items():
        struct.pack_into('>I', data, at, value)
    struct.pack_into('>H', data, 0x50, 0x0022)
    for i, point in enumerate(((1, 2, 3), (4, 5, 6), (7, 8, 9))):
        struct.pack_into('>3h', data, 0x68+16*i, *point)
    image = bytes(16) + b'RNC\x01' + struct.pack('>II', len(data), 1) + bytes(7)
    return image, data


def test_triangle_and_vertices_are_checked_and_previewed(monkeypatch):
    image, data = fixture()
    monkeypatch.setattr(models.rnc, 'unpack', lambda *_args, **_kwargs: data)
    asset = models.regions(image)[0]
    preview = models.preview(image, asset, {})
    assert preview['vertices'] == [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)
    assert preview['triangles'] == 1


def test_invalid_triangle_or_section_bounds_are_rejected(monkeypatch):
    image, data = fixture()
    monkeypatch.setattr(models.rnc, 'unpack', lambda *_args, **_kwargs: data)
    struct.pack_into('>H', data, 0x50, 0x0023)
    assert models.model(image, 16) is None
    struct.pack_into('>H', data, 0x50, 0x0022)
    struct.pack_into('>I', data, 0x3c, 0x1000)
    assert models.model(image, 16) is None

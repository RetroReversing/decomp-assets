"""Level drawing bytecode resolves bounded vertices and triangles."""

import struct

import pytest

from decompassets.n64 import level_bytecode, lzhuf


def test_level_geometry_and_invalid_opcode(monkeypatch):
    image = bytearray(0x4000)
    base = 0x2000
    header = [0] * 17
    header[0], header[1], header[15], header[16] = 80, 1, 128, 36
    struct.pack_into('>17I', image, base, *header)
    struct.pack_into('>3i', image, base + 80, 100, 200, 300)
    vertices = b''.join(struct.pack('>3h4B', *point, 0, 255, 255, 255)
                        for point in ((1, 2, 3), (4, 5, 6), (7, 8, 9)))
    program = b'\x01\x03' + vertices + b'\x04\x00\x22\x00'
    monkeypatch.setattr(lzhuf, 'unpack', lambda *_, **__: program)
    meshes = level_bytecode.meshes(image, base, len(image))
    assert meshes == [(0, [(101, 202, 303), (104, 205, 306), (107, 208, 309)], [(0, 1, 2)])]
    monkeypatch.setattr(lzhuf, 'unpack', lambda *_, **__: b'\xff')
    assert level_bytecode.meshes(image, base, len(image)) == []


def test_huffman_rejects_empty_input():
    from decompassets.formats import AssetError

    with pytest.raises(AssetError):
        lzhuf.unpack(b'', 8, fill=0)

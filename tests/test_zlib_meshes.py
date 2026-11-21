"""Validate both model passes, their vertex bounds, and preview dispatch."""

import struct
import zlib

from decompassets.n64 import preview, zlib_meshes


def test_zlib_mesh_uses_two_matching_vertex_passes():
    header = bytearray(0x48)
    header[:2] = b'\x01\x03'
    struct.pack_into('>I20xII', header, 4, 3, 0x48, 0x78)
    vertex = struct.pack('>3h6x4B', 1, -2, 3, 10, 20, 30, 255)
    packets = bytes.fromhex('01 03 04 00 22 ff')
    prefix = bytes(header) + vertex * 3
    data = b'file' + zlib.compress(prefix + packets * 2 + bytes(4))
    mesh, = zlib_meshes.regions(data)
    result = preview(data, mesh, {})
    assert result['vertices'] == [(1, -2, 3)] * 3
    assert result['triangles'] == 1
    assert result['surfaces'][0]['indices'] == (0, 1, 2)
    assert zlib_meshes.regions(data[:-1]) == []
    second = bytes.fromhex('01 03 04 00 43 ff')
    assert zlib_meshes.regions(zlib.compress(prefix + packets + second + bytes(4))) == []
    second = bytes.fromhex('01 03 04 08 20 ff')
    assert zlib_meshes.regions(zlib.compress(prefix + packets + second + bytes(4))) == []

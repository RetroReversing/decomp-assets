"""Mesh batches must resolve their local vertex and triangle ranges."""

import struct

from decompassets.n64 import exs_models


def test_checked_mesh_and_preview():
    data = bytearray(144)
    data[:8] = b'_MGNEVR1'
    struct.pack_into('>4I', data, 8, 36, 80, 92, 96)
    struct.pack_into('>6H', data, 36, 0, 0, 0, 1, 1, 3)
    data[84:86] = b'\x01\x03'
    data[92:96] = b'\x00\x01\x02\x00'
    for i in range(3):
        struct.pack_into('>3h', data, 96 + i*16, i, 0, 0)
    assert exs_models.meshes(data)[0][2] == [(0, 1, 2)]
    encoded = b''.join(b'\xff' + data[i:i+8] for i in range(0, len(data), 8)) + bytes(3)
    image = b'EXS\x01' + len(data).to_bytes(4, 'little') + encoded
    asset, = exs_models.regions(image)
    assert exs_models.preview(image, asset, {})['triangles'] == 1
    data[94] = 3
    assert not exs_models.meshes(data)

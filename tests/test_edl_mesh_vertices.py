import struct

from decompassets.n64 import edl_mesh_vertices, eurocom


def _pack():
    data = bytearray(0xb0)
    struct.pack_into('>I', data, 0, 0x00150011)
    struct.pack_into('>I', data, 0x30, 1)
    struct.pack_into('>HHI', data, 0x3c, 2, 4, 0x40)
    struct.pack_into('>I', data, 0x58, (0xa8 - 0x58) << 8)
    struct.pack_into('>6h', data, 0x80, -1, 3, -2, 4, -3, 5)
    struct.pack_into('>3h2x', data, 0x8c, -1, 2, 3)
    struct.pack_into('>3h2x', data, 0x94, 4, -3, 5)
    struct.pack_into('>3h2x', data, 0x9c, 0, 0, 0)
    return data


def test_compressed_mesh_vertices_are_bounded_and_previewed_as_points():
    data = _pack()
    items = edl_mesh_vertices.meshes(data)
    assert len(items) == 1 and items[0]['vertices'] == 3
    rom = struct.pack('>4sII', b'EDL\x80', len(data) + 12, len(data)) + data
    asset, = edl_mesh_vertices.regions(rom, {0: (0, len(rom), len(data))}, lambda: None)
    result = eurocom.preview(rom, asset, {})
    assert result['vertices'] == [(-1, 2, 3), (4, -3, 5), (0, 0, 0)]
    assert result['points'] == [0, 1, 2] and not result['surfaces']
    assert 'only' in result['note']
    struct.pack_into('>h', data, 0x8c, -2)
    assert not edl_mesh_vertices.meshes(data)
    assert not edl_mesh_vertices.meshes(_pack()[:-32])

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


def test_compact_commands_decode_triangles_and_reject_bad_indices():
    data = _pack()
    struct.pack_into('>H', data, 0x3c, 1)
    # Load three vertex slots, then draw one little-endian packed triangle.
    stream = bytes((0, 0x1f, 0, 0, 0, 0, 0, 3, 0,
                    0, 0, 0, 1, 0, 0, 2, 0, 0, 0x0e, 0x20, 0x08, 6))
    data[0xa8:] = stream
    rom = struct.pack('>4sII', b'EDL\x80', len(data) + 12, len(data)) + data
    asset, = edl_mesh_vertices.regions(rom, {0: (0, len(rom), len(data))}, lambda: None)
    assert asset['triangles'] == 1
    result = eurocom.preview(rom, asset, {})
    assert result['triangles'] == 1
    assert result['surfaces'][0]['indices'] == (0, 1, 2)
    assert 'Untextured' in result['note']
    data[-3] = 0xe0
    assert edl_mesh_vertices.meshes(data)[0]['triangles'] == 0


def test_triangle_header_can_exceed_terminated_stream():
    data = _pack()
    struct.pack_into('>H', data, 0x3c, 2)
    data[0xa8:] = bytes((0, 0x1f, 0, 0, 0, 0, 0, 3, 0,
                         0, 0, 0, 1, 0, 0, 2, 0, 0, 0x0e, 0x20, 0x08, 6))
    assert edl_mesh_vertices.meshes(data)[0]['triangles'] == 1
    struct.pack_into('>H', data, 0x3c, 0)
    assert edl_mesh_vertices.meshes(data)[0]['triangles'] == 0

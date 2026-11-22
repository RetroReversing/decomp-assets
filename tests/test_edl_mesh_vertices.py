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


def test_adjacent_texture_pack_resolves_mesh_material_and_uv():
    raw = bytearray(0xa4)
    struct.pack_into('>IIHHIII', raw, 0, 5, len(raw), 1, 1, 0x1c, 16, 0x2c)
    struct.pack_into('>HHIIHH', raw, 0x28, 2, 8, 0, 0, 0, 0)
    struct.pack_into('>I', raw, 0x40, 8)
    struct.pack_into('>I', raw, 0x44, (0x84 - 0x44) << 8)
    struct.pack_into('>I', raw, 0x48, 0x64 - 0x48)
    texture = struct.pack('>4sII', b'EDL\x80', len(raw) + 12, len(raw)) + raw
    data = _pack()
    struct.pack_into('>H', data, 0x3c, 1)
    data[0xa8:] = bytes((0, 0x1f, 0, 0, 0, 0, 9, 0, 0, 3, 0,
                         0, 1, 2, 1, 2, 3, 2, 3, 4, 0x0e, 0x20, 0x08, 6))
    model = struct.pack('>4sII', b'EDL\x80', len(data) + 12, len(data)) + data
    offset = (len(texture) + 15) & ~15
    rom = texture + bytes(offset - len(texture)) + model
    asset, = edl_mesh_vertices.regions(rom, {0: (0, len(texture), len(texture) - 12),
                                            offset: (0, len(model), len(data))}, lambda: None)
    assert asset['texture_offset'] == 0
    result = eurocom.preview(rom, asset, {})
    assert result['materials'][1]['image'].startswith('data:image/png;base64,')
    assert result['surfaces'][0]['material'] == 1
    assert result['surfaces'][0]['uv'][0] == [0.125, 0.25]


def test_unpadded_vertices_and_alternate_flags_need_valid_surface_commands():
    data = _pack()
    struct.pack_into('>HH', data, 0x3c, 1, 5)
    struct.pack_into('>I', data, 0x58, (0xa4 - 0x58) << 8)
    data[0xa4:] = bytes((0, 0x1f, 0, 0, 0, 0, 0, 3, 0,
                         0, 0, 0, 1, 0, 0, 2, 0, 0, 0x0e, 0x20, 0x08, 6))
    item, = edl_mesh_vertices.meshes(data)
    assert item['vertices'] == 3 and item['triangles'] == 1
    data[-1] = 15
    assert edl_mesh_vertices.meshes(data) == []


def test_quad_commands_use_four_positions_and_texture_coordinates():
    data = _pack()
    struct.pack_into('>HH', data, 0x3c, 2, 6)
    struct.pack_into('>3h2x', data, 0xa4, 0, 1, 2)
    struct.pack_into('>I', data, 0x58, ((0xac - 0x58) << 8) | 1)
    record = bytearray(28)
    struct.pack_into('>H', record, 0, 0x9f)
    record[12] = 3
    record[14:22] = bytes((0, 0, 7, 7, 7, 0, 7, 0))
    data[0xac:] = record
    item, = edl_mesh_vertices.meshes(data)
    assert item['vertices'] == 4 and item['triangles'] == 2
    faces = edl_mesh_vertices._faces(data, item['descriptor'], 4)
    assert faces[0] == (((0, 0, 7), (2, 7, 7), (1, 0, 0)), 4)
    assert faces[1] == (((1, 0, 0), (2, 7, 7), (3, 7, 0)), 4)
    assert edl_mesh_vertices._faces(data[:-1], item['descriptor'], 4) is None


def test_shared_position_storage_uses_only_referenced_bounded_vertices():
    data = _pack()
    data.extend(bytes(16))
    struct.pack_into('>HH', data, 0x3c, 1, 4)
    struct.pack_into('>I', data, 0x58, (0xb8 - 0x58) << 8)
    struct.pack_into('>3h2x', data, 0x8c, 100, 100, 100)
    struct.pack_into('>3h2x', data, 0xa4, 0, 1, 2)
    data[0xb8:] = bytes((0, 0x1f, 0, 0, 0, 0, 0, 3, 0,
                         1, 0, 0, 2, 0, 0, 3, 0, 0, 0x0e, 0x20, 0x08, 6))
    item, = edl_mesh_vertices.meshes(data)
    assert item['source_indices'] == [1, 2, 3]
    rom = struct.pack('>4sII', b'EDL\x80', len(data) + 12, len(data)) + data
    asset, = edl_mesh_vertices.regions(rom, {0: (0, len(rom), len(data))}, lambda: None)
    preview = eurocom.preview(rom, asset, {})
    assert preview['vertices'] == [(4, -3, 5), (0, 0, 0), (0, 1, 2)]
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)
    struct.pack_into('>h', data, 0x94, 99)
    assert edl_mesh_vertices.meshes(data) == []

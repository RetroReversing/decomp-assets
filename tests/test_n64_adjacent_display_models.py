import struct

from decompassets.n64 import adjacent_display_models, display_meshes


def fixture(*, flat=False, bad_index=False):
    data = bytearray(16)
    for point in ((0, 0, 0), (10, 0, 0), (0, 10, 0), (10, 10, 0 if flat else 10)):
        data += struct.pack('>3hH2h4B', *point, 0, 0, 0, 255, 255, 255, 255)
    data += struct.pack('>6I', 0x01004008, 0x80001000, 0x06000204,
                        0x00000408 if bad_index else 0x00000406, 0xdf000000, 0)
    return bytes(data)


def test_adjacent_vertices_and_triangles_make_a_mesh():
    data = fixture()
    asset = adjacent_display_models.regions(data)[0]
    preview = display_meshes.preview(data, asset, {})
    assert len(preview['vertices']) == 4
    assert preview['triangles'] == 2
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)


def test_flat_or_invalid_index_is_not_a_mesh():
    assert not adjacent_display_models.regions(fixture(flat=True))
    assert not adjacent_display_models.regions(fixture(bad_index=True))

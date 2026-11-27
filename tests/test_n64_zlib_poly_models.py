import struct
import zlib

from decompassets import n64
from decompassets.n64 import zlib_poly_models


def fixture(bad_index=False):
    data = bytearray(0xdc)
    for offset, value in ((0, 0x10000), (4, 0xc4), (0x18, 0x40), (0x48, 0x50),
                          (0x50, 0x60), (0x80, 0x90), (0x98, 0xa0), (0x9c, 1),
                          (0xa0, 36), (0xa4, 0x090c5146)):
        struct.pack_into('>I', data, offset, value)
    struct.pack_into('>3H', data, 0xac, 0, 1, 3 if bad_index else 2)
    for index, point in enumerate(((1, 2, 3), (4, 5, 6), (7, 8, 9))):
        struct.pack_into('>3hH', data, 0xc4+8*index, *point, 0)
    return bytes(16) + zlib.compress(data)


def test_polygon_mesh_decodes_vertices_and_indices():
    data = fixture()
    asset = next(a for a in n64.regions(data) if a.get('layout') == zlib_poly_models.LAYOUT)
    preview = n64.preview(data, asset, {})
    assert preview['vertices'] == [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)
    assert preview['triangles'] == 1


def test_out_of_range_vertex_and_truncated_stream_are_rejected():
    assert zlib_poly_models.model(fixture(True), 16) is None
    assert zlib_poly_models.model(fixture()[:-1], 16) is None


def test_quads_are_split_into_two_triangles():
    raw = bytearray(zlib.decompress(fixture()[16:]))
    raw[0xc4:0xc4] = bytes(4)
    struct.pack_into('>I', raw, 4, 0xc8)
    struct.pack_into('>II', raw, 0xa0, 44, 0x0a0c5146)
    struct.pack_into('>4H', raw, 0xac, 0, 1, 2, 0)
    image = bytes(16) + zlib.compress(raw)
    asset = zlib_poly_models.regions(image)[0]
    preview = zlib_poly_models.preview(image, asset, {})
    assert [face['indices'] for face in preview['surfaces']] == [(0, 1, 2), (0, 2, 0)]

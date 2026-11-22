import struct

from decompassets.n64 import refpack_triangles


def test_mesh_requires_bounded_finite_triangle_vertices():
    data = bytearray(108)
    data[:4] = b'\x05\x01\0\0'
    struct.pack_into('<13I', data, 4, 56, *([108]*12))
    struct.pack_into('<I', data, 56, 3)
    for i, point in enumerate(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))):
        struct.pack_into('<3f', data, 60+16*i, *point)
    assert len(refpack_triangles.mesh(data)) == 3
    struct.pack_into('<f', data, 60, float('nan'))
    assert refpack_triangles.mesh(data) is None
    struct.pack_into('<f', data, 60, 0.)
    struct.pack_into('<I', data, 56, 6)
    assert refpack_triangles.mesh(data) is None

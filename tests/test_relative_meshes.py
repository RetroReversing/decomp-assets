import struct

from decompassets import n64
from decompassets.n64 import relative_meshes


def fixture(pointer=32, triangle=0x020406, flag=0, trailing=b''):
    commands = struct.pack('>8I', 0x0400103f, pointer, 0xbf000000, 0x00000204,
                           0xbf000000, triangle, 0xb8000000, 0)
    vertices = b''.join(struct.pack('>3hH2h4B', x, y, 0, flag, 0, 0, 255, 255, 255, 255)
                        for x, y in ((0, 0), (1, 0), (1, 1), (0, 1)))
    return bytes(16) + commands + vertices + trailing


def test_relative_vertices_immediately_follow_the_closed_list():
    data = fixture()
    asset, = [row for row in n64.regions(data) if row['kind'] == '3d model']
    mesh = n64.preview(data, asset, {})
    assert asset['offset'] == 16 and mesh['triangles'] == 2
    assert mesh['vertices'] == [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    assert [face['indices'] for face in mesh['surfaces']] == [(0, 1, 2), (1, 2, 3)]


def test_relative_mesh_rejects_missing_vertices_invalid_slots_and_vertex_flags():
    for data in (fixture(pointer=40, trailing=bytes(8)), fixture(triangle=0x020408),
                 fixture(flag=1), fixture()[:-1]):
        assert not relative_meshes.regions(data)

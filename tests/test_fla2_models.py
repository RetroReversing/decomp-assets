import struct

from decompassets.n64.fla2_models import meshes


def fixture():
    data = bytearray(512)
    struct.pack_into('>6I', data, 0, 1, 32, 2, 64, 0, 0)
    struct.pack_into('>I', data, 32, 1)
    struct.pack_into('>I', data, 44, 96)
    struct.pack_into('>I', data, 64, 2)
    struct.pack_into('>I', data, 76, 160)
    for node, geometry in ((96, 224), (160, 260)):
        data[node+4:node+12] = b'testmesh'
        struct.pack_into('>I', data, node+20, geometry)
        struct.pack_into('>HHII', data, geometry, 1, 3, 320, 400)
    for i, point in enumerate(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))):
        struct.pack_into('>3f', data, 320+i*12, *point)
    struct.pack_into('>3H', data, 400, 0, 1, 2)
    return data


def test_object_hierarchy_bounds_faces_and_pointers():
    data = fixture()
    rows = meshes(data)
    assert len(rows) == 2 and rows[0][2] == [(0, 1, 2)]
    struct.pack_into('>H', data, 404, 3)
    assert meshes(data) == []
    data = fixture()
    struct.pack_into('>I', data, 96+52, len(data)+4)
    assert meshes(data) == []

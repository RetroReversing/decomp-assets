import struct

from decompassets.n64 import relative_models


def test_bounded_local_meshes_and_invalid_triangles():
    data = bytearray(0x120)
    struct.pack_into('>II', data, 0x34, 0x80, 0xa0)
    struct.pack_into('>I', data, 0x40, 0xd0)
    struct.pack_into('>6I', data, 0x80, 0x01003006, 0x06000000,
                     0x05000204, 0, 0xdf000000, 0)
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3h', data, 0xa0 + 16 * i, x, y, 0)
    [mesh] = relative_models.meshes(data)
    assert mesh['vertices'] == 3
    assert mesh['triangles'] == 1
    struct.pack_into('>I', data, 0x88, 0x05000206)
    assert not relative_models.meshes(data)


def test_chunk_selects_its_own_vertex_slice():
    data = bytearray(0x160)
    struct.pack_into('>II', data, 0x34, 0x80, 0xa0)
    struct.pack_into('>I', data, 0x40, 0x100)
    struct.pack_into('>3I', data, 0x68, 0x100, 0x134, 0)
    struct.pack_into('>10I', data, 0x10c, 0, 24, 0, 0, 0, 0, 0, 0, 0x30, 0x30)
    struct.pack_into('>6I', data, 0x80, 0x01003006, 0x06000000,
                     0x05000204, 0, 0xdf000000, 0)
    [mesh] = relative_models.meshes(data)
    assert mesh['vertex_start'] == 0xd0
    assert mesh['vertex_end'] == 0x100
    struct.pack_into('>I', data, 0x130, 0x40)
    assert not relative_models.meshes(data)

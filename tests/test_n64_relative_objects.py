import struct

from decompassets.n64 import relative_objects


def test_object_and_actor_vertex_windows():
    item = bytearray(0x100)
    struct.pack_into('>I', item, 0x40, 0x50)
    struct.pack_into('>II', item, 0x48, 0x70, 0xa0)
    struct.pack_into('>6I', item, 0x50, 0x01003006, 0x08000000,
                     0x05000204, 0, 0xdf000000, 0)
    [mesh] = relative_objects.meshes(item, 4)
    assert (mesh['vertices'], mesh['triangles'], mesh['vertex_start']) == (3, 1, 0x70)
    struct.pack_into('>I', item, 0x4c, 0x90)
    assert not relative_objects.meshes(item, 4)

    actor = bytearray(0xc0)
    struct.pack_into('>II', actor, 0, 0x1000, 0x1078)
    struct.pack_into('>I', actor, 0xa0, 0x1030)
    struct.pack_into('>6I', actor, 0x58, 0x01003006, 0x06000000,
                     0x05000204, 0, 0xdf000000, 0)
    [mesh] = relative_objects.meshes(actor, 5)
    assert (mesh['vertices'], mesh['triangles'], mesh['vertex_start']) == (3, 1, 0x28)
    struct.pack_into('>I', actor, 0xa0, 0x2000)
    assert not relative_objects.meshes(actor, 5)

import struct

import pytest

from decompassets.n64.level_world_models import meshes


def level():
    data = bytearray(0x1000)
    base = 0x8024b000
    struct.pack_into('>I', data, 0, base+0x100)
    struct.pack_into('>I', data, 0x100, base+0x200)
    struct.pack_into('>I', data, 0x118, 3)
    struct.pack_into('>I', data, 0x130, base+0x500)
    data[0x20c] = 2
    struct.pack_into('>HH', data, 0x218, 0, 16)
    struct.pack_into('>II', data, 0x228, 0x01003006, 0x01000000)
    struct.pack_into('>II', data, 0x230, 0x05000204, 0)
    struct.pack_into('>II', data, 0x238, 0, 0xcdcdcdcd)
    for i,(x,y,z) in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3hH2h4B', data, 0x500+i*16, x,y,z,0,0,0,255,255,255,255)
    return data


@pytest.mark.parametrize('damage', [None, 'bad_tree', 'bad_vertex_pool', 'bad_vertex_count', 'bad_index', 'no_end'])
def test_world_section_requires_closed_tree_and_resolved_vertices(damage):
    data = level()
    if damage == 'bad_tree': struct.pack_into('>I', data, 0x100, 0)
    if damage == 'bad_vertex_pool': struct.pack_into('>I', data, 0x130, 0)
    if damage == 'bad_vertex_count': struct.pack_into('>I', data, 0x118, 2)
    if damage == 'bad_index': struct.pack_into('>I', data, 0x230, 0x05000208)
    if damage == 'no_end': struct.pack_into('>I', data, 0x23c, 0)
    result = meshes(data)
    assert len(result) == (1 if damage is None else 0)
    if result:
        assert result[0]['vertices'] == 3
        assert result[0]['triangles'] == 1

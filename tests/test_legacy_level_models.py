import struct

import pytest

from decompassets.n64.legacy_level_models import meshes


def level():
    data=bytearray(0x1000)
    base=0x8024b000
    struct.pack_into('>I',data,0,base+0x100)
    struct.pack_into('>I',data,0x100,base+0x200)
    struct.pack_into('>I',data,0x118,3)
    struct.pack_into('>I',data,0x124,base+0x500)
    struct.pack_into('>II',data,0x138,base+0x300,base+0x400)
    struct.pack_into('>H',data,0x208,2)
    struct.pack_into('>HHI',data,0x210,0,24,0)
    struct.pack_into('>II',data,0x218,0x06000000,0x02000000)
    struct.pack_into('>II',data,0x220,0x04000c2f,0x01000000)
    struct.pack_into('>II',data,0x228,0xb8000000,0)
    struct.pack_into('>HHI',data,0x230,0,16,0)
    struct.pack_into('>II',data,0x238,0xbf000000,0x00000204)
    struct.pack_into('>II',data,0x240,0xb8000000,0)
    for i,(x,y,z) in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3hH2h4B',data,0x500+i*16,x,y,z,0,0,0,255,255,255,255)
    return data


@pytest.mark.parametrize('damage',[None,'tree','count','material','triangle','terminator'])
def test_chunks_share_vertex_state_but_require_valid_bounds(damage):
    data=level()
    if damage=='tree':struct.pack_into('>I',data,0x100,0)
    if damage=='count':struct.pack_into('>I',data,0x118,2)
    if damage=='material':struct.pack_into('>I',data,0x21c,0x02000100)
    if damage=='triangle':struct.pack_into('>I',data,0x23c,0x00000208)
    if damage=='terminator':struct.pack_into('>I',data,0x228,0)
    rows=meshes(data)
    assert len(rows)==(1 if damage is None else 0)
    if rows:assert (len(rows[0]['vertices']),len(rows[0]['faces']))==(3,1)

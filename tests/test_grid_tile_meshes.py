import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import grid_tile_meshes as mesh


def fixture():
    data=bytearray(0x63)
    struct.pack_into('>3I',data,0,0x30,0x44,0x63)
    data[0x30:0x38]=b'46d\0'+bytes((32,32,2,2))
    struct.pack_into('<4H',data,0x3c,1,1,0,1)
    struct.pack_into('>2I',data,0x44,8,31)
    data[0x4c:0x54]=b'46d\0'+bytes((0,0,0,3))
    data[0x54:0x5d]=bytes((0,0,0, 1,0,0, 0,0,1))
    data[0x5d:0x63]=b'\x10\xff\xff\xff\x22\x00'
    return bytes(data)


def test_grid_mesh_instantiates_tiles_in_world_positions():
    rom=fixture();a=mesh.regions(rom)
    assert len(a)==1 and a[0]['triangles']==3
    p=mesh.preview(rom,a[0],{})
    assert len(p['vertices'])==9 and p['vertices'][3]==(32,0,0)


def test_invalid_tile_indices_are_rejected():
    rom=bytearray(fixture());struct.pack_into('<H',rom,0x3c,5)
    assert mesh.regions(bytes(rom))==[]
    with pytest.raises(AssetError):mesh.preview(bytes(rom),{'offset':0,'label':'map'}, {})

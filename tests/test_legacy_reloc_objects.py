import struct

import pytest

from decompassets.n64 import legacy_reloc_objects as objects


def object_data():
    relocs=[0xc,0x5c,0x64,0x74,0x90]
    base=4+4*len(relocs)
    data=bytearray(base+0x1000)
    struct.pack_into('>I5I',data,0,len(relocs),*relocs)
    struct.pack_into('>HH',data,base+8,1,0)
    struct.pack_into('>I',data,base+0xc,0x5c)
    struct.pack_into('>I',data,base+0x5c,0x60)
    struct.pack_into('>II',data,base+0x60,3,0x100)
    struct.pack_into('>III',data,base+0x70,1,0x130,1)
    struct.pack_into('>I',data,base+0x90,0x200)
    for i,(x,y,z) in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3hH4B',data,base+0x100+i*12,x,y,z,0,255,255,255,255)
    struct.pack_into('>3H6x',data,base+0x130,0,1,2)
    data[base+0x200:base+0x220]=b'\xff\xff'*16
    commands=[(0xe7000000,0),(0xba000e02,0x8000),(0xfd100000,0x05000000),
              (0xf5000100,0x06000000),(0xf0000000,0x0603c000),(0xf5500000,0x07094250),
              (0xe6000000,0),(0xfd500000,0x05000020),(0xf3000000,0x070ff400),
              (0xf5400400,0x00094250),(0xf2000000,0x0007c07c),
              (0xe6000000,0),(0xb8000000,0)]
    for i,(a,b) in enumerate(commands):struct.pack_into('>II',data,base+0x500+i*8,a,b)
    return data


@pytest.mark.parametrize('damage',[None,'relocation','index','animated','parts','bounds','texture'])
def test_legacy_rigid_object_is_bounded(damage):
    data=object_data();base=24
    if damage=='relocation':struct.pack_into('>I',data,8,0x5e)
    if damage=='index':struct.pack_into('>H',data,base+0x134,8)
    if damage=='animated':struct.pack_into('>H',data,base+0xa,1)
    if damage=='parts':struct.pack_into('>I',data,base+0x78,2)
    if damage=='bounds':struct.pack_into('>I',data,base+0x64,0xfffffffc)
    if damage=='texture':data[base+0x200:base+0x220]=bytes(32)
    found=objects.meshes(data)
    assert len(found)==(1 if damage in (None,'texture') else 0)
    if found:assert len(objects.textures(data,found))==(0 if damage=='texture' else 1)

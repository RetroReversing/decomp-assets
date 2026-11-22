import struct
import zlib

import pytest

from decompassets.n64 import reloc_level_objects as objects


def object_data():
    relocs = [0xc, 0x5c, 0x68, 0x74, 0x94]
    base = 4+4*len(relocs)
    data = bytearray(base+0x1000)
    struct.pack_into('>I5I', data, 0, len(relocs), *relocs)
    struct.pack_into('>H', data, base+8, 1)
    struct.pack_into('>I', data, base+0xc, 0x5c)
    struct.pack_into('>I', data, base+0x5c, 0x60)
    struct.pack_into('>H2xHH', data, base+0x60, 3, 1, 1)
    struct.pack_into('>I', data, base+0x68, 0x100)
    struct.pack_into('>I', data, base+0x74, 0x120)
    struct.pack_into('>I', data, base+0x94, 0x200)
    for i,(x,y,z) in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3hH', data, base+0x100+i*8, x,y,z,0)
    struct.pack_into('>3H6x', data, base+0x120, 0,1,2)
    data[base+0x200:base+0x220] = b'\xff\xff'*16
    commands = [(0xe7000000,0),(0xe3001001,0x8000),(0xfd100000,0x05000000),
                (0xf5000100,0x06000000),(0xf0000000,0x0603c000),(0xf5500000,0x07094250),
                (0xe6000000,0),(0xfd500000,0x05000020),(0xf3000000,0x070ff400),
                (0xf5400400,0x00094250),(0xf2000000,0x0007c07c),
                (0xe6000000,0),(0xdf000000,0)]
    for i,(w0,w1) in enumerate(commands):struct.pack_into('>II',data,base+0x500+8*i,w0,w1)
    return data


@pytest.mark.parametrize('damage', [None, 'relocation', 'index', 'skinned', 'bounds'])
def test_object_mesh_requires_relocations_and_rigid_bounded_faces(damage):
    data = object_data()
    base = 24
    if damage == 'relocation': struct.pack_into('>I', data, 8, 0x5e)
    if damage == 'index': struct.pack_into('>H', data, base+0x124, 8)
    if damage == 'skinned': struct.pack_into('>H', data, base+0x66, 2)
    if damage == 'bounds': struct.pack_into('>I', data, base+0x68, 0xfffffffc)
    found = objects.meshes(data)
    assert len(found) == (1 if damage is None else 0)
    if found:
        assert len(found[0]['faces']) == 1
        assert len(objects.textures(data, found)) == 1


def test_directory_needs_contiguous_members():
    data = bytearray(0x10000)
    packed = zlib.compressobj(wbits=-15)
    body = packed.compress(object_data())+packed.flush()
    width = (len(body)+15)//16*16
    for i in range(16):
        lo = 0x4000+i*width
        name = f'a{i:07}'.encode()
        struct.pack_into('>8sII', data, 0x100+i*16, name, lo, lo+width)
        data[lo:lo+len(body)] = body
    assert len(objects.members(data)) == 16
    struct.pack_into('>I', data, 0x100+8, 0)
    assert objects.members(data) == []


def test_directory_accepts_nonoverlapping_members_in_name_order():
    data=bytearray(0x10000)
    packed=zlib.compressobj(wbits=-15)
    body=packed.compress(object_data())+packed.flush()
    width=(len(body)+15)//16*16
    for i in range(16):
        lo=0x4000+(15-i)*width
        struct.pack_into('>8sII',data,0x100+i*16,f'a{i:07}'.encode(),lo,lo+width)
        data[lo:lo+len(body)]=body
    assert len(objects.members(data))==16

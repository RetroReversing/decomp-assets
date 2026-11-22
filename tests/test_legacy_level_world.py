import struct
import zlib

import pytest

from decompassets.n64 import legacy_level_world as world


def level():
    data = bytearray(0x1000)
    base = 0x8024b000
    struct.pack_into('>I',data,0,base+0x100)
    struct.pack_into('>II',data,0x138,base+0x200,base+0x400)
    commands = [(0xe7000000,0),(0xba000e02,0x8000),(0xfd100000,0x03000000),
                (0xf5000100,0x06000000),(0xf0000000,0x0603c000),(0xf5500000,0x07094250),
                (0xe6000000,0),(0xfd500000,0x03000020),(0xf3000000,0x070ff400),
                (0xf5400400,0x00094250),(0xf2000000,0x0007c07c),
                (0xe6000000,0),(0xb8000000,0)]
    for i,(a,b) in enumerate(commands):struct.pack_into('>II',data,0x200+i*8,a,b)
    data[0x400:0x420]=b'\xff\xff'*16
    return data


@pytest.mark.parametrize('damage',[None,'scene','pool','opcode','segment','palette','tile'])
def test_materials_require_bounded_legacy_commands(damage):
    data=level()
    if damage=='scene':struct.pack_into('>I',data,0,0)
    if damage=='pool':struct.pack_into('>I',data,0x13c,0)
    if damage=='opcode':data[0x200+7*8]=0
    if damage=='segment':data[0x200+7*8+4]=5
    if damage=='palette':data[0x400:0x420]=bytes(32)
    if damage=='tile':struct.pack_into('>I',data,0x200+10*8,0xf2000001)
    rows=world.textures(data)
    assert len(rows)==(1 if damage is None else 0)
    if rows:assert (rows[0]['width'],rows[0]['height'])==(32,32)


def test_directory_requires_bounded_inflatable_records():
    data=bytearray(0x10000)
    stream=zlib.compressobj(wbits=-15)
    body=stream.compress(level())+stream.flush()
    size=(len(body)+15)//16*16
    for i in range(8):
        lo=0x4000+i*size
        struct.pack_into('>5I',data,0x2000+i*32,lo,lo+size,0x3000,0x3100,0x80101000)
        data[lo:lo+len(body)]=body
    assert len(world.records(data))==8
    data[0x4000]=0xff
    assert world.records(data)==[]

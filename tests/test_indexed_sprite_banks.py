import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import indexed_sprite_banks as sprites


def fixture():
    data=bytearray(0x500);base=0x100;pal=0x60;anim=0x270;mapping=0x278;index=0x288;at=base+index
    frame=b'46d\0'+struct.pack('<HH',4,4)+bytes(16)
    data[base:base+len(frame)*3]=frame*3
    section=base+pal
    struct.pack_into('>II',data,section,8,528)
    data[section+8:section+12]=b'46d\0'
    data[section+12:section+524]=b'\xff\xff'*256
    data[section+524:section+528]=b'\xff'*4
    data[base+mapping:base+mapping+7]=b'46d\0\0\0\0'
    struct.pack_into('>8I',data,at,0,pal,anim,mapping,index,0,0,0)
    struct.pack_into('>4I',data,at+32,0,24,48,72)
    return bytes(data)


def test_bank_finds_frame_and_palette_mapping():
    rom=fixture();found=sprites.regions(rom)
    assert len(found)==1 and found[0]['texture_count']==3
    assert sprites.preview(rom,found[0],{'texture':2})['mime']=='image/png'
    with pytest.raises(AssetError):sprites.preview(rom,found[0],{'texture':3})


def test_rejects_invalid_palette_or_dimensions():
    rom=bytearray(fixture());rom[0x100+0x60+524:0x100+0x60+528]=bytes(4)
    assert sprites.regions(bytes(rom))==[]
    rom=bytearray(fixture());struct.pack_into('<H',rom,0x100+4,0xffff)
    assert sprites.regions(bytes(rom))==[]

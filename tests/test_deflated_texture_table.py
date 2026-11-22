import struct
import zlib

from decompassets.n64 import deflated_texture_table as tex


def raw_deflate(data):
    obj=zlib.compressobj(wbits=-15)
    return obj.compress(data)+obj.flush()


def texture(indices=b'\0\1\1\0'):
    return b'\x40\x09\x01\x00\x01\xff\xff\x02\x02\x11\x72' + raw_deflate(indices)


def fixture():
    item=texture();base=0x110000
    table=(struct.pack('>II',len(item),0)*128)+struct.pack('>II',0xffff,0)
    stream=b'\x11\x72'+raw_deflate(table)
    rom=bytearray(base+128*len(item)+16)
    struct.pack_into('>II',rom,0x1000,0x3c040011,0x24840000)
    rom[0x2000:0x2000+len(stream)]=stream
    rom[base:base+128*len(item)]=item*128
    return bytes(rom)


def test_texture_validates_bounds_and_palette_indices():
    assert tex.image(texture()) is not None
    assert tex.image(texture(b'\0\1\2\0')) is None
    assert tex.image(texture()[:-1]) is None


def test_code_and_inflated_size_table_locate_images():
    rom=fixture();assets=tex.regions(rom)
    assert len(assets)==128 and assets[0]['offset']==0x110000
    assert tex.preview(rom,assets[-1],{})['mime']=='image/png'
    damaged=bytearray(rom);damaged[0x1000:0x1008]=bytes(8)
    assert tex.regions(bytes(damaged))==[]

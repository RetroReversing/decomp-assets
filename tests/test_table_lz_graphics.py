"""Table-indexed LZ graphics require both resource and runtime evidence."""
import struct

import pytest

from decompassets import n64
from decompassets.n64 import runtime_packed_graphics, table_lz_graphics


def literal(data):
    bits = ''.join('1'+format(byte, '08b') for byte in data) + '0'*15
    bits += '0'*(-len(bits)%8)
    return bytes(int(bits[i:i+8], 2) for i in range(0, len(bits), 8))


def fixture(zero_prefix=False, model=False):
    blocks = [bytes((i*29+j*13)%256 for i in range(256)) for j in range(4)]
    if model:
        vertices = bytearray(blocks[0])
        for index,(x,y) in enumerate(((0,0),(100,0),(0,100))):
            struct.pack_into('>3h',vertices,16*index,x,y,0)
            vertices[16*index+6:16*index+8] = b'\0\0'
        blocks[0] = bytes(vertices)
    if zero_prefix:
        blocks[0] = bytes(64) + blocks[0][64:]
    image = bytearray(0x1000)
    bounds = []
    for data in blocks:
        start = len(image)
        image.extend(literal(data))
        image.extend(bytes(-len(image)%16))
        bounds.append((start,len(image)))
    for index,(start,end) in enumerate(bounds):
        struct.pack_into('>II',image,0x20+index*8,start,end)
    ram = bytearray(4096)
    ram[0x800:0x900] = blocks[0]
    commands = [(0xfd900000,0x80000800),(0xf5900000,0x07000000),(0xe6000000,0),
                (0xf3000000,0x0707f000),(0xe7000000,0),(0xf5800800,0),
                (0xf2000000,(63 << 14)|(7 << 2)),(0xdf000000,0)]
    for index,(first,second) in enumerate(commands):
        struct.pack_into('>II',ram,index*8,first,second)
    if model:
        struct.pack_into('>6I',ram,56,0x04000c2f,0x80000800,0xbf000000,0x00000204,0xb8000000,0)
    return image, ram, blocks, bounds


def test_runtime_texture_needs_complete_table_stream_and_matching_ram():
    image, ram, blocks, bounds = fixture()
    assert table_lz_graphics.descriptors(image) == bounds
    assert table_lz_graphics.inflate(image[bounds[0][0]:bounds[0][1]])[0] == blocks[0]
    assets = runtime_packed_graphics.regions(image,[ram])
    asset, = [a for a in assets if a['layout'] == table_lz_graphics.TEXTURES]
    assert n64.preview(image,asset,{})['mime'] == 'image/png'
    ram[0x880] ^= 1
    assert not any(a['layout'] == table_lz_graphics.TEXTURES for a in runtime_packed_graphics.regions(image,[ram]))
    image[0x20+8:0x20+12] = bytes(4)
    assert not table_lz_graphics.descriptors(image)


def test_stream_is_bounded_and_cancellation_is_not_swallowed():
    encoded = literal(bytes(range(128)))
    assert table_lz_graphics.inflate(encoded[:-3]) is None
    def stop(): raise ValueError('cancelled')
    with pytest.raises(ValueError,match='cancelled'):
        table_lz_graphics.inflate(encoded,stop)


def test_ring_backreference_can_overlap_the_write_cursor():
    bits = '1' + format(ord('A'), '08b') + '0' + format(1, '014b') + format(3, '04b') + '0'*15
    bits += '0'*(-len(bits)%8)
    encoded = bytes(int(bits[i:i+8], 2) for i in range(0, len(bits), 8))
    assert table_lz_graphics.inflate(encoded)[0] == b'A'*7


def test_texture_with_a_uniform_prefix_can_use_later_matching_texels():
    image, ram, _, _ = fixture(zero_prefix=True)
    assets = runtime_packed_graphics.regions(image, [ram])
    assert any(a['layout'] == table_lz_graphics.TEXTURES for a in assets)


def test_runtime_model_uses_the_same_validated_decoder():
    image, ram, _, _ = fixture(model=True)
    assets = runtime_packed_graphics.regions(image, [ram])
    model = next(a for a in assets if a['kind'] == '3d model' and a.get('codec') == 'table-lz')
    assert n64.preview(image, model, {})['triangles'] == 1
    ram[0x810] ^= 1
    assert not any(a['kind'] == '3d model' and a.get('codec') == 'table-lz'
                   for a in runtime_packed_graphics.regions(image, [ram]))

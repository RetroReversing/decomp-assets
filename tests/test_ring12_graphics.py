"""Table-indexed 12-bit ring streams need runtime graphics evidence."""
import struct

import pytest

from decompassets import n64
from decompassets.n64 import ring12_graphics, runtime_packed_graphics


def literal(data):
    out = bytearray()
    while len(data) >= 8:
        out.append(0xff)
        out.extend(data[:8])
        data = data[8:]
    out.append((1 << len(data))-1)
    out.extend(data)
    out.extend(b'\0\0')
    return bytes(out)


def fixture(repeated_prefix=False):
    blocks = [bytes((i*29+j*13)%256 for i in range(256)) for j in range(4)]
    if repeated_prefix:
        blocks[0] = blocks[0][:128] + blocks[0][:64] + blocks[0][192:]
    image = bytearray(0x1000)
    starts = []
    for data in blocks:
        starts.append(len(image))
        image.extend(literal(data))
        image.extend(bytes(-len(image)%16))
    starts.append(len(image))
    image.extend(bytes(16))
    for index,start in enumerate(starts):
        struct.pack_into('>I',image,0x20+index*4,start)
    ram = bytearray(4096)
    ram[0x800:0x900] = blocks[0]
    commands = [(0xfd900000,0x80000800),(0xf5900000,0x07000000),(0xe6000000,0),
                (0xf3000000,0x0707f000),(0xe7000000,0),(0xf5800800,0),
                (0xf2000000,(63 << 14)|(7 << 2)),(0xdf000000,0)]
    for index,(first,second) in enumerate(commands):
        struct.pack_into('>II',ram,index*8,first,second)
    return image, ram, blocks, starts


def test_pointer_table_stream_and_runtime_texture_must_all_agree():
    image, ram, blocks, starts = fixture(repeated_prefix=True)
    assert ring12_graphics.descriptors(image) == list(zip(starts,starts[1:]))
    assert ring12_graphics.inflate(image[starts[0]:starts[1]])[0] == blocks[0]
    assets = runtime_packed_graphics.regions(image,[ram])
    asset, = [a for a in assets if a['layout'] == ring12_graphics.TEXTURES]
    assert n64.preview(image,asset,{})['mime'] == 'image/png'
    ram[0x8e0] ^= 1
    assert not any(a['layout'] == ring12_graphics.TEXTURES for a in runtime_packed_graphics.regions(image,[ram]))
    image[0x24:0x30] = bytes(12)
    assert not ring12_graphics.descriptors(image)


def test_ring_overlap_termination_and_cancellation():
    encoded = bytes([1,ord('A'),3,1,0,0])
    assert ring12_graphics.inflate(encoded)[0] == b'A'*6
    assert ring12_graphics.inflate(encoded[:-1]) is None
    def stop(): raise ValueError('cancelled')
    with pytest.raises(ValueError,match='cancelled'):
        ring12_graphics.inflate(encoded,stop)

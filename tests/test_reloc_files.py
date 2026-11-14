"""A table of relocatable files with display lists and sprites, one file VPK0-packed: homemade data only."""
import base64
import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import reloc_files, vpk0

from .test_rom_assets import pixels

END = 0xFFFF


class Bits:
    def __init__(self):
        self.bits = ''

    def put(self, value, count):
        self.bits += format(value, f'0{count}b') if count else ''

    def bytes(self):
        padded = self.bits + '0' * (-len(self.bits) % 8)
        return bytes(int(padded[i:i+8], 2) for i in range(0, len(padded), 8))


def pack(raw, back=None):
    """A method-0 VPK0 stream: 8-bit distances, 5-bit lengths, literals, and one back-reference (at, distance, length)."""
    bits = Bits()
    for leaf in (8, 5):
        bits.put(0, 1);bits.put(leaf, 8);bits.put(1, 1)
    at = 0
    while at < len(raw):
        if back and at == back[0]:
            bits.put(1, 1);bits.put(back[1], 8);bits.put(back[2], 5);at += back[2]
        else:
            bits.put(0, 1);bits.put(raw[at], 8);at += 1
    stream = b'vpk0' + struct.pack('>I', len(raw)) + b'\0' + bits.bytes()
    return stream + bytes(-len(stream) % 4)


def link(following, target):
    return struct.pack('>HH', following, target // 4)


def first_file():
    """A display list loading an RGBA16 4×2 image, and an I8 8×2 sprite stored with its odd row swapped."""
    data = bytearray(0xA8)
    commands = [(0xFD100000, None), (0xF5100000, 0x07000000), (0xF3000000, 0x07007800), (0xF5100200, 0),
                (0xF2000000, 0x0000C004), (0xDF000000, 0)]
    for k, (w0, w1) in enumerate(commands):struct.pack_into('>I', data, 8*k, w0);struct.pack_into('>I', data, 8*k+4, w1 or 0)
    data[0x30:0x40] = bytes.fromhex('f801') * 8                            # red texels
    struct.pack_into('>4h2f', data, 0x40, 0, 0, 8, 2, 1.0, 1.0)           # sprite: x, y, width, height, scale
    struct.pack_into('>2h', data, 0x40 + 40, 1, 0)                        # one bitmap
    struct.pack_into('>2h2B', data, 0x40 + 44, 2, 2, 4, 1)                # strip height, I8
    struct.pack_into('>4h', data, 0x88, 8, 8, 0, 0)                       # bitmap: width, row width
    struct.pack_into('>h', data, 0x88 + 12, 2)                            # two rows
    data[0x98:0xA8] = bytes([0x00]*8) + bytes([0xFF]*4 + [0x80]*4)        # row 1 stored swapped
    # Internal chain: the image's address (word 1) -> texels, the sprite's bitmap pointer -> bitmap, its buffer -> texels.
    data[4:8] = link(29, 0x30);data[0x74:0x78] = link(36, 0x88);data[0x90:0x94] = link(END, 0x98)
    return bytes(data), 1


def table(files):
    """files: (data, packed bytes or None, intern, extern, extern ids)."""
    head, body = b'', b''
    for data, packed, intern, extern, ids in files:
        stored = packed or data
        head += struct.pack('>IHHHH', len(body) | (0x80000000 if packed else 0), intern, len(stored)//4, extern, len(data)//4)
        body += stored + ids + bytes(-len(ids) % 4)
    return head + struct.pack('>IHHHH', len(body), 0, 0, 0, 0) + body


def build():
    data, intern = first_file()
    # File 1 points at file 0's texels from outside: an RGBA16 4×2 image through its external chain.
    other = bytearray(0x30)
    for k, (w0, w1) in enumerate([(0xFD100000, 0), (0xF5100000, 0x07000000), (0xF3000000, 0x07007800),
                                  (0xF5100200, 0), (0xF2000000, 0x0000C004), (0xDF000000, 0)]):
        struct.pack_into('>II', other, 8*k, w0, w1)
    other[4:8] = link(END, 0x98)
    raw = bytes(range(16)) * 2
    files = [(data, None, intern, END, b''), (bytes(other), None, END, 1, struct.pack('>H', 0)),
             (raw, pack(raw, (16, 16, 16)), END, END, b'')]
    files += [(bytes(4), None, END, END, b'')] * 32
    return bytes(64) + table(files)


def test_vpk0_unpacks_literals_and_back_references():
    raw = bytes(range(16)) * 2
    assert vpk0.unpack(pack(raw, (16, 16, 16))) == raw
    with pytest.raises(AssetError):vpk0.unpack(pack(raw, (16, 17, 16)))   # reaches before the start
    with pytest.raises(AssetError):vpk0.unpack(b'vpk0' + bytes(8))


def test_file_table_textures_are_found_through_pointer_chains():
    image = build()
    at, files = reloc_files.find(image)
    assert at == 64 and len(files) == 35 and files[2]['compressed']
    assert reloc_files.unpack(image, files[2]) == bytes(range(16)) * 2
    found = reloc_files.regions(image)
    assert [a['file'] for a in found] == [0]
    textures = [(t['offset'], t['format'], t['width'], t['height']) for t in found[0]['textures']]
    assert sorted(textures) == [(0x30, 'rgba5551-be', 4, 2), (0x98, 'i8', 8, 2), (0x98, 'rgba5551-be', 4, 2)]
    assert [a['layout'] for a in n64.regions(image) if a.get('layout') == 'reloc-file'] == ['reloc-file']
    red = pixels(base64.b64decode(n64.preview(image, found[0], {'texture': 0})['data_url'].split(',')[1]))
    assert red[:4] == bytes([255, 0, 0, 255])
    sprite_index = next(k for k, t in enumerate(found[0]['textures']) if t['format'] == 'i8')
    sprite = pixels(base64.b64decode(n64.preview(image, found[0], {'texture': sprite_index})['data_url'].split(',')[1]))
    assert sprite[8*4:8*4+4] == bytes([0x80, 0x80, 0x80, 255]) and sprite[12*4:12*4+4] == bytes([255, 255, 255, 255])


def test_tables_that_do_not_chain_are_not_taken():
    image = bytearray(build())
    struct.pack_into('>I', image, 64 + 12*5, 0x10)                     # a file starting inside an earlier one
    assert reloc_files.find(bytes(image)) == (None, None)
    assert reloc_files.regions(bytes(64) + table([(bytes(4), None, END, END, b'')] * 8)) == []   # too few files

import base64
import mmap
import struct

import pytest

from decompassets import n64
from decompassets.n64 import yay0_atlases


def test_cached_loader_table_requires_four_non_overlapping_atlases():
    fake = b'Yay0\0\0\x10\0' + bytes(8)
    payload = struct.pack('>8I',0xb0000020,16,0xb0000030,16,0xb0000040,16,0xb0000050,16)
    image = payload+fake*4
    assert yay0_atlases._table(image,0)==[(32,48),(48,64),(64,80),(80,96)]
    assert yay0_atlases._table(image[:-1],0)==[]
    repeated = payload[:8]+payload[:8]+payload[16:]+fake*4
    assert yay0_atlases._table(repeated,0)==[]
    assert yay0_atlases.regions(image)==[]


def test_texture_preview_dispatch_decodes_the_native_ia4_layout():
    crunch64 = pytest.importorskip('crunch64')
    payload = crunch64.yay0.compress(bytes([255])*4096)
    asset = dict(offset=0,size=len(payload),layout=yay0_atlases.LAYOUT,label='Glyph atlas')
    result = n64.preview(payload,asset,{})
    image = base64.b64decode(result['data_url'].split(',',1)[1])
    assert image[:8]==b'\x89PNG\r\n\x1a\n'
    assert struct.unpack_from('>II',image,16)==(128,64)


def test_find_atlas_in_a_memory_mapped_cartridge(tmp_path):
    crunch64 = pytest.importorskip('crunch64')
    payload = crunch64.yay0.compress(bytes([255])*4096)
    loader = struct.pack('>7I', 0x8d230000, 0x8d27001c, 0xae240000, 0x26730008,
                         0x26310004, 0x3c028000, 0x24552000)
    drawer = struct.pack('>9I', *(0x3c010000 | word for word in yay0_atlases._DRAW_LUI),
                         *(0x34210000 | word for word in yay0_atlases._DRAW_ORI))
    table_offset = len(loader) + len(drawer)
    payload_offset = table_offset + 32
    offsets = [payload_offset + index * len(payload) for index in range(4)]
    table = struct.pack('>8I', *(word for offset in offsets for word in (0xb0000000 + offset, len(payload))))
    file = tmp_path / 'image'
    file.write_bytes(loader + drawer + table + payload*4)

    def read(pc, code, **kwargs):
        addresses = range(0x80001000, 0x80001020, 4) if pc == 0 else range(0x80002000, 0x80002010, 4)
        return dict(events=[dict(kind='load', width=4, place=dict(kind='constant', value=address))
                            for address in addresses])

    context = dict(read_code=read,
                   functions=[dict(vram=0, rom_offset=0, size=len(loader)),
                              dict(vram=4, rom_offset=len(loader), size=len(drawer))],
                   segments=[dict(vram=0x80001000, rom_start=table_offset, rom_end=payload_offset)])
    with file.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
        assert [atlas['offset'] for atlas in yay0_atlases.regions(image, context=context)] == offsets

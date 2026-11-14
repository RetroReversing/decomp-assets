"""UVTX texture files in a UV filesystem of FORM files: homemade data only."""
import base64
import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import uv_textures

from .test_rom_assets import pixels

RED, GREEN = bytes.fromhex('f801'), bytes.fromhex('07c1')


def mio0(raw):
    """A literal-only MIO0 stream: every mask bit set, no back-references."""
    mask = bytes([0xFF]*((len(raw) + 7)//8))
    mask += bytes(-len(mask) % 4)
    data = 16 + len(mask)
    return b'MIO0' + struct.pack('>III', len(raw), data, data) + mask + raw


def chunk(tag, body):
    return tag + struct.pack('>I', len(body)) + body


def uvtx(comm, packed=False):
    body = chunk(b'GZIP', b'COMM' + struct.pack('>I', len(comm)) + mio0(comm)) if packed else chunk(b'COMM', comm)
    inner = b'UVTX' + chunk(b'PAD ', bytes(4)) + body
    return b'FORM' + struct.pack('>I', len(inner)) + inner


def comm(header, texels, commands, width, height):
    words = b''.join(struct.pack('>II', *c) for c in commands)
    return (struct.pack('>HH', len(texels), len(commands)) + bytes(header - 4) + texels + words
            + struct.pack('>HH', width, height) + bytes(24))


# An RGBA16 4×2 tile: block load with a row step, tile 0 one 64-bit word per row, Fast3D end.
RGBA16 = [(0xFD100000, 0), (0xF5100000, 0x07000000), (0xF3000000, 0x07007800), (0xF5100200, 0),
          (0xF2000000, 0x0000C004), (0xB8000000, 0)]
# An I4 16×2 tile loaded with no row step (dxt 0), so its odd row is stored swapped; F3DEX2-style end.
I4 = [(0xFD100000, 0), (0xF5100000, 0x07000000), (0xF3000000, 0x07007000), (0xF5800200, 0),
      (0xF2000000, 0x0003C004), (0xDF000000, 0)]


def test_uvtx_files_are_found_raw_and_packed_and_previewed():
    rgba = RED*2 + GREEN*2 + GREEN*4
    row0, row1 = bytes([0xF0]*4 + [0x00]*4), bytes([0x0F]*4 + [0xFF]*4)
    stored = row0 + row1[4:] + row1[:4]
    image = bytes(16) + uvtx(comm(20, rgba, RGBA16, 4, 2)) + uvtx(comm(28, stored, I4, 16, 2), packed=True)
    found = uv_textures.regions(image)
    assert [(a['offset'], a['codec'], a['preview_settings']['format'], a['preview_settings']['width'],
             a['preview_settings']['height']) for a in found] == [(16, 'raw', 'rgba5551-be', 4, 2),
                                                                  (found[1]['offset'], 'MIO0', 'i4', 16, 2)]
    assert found[1]['offset'] == 16 + found[0]['size']
    assert [a['layout'] for a in n64.regions(image) if a.get('layout') == 'uv-texture'] == ['uv-texture']*2
    shown = pixels(base64.b64decode(n64.preview(image, found[0], {})['data_url'].split(',')[1]))
    assert shown[:4] == bytes([255, 0, 0, 255]) and shown[16:20] == bytes([0, 255, 0, 255])
    shown = pixels(base64.b64decode(n64.preview(image, found[1], {})['data_url'].split(',')[1]))
    assert shown[16*4:16*4+4] == bytes([0, 0, 0, 255])                   # row 1 starts with the 0x0F bytes unswapped
    assert shown[24*4:24*4+4] == bytes([255, 255, 255, 255])


def test_uvtx_files_that_do_not_hold_together_are_left_out():
    rgba = RED*8
    unended = uvtx(comm(20, rgba, RGBA16[:-1] + [(0xE7000000, 0)], 4, 2))
    short = uvtx(comm(20, rgba[:8], RGBA16, 4, 2))                         # the tile reads past the texels
    ci4 = [(0xFD100000, 0), (0xF5100000, 0x07000000), (0xF3000000, 0x07007800), (0xF5400200, 0),
           (0xFD100000, 0), (0xF0000000, 0x0703C000), (0xF2000000, 0x0001C004), (0xDF000000, 0)]
    borrowed = uvtx(comm(20, rgba, ci4, 8, 2))                             # its palette is another file's
    assert uv_textures.regions(unended + short + borrowed) == []
    image = uvtx(comm(20, rgba, RGBA16, 4, 2))
    asset = uv_textures.regions(image)[0]
    with pytest.raises(AssetError):uv_textures.preview(image[:-30] + bytes(30), dict(asset, offset=1), {})

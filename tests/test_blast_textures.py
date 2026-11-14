"""A texture table of back-reference-packed textures: homemade data only."""
import base64
import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import blast_textures

from .test_rom_assets import pixels


def rgba16_words(columns, rows):
    """Codec-1 halfwords for an image whose texels differ along a row and repeat down it, then a back-reference."""
    words = [x << 6 | x for x in range(columns)]
    # Each later row copies the one before it: back 2*columns bytes, `columns` texels.
    words += [0x8000 | (columns*2) << 5 | columns] * (rows - 1)
    return struct.pack(f'>{len(words)}H', *words)


def build(resources, count=64):
    """A table of `count` entries (the rest empty, pointing at the end) followed by the resources it lists."""
    head, body, offset = b'', b'', 8*count
    for codec, packed in resources:
        head += struct.pack('>IHH', offset, len(packed), codec)
        packed += bytes(-len(packed) % 8)
        body += packed;offset += len(packed)
    head += struct.pack('>IHH', offset, 0, 0) * (count - len(resources))
    return head + body


def test_texture_table_textures_unpack_with_their_width_inferred():
    lut = bytes(range(256))                                   # a colour table, then a codec-5 texture that reads it
    image = bytes(24) + build([(1, rgba16_words(16, 8)), (0, lut), (5, struct.pack('>16H', *range(0x10, 0x110, 0x10))),
                               (1, rgba16_words(16, 16))])
    found = blast_textures.regions(image)
    assert [(a['codec'], a['preview_settings']['width'], a['preview_settings']['height']) for a in found] == [(1, 16, 8), (5, 4, 4), (1, 16, 16)]
    assert found[1]['codec'] == 5 and found[1]['lut'] == 24 + 64*8 + 8*((len(rgba16_words(16, 8)) + 7)//8)
    assert all(a['layout'] == 'blast' and a['confidence'] == 'inferred' for a in found)
    assert len([a for a in n64.regions(image) if a.get('layout') == 'blast']) == 3
    shown = pixels(base64.b64decode(n64.preview(image, found[0], {})['data_url'].split(',')[1]))
    assert shown[:16*4] == shown[16*4:32*4] and shown[:4] != shown[4:8]  # rows repeat, texels along a row differ
    assert n64.preview(image, found[0], {'width': 32})['details']['width'] == 32
    with pytest.raises(AssetError):n64.preview(image, found[0], {'width': 7})


def test_codecs_unpack_their_own_packings():
    assert blast_textures.unpack(1, struct.pack('>H', 0x0041)) == struct.pack('>H', 0x0081)
    assert blast_textures.unpack(3, struct.pack('>H', 0x7F01)) == bytes((0xFE, 0x02))
    assert blast_textures.unpack(6, struct.pack('>H', 0x3F09)) == bytes((0xEE, 0x22))
    assert blast_textures.unpack(1, struct.pack('>HH', 0x0001, 0x8041)) == struct.pack('>HH', 1, 1)
    with pytest.raises(AssetError):blast_textures.unpack(1, struct.pack('>H', 0x8041))      # reaches before the start
    with pytest.raises(AssetError):blast_textures.unpack(5, struct.pack('>H', 1))          # no colour table


def test_tables_that_do_not_chain_are_not_taken():
    good = build([(1, rgba16_words(16, 8))])
    assert blast_textures.table(good, 0)
    broken = bytearray(good)
    for k in range(8, 8*64, 8):struct.pack_into('>I', broken, k, 8*k)     # offsets that skip ahead every entry
    assert blast_textures.table(bytes(broken), 0) is None
    assert blast_textures.regions(bytes(64) + struct.pack('>IHH', 0x40, 4, 9) + bytes(64)) == []

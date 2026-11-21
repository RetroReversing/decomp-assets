import base64
import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import lz_texture_directories as reader
from decompassets.n64 import preview, regions


def _pack(data):
    packed = bytearray()
    for offset in range(0, len(data), 8):
        literals = data[offset:offset+8]
        packed.append((1 << len(literals)) - 1)
        packed.extend(literals)
    return bytes(packed) + (b'\0\0' if len(data)%8 else b'\0\0\0')


def _texture():
    data = bytearray(136)
    struct.pack_into('>10I', data, 0, 80, len(data), 80, 112, 0, 1, 1, 80, 80, 0)
    data[40:42] = b'\x10\0'
    struct.pack_into('>H', data, 50, 0xf801)
    struct.pack_into('>16s4H2I', data, 80, b'Marker', 4, 1, 2, 0, 40, 0)
    struct.pack_into('>16s2I', data, 112, b'Marker', 0x000f8000, 48)
    return bytes(data)


def _rom():
    image = bytearray(0x400)
    for index in range(128):
        start = len(image)
        struct.pack_into('>I', image, index*4, start)
        compressed = _pack(_texture()) if index < 8 else bytes(3)
        image.extend(compressed)
        image.extend(bytes(-len(image)%16))
    image[512:516] = b'\xff' * 4
    return image


def test_catalog_and_png_require_bounded_directory():
    image = _rom()
    assets = [a for a in regions(image) if a.get('layout') == reader.LAYOUT]
    assert len(assets) == 8
    asset = assets[0]
    assert asset['textures'][0]['label'] == 'Marker'
    result = preview(image, asset, {})
    png = base64.b64decode(result['data_url'].split(',')[1])
    compressed = struct.unpack_from('>I', png, 33)[0]
    assert zlib.decompress(png[41:41+compressed]) == bytes((0, 255, 0, 0, 255)) + bytes(12)
    image[512] = 0
    assert not reader.regions(image)


def test_dictionary_positions_and_truncation():
    assert reader.unpack(bytes.fromhex('01 41 00 01 00 00'))[0] == b'AAA'
    with pytest.raises(AssetError, match='match'):
        reader.unpack(bytes.fromhex('00 01 02'))
    with pytest.raises(AssetError, match='literal'):
        reader.unpack(bytes.fromhex('01'))


def test_palette_slots_and_rows_from_split_render_tiles():
    data = bytearray(0x180)
    commands = [(0xfd100000, 0x28), (0xf3000000, 0), (0xfd100000, 0x40),
                (0xf0000000, 0x3c000), (0xfd100000, 0x60), (0xf0000000, 0x3c000),
                (0xf5400000, 0), (0xf2000000, 0x0000c004),
                (0xf5400000, 0x01100000), (0xf2000000, 0x0100c000), (0xdf000000, 0)]
    for i, row in enumerate(commands):
        struct.pack_into('>II', data, 0x100+i*8, *row)
    offset, palettes, stripes = reader._list_texture(data, 0x100, len(data), 0x100, 4, 3)
    settings = dict(format='ci4', width=4, height=3, offset=offset)
    rows = reader._pixel_rows(data, settings, stripes, palettes, 0x40)
    assert [(r['offset'], r['height'], r['palette_offset']) for r in rows] == [(0x28, 2, 0x40), (0x2c, 1, 0x60)]

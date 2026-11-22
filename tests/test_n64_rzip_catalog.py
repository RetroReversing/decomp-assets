import struct
import zlib

from decompassets.n64 import rzip_catalog


def _pack(data):
    compressor = zlib.compressobj(wbits=-15)
    return struct.pack('>I', len(data)) + compressor.compress(data) + compressor.flush()


def _fixture():
    # Display commands identify both the indexed pixels and the palette at the end.
    tile = 0xf5000000 | (2 << 21) | (4 << 9)
    commands = struct.pack('>8I', 0xfd500000, 0, tile, 0, 0xfd100000, 0x800000, 0xdf000000, 0)
    texture = bytes([0x11] * 2048 + [0xff, 0xff] * 16)
    image = bytearray(16)
    image.extend(_pack(texture) * 32)
    image.extend(bytes((-len(image)) % 16))
    table = len(image)
    image.extend(bytes(8 * 8))
    for bank in range(8):
        start = len(image)
        image.extend(bytes(4 * 8))
        for entry in range(4):
            raw = commands if bank == entry == 0 else b'other content'
            encoded = _pack(raw)
            offset = len(image) - start
            struct.pack_into('>II', image, start + entry * 8, offset, 0x10000000 | len(encoded))
            image.extend(encoded)
        struct.pack_into('>II', image, table + bank * 8, start - table, len(image) - start)
    return bytes(image), table


def test_catalog_finds_indexed_textures_and_previews():
    image, table = _fixture()
    catalogs = list(rzip_catalog.catalogs(image))
    assert len(catalogs) == 1
    assert catalogs[0][0] == table
    assert len(catalogs[0][2]) == 32
    assets = rzip_catalog.regions(image)
    assert len(assets) == 1
    assert assets[0]['texture_count'] == 1
    assert assets[0]['textures'][0]['preview_settings']['format'] == 'ci4'
    result = rzip_catalog.preview(image, assets[0], {})
    assert result['mime'] == 'image/png'
    assert result['details']['width'] == result['details']['height'] == 64
    assert result['data_url'].startswith('data:image/png;base64,')


def test_catalog_rejects_broken_outer_table_and_stream():
    image, table = _fixture()
    broken = bytearray(image)
    struct.pack_into('>I', broken, table + 8, 1)
    assert not list(rzip_catalog.catalogs(broken))
    broken = bytearray(image)
    broken[16] = 0xff
    assert not list(rzip_catalog.catalogs(broken))


def test_texture_requires_palette_and_matching_dimensions():
    flat = [(0, 1, 2080)]
    assert not rzip_catalog._texture_refs(struct.pack('>4I', 0xfd500000, 0, 0xdf000000, 0), flat)

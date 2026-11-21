import struct

from decompassets import n64
from decompassets.n64 import inline_meshes, inline_tiles

_BASE = 0x80100000


def test_adjacent_tiles_validate_pixels_and_palette():
    image = bytearray(256)
    for start in (0, 32):
        struct.pack_into('>4H2I', image, start, 4, 4, 2, 0, _BASE+160, _BASE+start+24)
        image[start+16] = 0xdf
        image[start+24:start+32] = bytes([0x11])*8
    struct.pack_into('>H', image, 162, 0xf801)
    tiles = inline_tiles.regions(image)
    assert [a['offset'] for a in tiles] == [24, 56]
    for asset in tiles:
        result = n64.preview(image, asset, {})
        assert result['data_url'].startswith('data:image/png;base64,')
    struct.pack_into('>I', image, 44, _BASE+64)
    assert inline_tiles.regions(image) == []


def test_linked_headers_resolve_the_directory_vertex_base():
    image = bytearray(0x400)
    headers = tuple(range(0x100, 0x240, 0x40))
    for i, point in enumerate(((0, 0), (9, 0), (0, 9))):
        struct.pack_into('>3hH', image, 0x40+16*i, *point, 0, 0)
    for i, start in enumerate(headers):
        previous = _BASE+headers[i-1]+32 if i else 0
        struct.pack_into('>4I', image, start+16, previous, 0x101, 0xffffffff, 0x7f7f7f00)
        struct.pack_into('>8I', image, start+32, 0x01003006, 0x01000000, 0x05000204, 0,
                         0xe7000000, 0, 0xdf000000, 0)
    struct.pack_into('>3I', image, 0x300, _BASE+0x40, _BASE+headers[1], 0)
    asset, = inline_meshes.regions(image)
    assert asset['offset'] == headers[0]+32
    preview = n64.preview(image, asset, {})
    assert preview['vertices'] == [(0, 0, 0), (9, 0, 0), (0, 9, 0)]
    assert preview['triangles'] == 1
    struct.pack_into('>I', image, headers[0]+36, 0x01000100)
    assert not inline_meshes.regions(image)

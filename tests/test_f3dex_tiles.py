import base64
import struct

from decompassets.n64 import f3dex_tiles


def test_adjacent_f3dex_tiles_validate_mapping_and_preview():
    image = bytearray(256)
    base = 0x80100000
    setup = bytes.fromhex('fd50000000000000f550000007018060f3000000071df2abf540060000018060b800000000000000')
    for at in (0, 96):
        struct.pack_into('>4H2I', image, at, 4, 4, 2, 0, base+at+64, base+at+56)
        image[at+16:at+56] = setup
        image[at+56:at+64] = b'\x12'*8
        struct.pack_into('>HH', image, at+66, 0xf801, 0x07c1)
    assets = f3dex_tiles.regions(image)
    assert [a['offset'] for a in assets] == [56, 152]
    result = f3dex_tiles.preview(image, assets[0], {})
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')
    struct.pack_into('>I', image, 108, base+160)
    assert f3dex_tiles.regions(image) == []

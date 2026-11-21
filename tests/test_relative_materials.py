import base64
import struct

from decompassets import n64

from .test_rom_assets import pixels


def fixture(*, pointer=88, closing=0xb8000000):
    commands = [(0xe7000000, 0), (0xba001402, 0), (0xbb000001, 0x80008000),
                (0xfd100000, pointer), (0xf5100000, 0x07000000), (0xe6000000, 0),
                (0xf3000000, 0x07007800), (0xe7000000, 0), (0xf5100200, 0),
                (0xf2000000, 0x0000c004), (closing, 0)]
    return bytes(32) + b''.join(struct.pack('>II', *pair) for pair in commands) + bytes.fromhex('f80107c1')*4


def test_closed_material_supplies_relative_texel_address_and_dimensions():
    data = fixture()
    asset, = [row for row in n64.regions(data) if row['kind'] == 'image']
    assert asset['offset'] == 120
    assert asset['preview_settings']['width'] == 4
    assert asset['preview_settings']['height'] == 2
    preview = n64.preview(data, asset, {})
    shown = pixels(base64.b64decode(preview['data_url'].split(',')[1]))
    assert shown[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])


def test_bad_material_extent_is_not_identified_as_a_texture():
    for data in (fixture(pointer=80), fixture(closing=0), fixture()[:-1]):
        assert not [row for row in n64.regions(data) if row['kind'] == 'image']

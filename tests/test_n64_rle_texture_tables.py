import struct

from decompassets.n64 import rle_texture_tables as rle


def _fixture():
    image = bytearray(0x500)
    # Native code references the table in RAM and a bounded cartridge bank.
    words = (0x3c038000, 0x24630200, 0x3c030000, 0x24630400,
             0x3c020000, 0x08000000, 0x24420500)
    struct.pack_into('>7I', image, 0x40, *words)
    for index in range(5):
        struct.pack_into('>II4B', image, 0x200+index*12, index*4, 0, 2, 2, 0, 0)
        struct.pack_into('>2H', image, 0x400+index*4, 33, 0xf800)
    context = dict(segments=[dict(rom_start=0, rom_end=len(image), vram=0x80000000)],
                   functions=[dict(rom_offset=0x40, size=28)])
    return bytes(image), context


def test_referenced_table_and_bounded_texture_preview():
    image, context = _fixture()
    assets = rle.regions(image, context=context)
    assert len(assets) == 4
    result = rle.preview(image, assets[0], {})
    assert result['details']['width'] == 4 and result['details']['height'] == 4
    assert result['data_url'].startswith('data:image/png;base64,')


def test_run_bounds_and_previous_color():
    assert rle._inflate(bytes.fromhex('0002 f83e 0002 f83e'), 1, 1) == bytes.fromhex('0003 0002 0003 0002')
    assert rle._inflate(bytes.fromhex('ffff f800'), 1, 1) is None
    assert rle._inflate(bytes.fromhex('f83e'), 1, 1) is None

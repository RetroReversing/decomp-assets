import struct

import pytest

from decompassets import formats
from decompassets.n64 import runtime_textures


def fixture():
    image = bytearray(4096)
    ram = bytearray(4096)
    pixels = bytes((i * 29) % 256 for i in range(256))
    image[1024:1280] = pixels
    ram[2048:2304] = pixels
    commands = [(0xfd900000, 0x80000800), (0xf5900000, 0x07000000), (0xe6000000, 0),
                (0xf3000000, 0x0707f000), (0xe7000000, 0), (0xf5800800, 0),
                (0xf2000000, (63 << 14) | (7 << 2))]
    for n, (a, b) in enumerate(commands):
        struct.pack_into('>II', ram, n * 8, a, b)
    return image, ram


def test_observed_texture_uses_commands_and_unique_cartridge_bytes():
    image, ram = fixture()
    asset, = runtime_textures.regions(image, [ram])
    assert (asset['offset'], asset['size'], asset['format'], asset['width'], asset['height']) == (1024, 256, 'i4', 64, 8)
    result = runtime_textures.preview(image, asset, {})
    assert result['details']['width'] == 64
    assert len(runtime_textures.regions(image, [ram, ram])) == 1


def test_reject_ambiguous_or_incomplete_evidence():
    image, ram = fixture()
    image[1500:1756] = image[1024:1280]
    assert not runtime_textures.regions(image, [ram])
    image, ram = fixture()
    ram[2048] ^= 1
    assert not runtime_textures.regions(image, [ram])
    image, ram = fixture()
    struct.pack_into('>I', ram, 4, 0x06000800)  # segmented pointer is not a RAM address
    assert not runtime_textures.regions(image, [ram])
    image, ram = fixture()
    struct.pack_into('>I', ram, 44, 0x01000000)  # mismatched tile slot
    assert not runtime_textures.regions(image, [ram])


def test_runtime_indexed_texture_uses_the_immediately_loaded_palette():
    image = bytearray(4096)
    ram = bytearray(4096)
    palette = bytes(range(32))
    pixels = bytes((i * 29) % 256 for i in range(1024))
    image[992:1024] = b''.join(palette[i:i + 2][::-1] for i in range(0, 32, 2))
    image[1024:2048] = pixels
    ram[2016:2048] = palette
    ram[2048:3072] = pixels
    commands = [(0xe3001001, 0x8000), (0xfd100000, 0x800007e0), (0xe8000000, 0),
                (0xf5000100, 0x07000000), (0xe6000000, 0), (0xf0000000, 0x0703c000),
                (0xe7000000, 0), (0xfd500000, 0x80000800), (0xf5500000, 0x07000000),
                (0xe6000000, 0), (0xf3000000, 0x071ff200), (0xe7000000, 0),
                (0xf5400800, 0), (0xf2000000, (63 << 14) | (31 << 2))]
    for n, (a, b) in enumerate(commands):
        struct.pack_into('>II', ram, n * 8, a, b)
    asset, = runtime_textures.regions(image, [ram])
    assert (asset['format'], asset['palette_offset'], asset['palette_little_endian']) == ('ci4', 992, True)
    result = runtime_textures.preview(image, asset, {})
    assert result['details']['width'] == 64 and result['details']['height'] == 32
    expected = formats.preview(bytes(image) + palette, dict(format='ci4', width=64, height=32,
                                                            offset=1024, palette_offset=len(image)))
    assert result['data_url'] == expected['data_url']
    image[992] ^= 1
    assert not runtime_textures.regions(image, [ram])


def test_runtime_indexed_texture_keeps_separately_loaded_ia_palette():
    image, ram = bytearray(4096), bytearray(4096)
    palette = bytes(range(32))
    pixels = bytes((i * 29) % 256 for i in range(1024))
    image[100:132] = image[200:232] = palette  # repeated colours have no unique source offset
    image[1024:2048] = pixels
    ram[1800:1832] = palette
    ram[2048:3072] = pixels
    commands = [(0xe3000e02, 0xc000), (0xfd100000, 0x80000708), (0xe8000000, 0),
                (0xf5000100, 0x07000000), (0xe6000000, 0), (0xf0000000, 0x0703c000),
                (0xe7000000, 0), (0xfd500000, 0x80000800), (0xf5500000, 0x07000000),
                (0xe6000000, 0), (0xf3000000, 0x071ff200), (0xe7000000, 0),
                (0xf5400800, 0), (0xf2000000, (63 << 14) | (31 << 2))]
    for n, (a, b) in enumerate(commands):
        struct.pack_into('>II', ram, n * 8, a, b)
    asset, = runtime_textures.regions(image, [ram])
    assert asset['palette'] == palette.hex() and asset['palette_format'] == 'ia16'
    result = runtime_textures.preview(image, asset, {})
    expected = formats.preview(bytes(image)+palette, dict(format='ci4', width=64, height=32,
                               offset=1024, palette_offset=len(image), palette_format='ia16'))
    assert result['data_url'] == expected['data_url']
    struct.pack_into('>I', ram, 28, 0x06000000)  # loaded TLUT and tile must use the same tile slot
    assert not runtime_textures.regions(image, [ram])
    struct.pack_into('>I', ram, 28, 0x07000000)
    image[100] ^= 1
    image[200] ^= 1
    with pytest.raises(formats.AssetError):
        runtime_textures.preview(image, asset, {})

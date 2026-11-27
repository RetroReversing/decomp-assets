import struct

from decompassets.n64 import runtime_tiled_textures as tiled


def _fixture():
    image = bytearray(4096)
    ram = bytearray(4096)
    colors = bytes((i*31+7) % 256 for i in range(512))
    pixels = bytes((i*17+i//16) % 256 for i in range(128))
    image[512:640] = pixels
    image[256:352] = colors[:96]
    ram[0x400:0x600] = colors
    ram[0x800:0x880] = pixels
    commands = [(0xfd100000, 0x80000400), (0xe8000000, 0), (0xf5000100, 0x07000000),
                (0xe6000000, 0), (0xf0000000, 0x073fc000), (0xe7000000, 0),
                (0xba000e02, 0x8000), (0xfd48000f, 0x80000800),
                (0xf5480000, 0x07000000), (0xe6000000, 0),
                (0xf4000000, 0x0703c01c), (0xe7000000, 0),
                (0xf5480000, 0), (0xf2000000, 0x0003c01c), (0xe4000000, 0)]
    for i, pair in enumerate(commands):
        struct.pack_into('>II', ram, 0x100+8*i, *pair)
    return image, ram


def test_tiled_rows_and_runtime_palette_are_corroborated():
    image, ram = _fixture()
    assets = tiled.regions(image, [ram])
    assert len(assets) == 1
    asset = assets[0]
    assert (asset['offset'], asset['width'], asset['height']) == (512, 16, 8)
    assert asset['frames'] == asset['palettes'] == 1
    assert asset['preview_settings']['width'] == 16
    assert tiled.preview(image, asset, {})['media'] == 'image'
    ram[0x800+60] ^= 1
    assert not tiled.regions(image, [ram])


def test_unproven_palette_or_duplicate_pixels_are_rejected():
    image, ram = _fixture()
    image[256] ^= 1
    assert not tiled.regions(image, [ram])
    image, ram = _fixture()
    image[700:828] = image[512:640]
    assert not tiled.regions(image, [ram])


def test_palette_from_unrelated_image_is_rejected():
    image, ram = _fixture()
    image[256:352] = bytes(96)
    image[2048:2144] = ram[0x400:0x460]
    assert not tiled.regions(image, [ram])

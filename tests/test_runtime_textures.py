import struct

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

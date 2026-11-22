import struct

from decompassets.n64 import iwad_sprites


def test_lzss_requires_valid_backreferences_and_terminator():
    raw = bytes([12, 0x42, 0x31, 0, 0x13, 0, 0])
    assert iwad_sprites.jaguar(raw, 6) == b'B1B1B1'
    assert iwad_sprites.jaguar(raw[:-2], 6) is None
    assert iwad_sprites.jaguar(bytes([1, 0xff, 0x10]), 6) is None


def test_iwad_sprite_directory_and_preview():
    sprite = bytearray(struct.pack('>8h', 1, 0, 16, 0, 0, 16, 2, 2))
    sprite.extend(bytes([0x12] * 16))
    sprite.extend(bytes.fromhex('ffff') * 16)
    directory = 12 + len(sprite)
    image = bytearray(struct.pack('<4sII', b'IWAD', 8, directory))
    image.extend(sprite)
    for offset, size, name in [(12, 0, b'S_START'), (12, len(sprite), b'ITEMA0'),
                               (directory, 0, b'S_END'), (directory, 0, b'T_START'),
                               (directory, 0, b'T_END'), (directory, 0, b'EXTRA1'),
                               (directory, 0, b'EXTRA2'), (directory, 0, b'EXTRA3')]:
        image.extend(struct.pack('<II8s', offset, size, name))
    [asset] = iwad_sprites.regions(image)
    result = iwad_sprites.preview(image, asset, {})
    assert result['media'] == 'image'
    assert (result['details']['width'], result['details']['height']) == (16, 2)
    struct.pack_into('<I', image, directory + 16, directory + 1)
    assert not iwad_sprites.regions(image)


def test_adaptive_huffman_reference_vector_and_truncation():
    from decompassets.n64.iwad_huffman import unpack

    # Encoded from a synthetic sentence with the public reference encoder.
    packed = bytes.fromhex('6e92a19d0954b4454eac9774dc2e2bd1dddc14ff0a2f2c73576179f7ab0c0000')
    plain = b'hello hello hello adaptive huffman test\0'
    assert unpack(packed, len(plain)) == plain
    assert unpack(packed[:-4], len(plain)) is None
    assert unpack(packed, len(plain)-1) is None


def test_iwad_texture_header_and_swizzled_rows():
    data = struct.pack('>4H', 1, 1, 4, 1) + bytes(range(16)) + bytes(32)
    pixels, palette, width, height, count = iwad_sprites._texture(data)
    assert (width, height, count, len(palette)) == (16, 2, 1, 32)
    assert pixels == bytes(range(8)) + bytes(range(12, 16)) + bytes(range(8, 12))
    assert iwad_sprites._texture(data[:-1]) is None

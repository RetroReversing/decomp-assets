import struct

from decompassets.n64 import compact_mio_textures as textures


def _packed(data):
    masks = bytes([255]) * ((len(data)+7)//8)
    out = struct.pack('>4H', 0, len(data), 8+len(masks), 8+len(masks)) + masks + data
    return out + bytes(-len(out) % 16)


def _image():
    pixels = b'\xff\xff' * 16
    commands = [(0xfd100000, 0x01000000), (0xf5100000, 0x07000000),
                (0xf5100000, 0), (0xf2000000, (12 << 12) | 12),
                (0xdf000000, 0), (0, 0)]
    data = pixels + bytes(48) + b''.join(struct.pack('>II', *x) for x in commands)
    packed = _packed(data)
    image = bytearray(0x3000)
    for n in range(8):
        start = 0x1800 + n*len(packed)
        image[start:start+len(packed)] = packed
        struct.pack_into('>3I', image, 0x1000+n*12, start, start+len(packed), len(data))
    return image, data


def test_checked_directory_previews_texture():
    image, _ = _image()
    regions = textures.regions(image)
    assert len(regions) == 1
    assert regions[0]['texture_count'] == 8
    assert regions[0]['textures'][0]['preview_settings']['width'] == 4
    item = regions[0]['textures'][0]
    assert item['frames'] == 1 and item['levels'][0]['height'] == 4
    result = textures.preview(image, regions[0], {'texture': 0})
    assert result['media'] == 'image'


def test_rejects_invalid_reference_and_bad_display_list():
    image, data = _image()
    image[0x1808] = 0
    assert textures.unpack(image, 0x1800, 0x1800+len(_packed(data)), len(data)) is None
    assert textures.texture(data[:-16] + bytes(16)) is None


def test_f3d_terminator_and_intensity_pixels():
    pixels = bytes(range(16))
    commands = [(0xfd900000, 0x01000000), (0xf5880800, 0),
                (0xf2000000, (12 << 12) | 12), (0xb8000000, 0), (0, 0)]
    data = pixels + bytes(48) + b''.join(struct.pack('>II', *x) for x in commands)
    assert textures.texture(data) == dict(format='i8', width=4, height=4, offset=0)
    assert textures.texture(data[:-16] + bytes(16)) is None


def test_f3d_ci4_palette_and_pixels():
    commands = [(0xfd100000, 0x01000000), (0xfd500000, 0x01000020),
                (0xf5400800, 0), (0xf2000000, (12 << 12) | 12), (0xb8000000, 0)]
    data = bytes(32 + 8 + 48) + b''.join(struct.pack('>II', *x) for x in commands)
    assert textures.texture(data) == dict(format='ci4', width=4, height=4, offset=32,
                                          palette_offset=0, palette_format='rgba5551-be')

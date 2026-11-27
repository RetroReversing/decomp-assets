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
    assert regions[0]['textures'][0]['settings']['width'] == 4
    result = textures.preview(image, regions[0], {'texture': 0})
    assert result['media'] == 'image'


def test_rejects_invalid_reference_and_bad_display_list():
    image, data = _image()
    image[0x1808] = 0
    assert textures.unpack(image, 0x1800, 0x1800+len(_packed(data)), len(data)) is None
    assert textures.texture(data[:-16] + bytes(16)) is None

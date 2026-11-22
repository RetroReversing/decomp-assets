import struct
import zlib

from decompassets.n64 import deflate_sprites


def _rom():
    # Two equal-sized indexed frames share the first frame's palette.
    data = bytearray(0x98)
    struct.pack_into('>2I', data, 0, 0x88, 0x98)
    struct.pack_into('>2I4H', data, 8, 0x18, 0x38, 8, 4, 4, 1)
    data[0x18:0x38] = b'\xff\xff' * 16
    struct.pack_into('>2I4H', data, 0x48, 0, 0x58, 8, 4, 4, 1)
    struct.pack_into('>4I', data, 0x88, 8, 16, 0x48, 0x50)
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(data) + compressor.flush()
    end = (0x100 + len(packed) + 15) & ~15
    image = bytearray(end)
    struct.pack_into('>2I', image, 0x20, 0x100, end)
    image[0x100:0x100 + len(packed)] = packed
    return bytes(image)


def test_shared_palette_frames():
    image = _rom()
    assets = deflate_sprites.regions(image)
    assert len(assets) == 1
    assert assets[0]['frames'] == 2
    preview = deflate_sprites.preview(image, assets[0], {'frame': 1})
    assert preview['details']['format'] == 'ci4'
    assert preview['data_url'].startswith('data:image/png;base64,')


def test_rejects_bad_table_and_dimensions():
    assert not deflate_sprites._images(bytes(64))
    data = bytearray(48)
    struct.pack_into('>2I', data, 0, 16, 24)
    struct.pack_into('>2I', data, 16, 9999, 9999)
    assert not deflate_sprites._images(data)

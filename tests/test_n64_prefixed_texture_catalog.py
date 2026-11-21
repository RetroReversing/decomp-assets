import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import prefixed_texture_catalog as catalog


def _pack():
    end = 0x2b0
    data = bytearray(end)
    struct.pack_into('>6I', data, 0, 1, 24, 1, end, 0, end)
    struct.pack_into('>II', data, 24, 0x04000100, 32)
    commands = [(0xe7000000, 0), (0xe3001001, 0x8000), (0xfd100000, 0x90),
                (0xf5000100, 0x06000000), (0xf0000000, 0x0603c000),
                (0xf5500000, 0x07018060), (0xe6000000, 0), (0xfd500000, 0xb0),
                (0xf3000000, 0x071ff000), (0xf5400400, 0x00018060),
                (0xf2000000, 0x0007c07c), (0xe6000000, 0), (0xdf000000, 0)]
    for i, pair in enumerate(commands):
        struct.pack_into('>II', data, 32 + 8*i, *pair)
    data[0x90:0xb0] = b'\xff\xff' * 16
    data[0xb0:0x2b0] = b'\x11' * 512
    compressor = zlib.compressobj(wbits=-15)
    return struct.pack('>I', len(data)) + compressor.compress(data) + compressor.flush()


def _image():
    data = bytearray(0x10000)
    for i in range(8):
        start = len(data)
        data.extend(_pack())
        data.extend(b'\xa5' * ((-len(data)) % 16))
        struct.pack_into('>III', data, i*12, start, len(data), 1)
    return bytes(data)


def test_directory_textures_and_preview():
    image = _image()
    assets = catalog.regions(image)
    assert len(assets) == 8
    assert assets[0]['texture_count'] == 1
    result = catalog.preview(image, assets[0], {})
    assert result['mime'] == 'image/png'
    assert result['details']['width'] == result['details']['height'] == 32
    with pytest.raises(AssetError):
        catalog.preview(image[:-1], assets[-1], {})


def test_directory_rejects_broken_members_and_relative_pointers():
    image = bytearray(_image())
    image[0x10000] = 0xff
    assert not catalog.regions(image)
    raw = bytearray(zlib.decompress(_pack()[4:], -15))
    struct.pack_into('>I', raw, 32 + 7*8 + 4, len(raw) + 1)
    assert not catalog.textures(raw)

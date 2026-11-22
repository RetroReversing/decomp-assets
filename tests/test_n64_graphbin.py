import struct
import zlib

import pytest

from decompassets import formats
from decompassets.n64 import graphbin


def _pack(bits=8):
    header = b'GraphBin' + struct.pack('>4H', 8, 4, 1, bits << 8)
    palette = b'\xff\xff' * 256
    pixels = bytes(8 * 4 * bits // 8)
    return header + palette + pixels


def _rom(data):
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(data) + compressor.flush()
    end = (0x100 + len(packed) + 15) & ~15
    image = bytearray(end)
    struct.pack_into('>2I', image, 0x20, 0x100, end)
    image[0x100:0x100 + len(packed)] = packed
    return bytes(image)


def test_bounded_images_and_frame_selection():
    image = _rom(_pack(8) + _pack(16))
    assets = graphbin.regions(image)
    assert len(assets) == 1
    assert assets[0]['frames'] == 2
    preview = graphbin.preview(image, assets[0], {'frame': 1})
    assert preview['details']['format'] == 'rgba5551-be'
    assert preview['details']['width'] == 8
    assert preview['data_url'].startswith('data:image/png;base64,')
    with pytest.raises(formats.AssetError):
        graphbin.preview(image, assets[0], {'frame': 2})


def test_rejects_invalid_or_unbounded_resources():
    assert not graphbin.regions(_rom(_pack()[:-10]))
    assert not graphbin.regions(_rom(b'not an image'))
    image = bytearray(_rom(_pack()))
    struct.pack_into('>I', image, 0x24, len(image) - 16)
    assert not graphbin.regions(bytes(image))

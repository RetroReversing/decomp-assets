"""Only complete RGBA members whose headers agree with the payload are textures."""

import base64
import struct
import zlib

import pytest

from decompassets.n64 import preview, zlib_textures


@pytest.mark.parametrize('depth', [16, 32])
def test_zlib_texture_uses_the_exact_visible_dimensions_and_crc(depth):
    header = struct.pack('>4I', 12, 8, depth, 11)
    rgba = b'\xf8\x01' if depth == 16 else b'\xff\x00\x00\xff'
    compressed = zlib.compress(header + rgba * (12*8))
    image = b'file' + compressed + b'tail'
    asset, = zlib_textures.regions(image)
    assert asset['size'] == len(compressed)
    assert asset['visible_width'] == 11
    result = preview(image, asset, {})
    png = base64.b64decode(result['data_url'].split(',')[1])
    assert struct.unpack_from('>2I', png, 16) == (12, 8)
    assert zlib_textures.regions(image[:4+len(compressed)-1]) == []
    assert zlib_textures.regions(zlib.compress(header + rgba)) == []

import base64
import struct
import zlib

import pytest

from decompassets import formats
from decompassets.n64 import chunked_package_images as images


def _literal_chunk(data):
    assert len(data) % 8 == 0
    result = b''.join(b'\x00' + data[i:i + 8] for i in range(0, len(data), 8)) + b'\x03\x00\x00'
    return result + b'\xff' * (-len(result) % 4)


def _image():
    header = b'PKG\x00' + struct.pack('<I', 0x210) + struct.pack('>II4BI', 1, 32, 1, 2, 1, 0, 16)
    pixels = bytes(range(16))
    palette = b''.join(struct.pack('>H', ((i % 32) << 11) | 1) for i in range(256))
    return header + pixels + palette


def test_multichunk_package_is_bounded_and_preview_reverses_scanlines():
    data = _image()
    image = bytes(16) + _literal_chunk(data[:40]) + _literal_chunk(data[40:])
    found = images.regions(image)
    assert len(found) == 1 and found[0]['width'] == 8 and found[0]['height'] == 2
    preview = images.preview(image, found[0], {})
    png = base64.b64decode(preview['data_url'].split(',')[1])
    pos = png.index(b'IDAT')
    length = int.from_bytes(png[pos-4:pos], 'big')
    row = zlib.decompress(png[pos+4:pos+4+length])
    assert row[0] == 0 and row[1] == 8 * 255 // 31 and row[34] == 0
    with pytest.raises(formats.AssetError):
        images.preview(image[:-8], found[0], {})


def test_rejects_bad_backreferences_and_invalid_headers():
    assert images._chunk(b'\x01\x00') is None
    data = bytearray(_image())
    data[18] = 2
    assert not images.regions(bytes(16) + _literal_chunk(data[:40]) + _literal_chunk(data[40:]))
    assert not images.regions(bytes(16) + _literal_chunk(_image()[:40]))

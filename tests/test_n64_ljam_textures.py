import base64
import struct
import zlib

import pytest

from decompassets import formats
from decompassets.n64 import ljam_textures


def _archive():
    data = bytearray(256)
    data[:8] = b'LJAM'+struct.pack('<I', 0)
    struct.pack_into('<I', data, 8, 1)
    data[12:24] = b'IMAGES\0'.ljust(12, b'\0')
    struct.pack_into('<I', data, 24, 32)
    struct.pack_into('<I', data, 32, 1)
    data[36:48] = b'ICON.TGA\0'.ljust(12, b'\0')
    struct.pack_into('<II', data, 48, 128, 34)
    struct.pack_into('<I', data, 56, 0)
    header = bytes.fromhex('000002000000000000000000020002002008')
    # TGA rows are bottom first and pixels are BGRA.
    pixels = bytes.fromhex('ff0000ff 00ff00ff 0000ffff ffffffff')
    data[128:162] = header+pixels
    return bytes(data)


def test_archive_true_colour_texture_and_orientation():
    image = _archive()
    asset, = ljam_textures.regions(image)
    preview = ljam_textures.preview(image, asset, {})
    assert preview['details']['width'] == preview['details']['height'] == 2
    png = base64.b64decode(preview['data_url'].split(',')[1])
    at = png.index(b'IDAT');size = int.from_bytes(png[at-4:at], 'big')
    rows = zlib.decompress(png[at+4:at+4+size])
    assert rows[:9] == bytes.fromhex('00 ff0000ff ffffffff')
    with pytest.raises(formats.AssetError):
        ljam_textures.preview(image[:-100], asset, {})


def test_directory_rejects_cycles_and_out_of_bounds_files():
    image = bytearray(_archive())
    struct.pack_into('<I', image, 56, 1)
    image[60:72] = b'LOOP\0'.ljust(12,b'\0')
    struct.pack_into('<I', image, 72, 32)
    assert not ljam_textures.regions(image)
    image = bytearray(_archive())
    struct.pack_into('<I', image, 48, len(image)-4)
    assert not ljam_textures.regions(image)

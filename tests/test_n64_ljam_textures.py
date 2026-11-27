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


def test_packed_bitmap_framed_lz_and_palette():
    # Two indexed pixels followed by a back-reference; one block, stream order.
    header = struct.pack('<BBHH', 8, 1, 4, 1)
    palette = bytes.fromhex('0000ff 00ff00')
    block = bytes.fromhex('00 60 01 0f02 0000')
    image = header+palette+struct.pack('<HH', 4, len(block))+block
    # The compressed form must be smaller than its expanded block.
    assert ljam_textures._bmp(image, 0, len(image)) is None
    # Raw block: two red, two green pixels.
    image = header+palette+struct.pack('<HH', 4, 4)+bytes.fromhex('00000101')
    width, height, rgba = ljam_textures._bmp(image, 0, len(image))
    assert (width, height) == (4, 1)
    assert rgba == bytes.fromhex('ff0000ff ff0000ff 00ff00ff 00ff00ff')
    assert ljam_textures._bmp(image[:-1], 0, len(image)-1) is None
    assert ljam_textures._bmp(bytes([0x88])+image[1:], 0, len(image)) is None
    # A literal and an overlapping reference expand to 20 palette indices.
    header = struct.pack('<BBHH', 8, 0, 20, 1)
    block = bytes.fromhex('00 c0 0001 01 0000')
    image = header+palette[:3]+struct.pack('<HH', 20, len(block))+block
    assert ljam_textures._bmp(image, 0, len(image))[2] == bytes.fromhex('ff0000ff')*20
    malformed = header+palette[:3]+struct.pack('<HH', 20, len(block))+bytes.fromhex('00 c0 0002 01 0000')
    assert ljam_textures._bmp(malformed, 0, len(malformed)) is None

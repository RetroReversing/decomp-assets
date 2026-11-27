import base64
import struct
import zlib

from decompassets import n64
from decompassets.n64 import zlib_indexed_images


def fixture():
    palette = bytes([255, 0, 0, 255, 0, 255, 0, 255]) + bytes(254*4)
    data = struct.pack('>IIHHI', 0x80000001, 0, 2, 2, 0) + palette + bytes([0, 1, 1, 0])
    return b'\0'*16 + zlib.compress(data)


def test_indexed_image_is_found_and_palette_is_rendered():
    image = fixture()
    asset = next(a for a in n64.regions(image) if a.get('layout') == zlib_indexed_images.LAYOUT)
    preview = n64.preview(image, asset, {})
    png = base64.b64decode(preview['data_url'].split(',', 1)[1])
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    pos, compressed = 8, bytearray()
    while pos < len(png):
        size = int.from_bytes(png[pos:pos+4], 'big')
        kind = png[pos+4:pos+8]
        if kind == b'IDAT':
            compressed.extend(png[pos+8:pos+8+size])
        pos += 12 + size
    pixels = zlib.decompress(compressed)
    assert pixels[:9] == bytes([0, 255, 0, 0, 255, 0, 255, 0, 255])
    assert asset['preview_settings']['width'] == 2
    assert preview['details']['width'] == 2


def test_bad_checksum_or_unexpected_extra_data_is_not_an_image():
    image = fixture()
    assert zlib_indexed_images.image_at(image[:-1], 16) is None
    data = zlib.decompress(image[16:]) + b'\0'
    assert zlib_indexed_images.image_at(b'\0'*16 + zlib.compress(data), 16) is None


def test_four_bit_palette_image():
    palette = bytes([255, 0, 0, 255, 0, 255, 0, 255]) + bytes(14*4)
    data = struct.pack('>IIHHI', 0x80000000, 0, 2, 2, 0) + palette + bytes([0x01, 0x10])
    image = bytes(16) + zlib.compress(data)
    asset = next(a for a in n64.regions(image) if a.get('layout') == zlib_indexed_images.LAYOUT)
    assert asset['palette_entries'] == [16]
    assert asset['preview_settings']['format'] == 'ci4'
    assert n64.preview(image, asset, {})['media'] == 'image'

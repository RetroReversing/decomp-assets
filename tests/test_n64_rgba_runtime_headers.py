import base64
import struct
import zlib

from decompassets.n64 import rgba_runtime_headers as images


def fixture():
    header = struct.pack('>4H6I', 4, 4, 0x201, 16, 0, 0x80400000, 4 << 16, 0, 0, 0)
    return bytes(16) + header + bytes.fromhex('f801')*16


def test_header_image_previews_the_bounded_pixels():
    data = fixture()
    asset = images.regions(data)[0]
    result = images.preview(data, asset, {})
    png = base64.b64decode(result['data_url'].split(',', 1)[1])
    at, chunks = 8, bytearray()
    while at < len(png):
        size = int.from_bytes(png[at:at+4], 'big')
        if png[at+4:at+8] == b'IDAT':
            chunks.extend(png[at+8:at+8+size])
        at += 12+size
    assert zlib.decompress(chunks)[1:5] == bytes((255, 0, 0, 255))
    assert (asset['width'], asset['height']) == (4, 4)


def test_invalid_size_address_and_truncation_are_rejected():
    data = fixture()
    assert images.image_at(data[:-1], 16) is None
    invalid = bytearray(data)
    struct.pack_into('>I', invalid, 16+12, 0x12345678)
    assert images.image_at(invalid, 16) is None
    invalid = bytearray(data)
    struct.pack_into('>H', invalid, 16+6, 15)
    assert images.image_at(invalid, 16) is None

"""Stage texture previews validate the run stream and crop padded rows."""

import base64
import struct
import zlib

from decompassets.n64 import preview, stage_banks


def _bank():
    data = bytes.fromhex('0001 f801') + bytes(28)
    data += b'\x10' + bytes(7) + b'\x01' + bytes(7)
    stream = bytes([len(data) - 1]) + data + b'\xff'
    start = 92
    size = start + 12 + len(stream)
    image = bytearray(size)
    struct.pack_into('>6I', image, 0, 0x010a0000, 1, size, 512, 1, 72)
    struct.pack_into('>B3xHH4xII', image, 72, 0, 2, 2, start, 0)
    struct.pack_into('>BBHII', image, start, 16, 0, 12, 12 + len(stream), len(data))
    image[start + 12:] = stream
    return image


def test_ci4_stage_texture_uses_hardware_row_stride():
    image = _bank()
    asset, = stage_banks.regions(image)
    result = preview(image, asset, {'texture': 0})
    assert result['details']['width'] == 2
    png = base64.b64decode(result['data_url'].split(',')[1])
    size = struct.unpack_from('>I', png, 33)[0]
    assert png[37:41] == b'IDAT'
    red, black = bytes.fromhex('ff0000ff'), bytes.fromhex('000000ff')
    assert zlib.decompress(png[41:41 + size]) == b'\0' + red + black + b'\0' + black + red


def test_stage_texture_rejects_wrong_decoded_extent():
    image = _bank()
    image[103] -= 1
    assert not stage_banks.regions(image)


def test_nibble_runs_are_low_nibble_first_and_bounded():
    data = bytes.fromhex('01 21 81 f3 0f')
    assert stage_banks._unpack(data, 2, 4) == b'\x21\x33'
    assert stage_banks._unpack(data, 1, 4) is None
    assert stage_banks._unpack(data[:-1], 2, 4) is None

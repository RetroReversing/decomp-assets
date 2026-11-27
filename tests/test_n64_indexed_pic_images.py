import struct

import pytest

from decompassets import formats
from decompassets.n64 import indexed_pic_images as pic


def fixture():
    # Two explicit opaque colors, then a run ending beyond the image.
    bitstring = '000' + format(0x7c00, '015b') + '0' + '000' + format(0x001f, '015b') + '0' + '00'
    bitstring += '0' * (-len(bitstring) % 8)
    payload = int(bitstring, 2).to_bytes(len(bitstring)//8, 'big')
    return b'PIC\x1a\0\0\0' + struct.pack('>3H', 15, 2, 1) + payload


def test_direct_pic_colors_and_truncated_stream():
    data = fixture()
    record = pic.header(data, 0)
    assert (record['width'], record['height']) == (2, 1)
    pixels = pic.decode(data, record)
    assert len(pixels) == 4 and pixels[0:2] != pixels[2:4]
    assert all(pixels[i] & 1 for i in (1, 3))
    with pytest.raises(formats.AssetError):
        pic.decode(data[:record['payload']+1], record)


def test_header_rejects_unbounded_and_external_palette():
    data = fixture()
    assert pic.header(data[:8], 0) is None
    assert pic.header(data.replace(b'\0\0\x0f', b'\x40\0\x08'), 0) is None

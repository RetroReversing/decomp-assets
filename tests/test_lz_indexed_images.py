"""Bounded output-sized LZSS streams carrying complete indexed images."""

import struct

import pytest

from decompassets import formats, n64
from decompassets.n64 import lz_indexed_images


def packed_image():
    raw = bytearray(0x90)
    struct.pack_into('>8I', raw, 0, 0x10, 0x10000, 0x10, 0x40, 32, 0, 0, 0xffffffff)
    for i in range(16):
        struct.pack_into('>H', raw, 0x20+2*i, i * 0x801 | 1)
    struct.pack_into('>6HI', raw, 0x40, 0, 0, 0, 0, 4, 8, 0xffffffff)
    raw[0x50:] = bytes(range(64))
    # The first token reads three zero bytes from the initialized ring; the
    # remaining bytes are literals. This is also the recognizer's prefix.
    stream = bytearray(struct.pack('>I', len(raw)) + b'\xfe\xed\xf0' + raw[3:10])
    for at in range(10, len(raw), 8):
        stream += b'\xff' + raw[at:at+8]
    return bytes(raw), bytes(stream)


def test_detect_and_preview_bounded_indexed_image():
    raw, packed = packed_image()
    assert lz_indexed_images.unpack(packed) == (raw, len(packed))
    image = bytes(64) + packed
    assets = lz_indexed_images.regions(image)
    assert len(assets) == 1
    asset = assets[0]
    assert (asset['width'], asset['height'], asset['palettes'], asset['size']) == (16, 8, 1, len(packed))
    preview = lz_indexed_images.preview(image, asset, {})
    assert preview['data_url'].startswith('data:image/png;base64,')
    assert n64.preview(image, asset, {})['data_url'] == preview['data_url']
    with pytest.raises(formats.AssetError):
        lz_indexed_images.preview(image, asset, {'palette': 1})


def test_reject_truncated_stream_and_invalid_section_extent():
    raw, packed = packed_image()
    assert lz_indexed_images.unpack(packed[:-1]) is None
    bad = bytearray(raw)
    struct.pack_into('>H', bad, 0x40+10, 7)
    assert lz_indexed_images.record(bad) is None
    assert lz_indexed_images.unpack(b'\xff\xff\xff\xff\x00') is None

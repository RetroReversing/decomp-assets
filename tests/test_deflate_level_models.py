import struct
import zlib

import pytest

from decompassets import formats
from decompassets.n64 import deflate_level_models as models


def decoded():
    data = bytearray(0x100)
    struct.pack_into('>II', data, 0, 0x30, 0x38)
    struct.pack_into('>HH', data, 0x18, 1, 1)
    struct.pack_into('>4I', data, 0x38, 0x98, 0xb6, 0, 0x78)
    struct.pack_into('>3H', data, 0x58, 3, 1, 1)
    struct.pack_into('>2H', data, 0x78 + 6, 0, 0)
    struct.pack_into('>2H', data, 0x88 + 6, 3, 1)
    for i, point in enumerate(((0, 0, 0), (3, 0, 0), (0, 4, 1))):
        struct.pack_into('>3h', data, 0x98 + i * 10, *point)
    data[0xb7:0xba] = b'\x00\x01\x02'
    return data


def wrapped(data):
    compressor = zlib.compressobj(wbits=-15)
    return len(data).to_bytes(4, 'little') + b'\x09' + compressor.compress(data) + compressor.flush()


def test_level_segments_and_preview():
    data = decoded()
    image = bytes(16) + wrapped(data) + bytes(32)
    asset, = models.regions(image)
    assert (asset['offset'], asset['nodes'], asset['vertices'], asset['triangles']) == (16, 1, 3, 1)
    result = models.preview(image, asset, {})
    assert result['vertices'] == [(0, 0, 0), (3, 0, 0), (0, 4, 1)]
    assert result['surfaces'][0]['indices'] == (0, 1, 2)


def test_rejects_bad_triangle_and_stale_stream():
    data = decoded()
    data[0xb9] = 3
    assert models.geometry(data) is None
    image = bytes(16) + wrapped(decoded())
    asset, = models.regions(image)
    with pytest.raises(formats.AssetError):
        models.preview(image[:-1], asset, {})


def test_requires_valid_segment_and_batch_extents():
    data = decoded()
    struct.pack_into('>H', data, 0x8e, 4)
    assert models.geometry(data) is None
    data = decoded()
    struct.pack_into('>I', data, 0x38, len(data) - 1)
    assert models.geometry(data) is None

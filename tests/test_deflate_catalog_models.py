"""Synthetic packed model tables with a partially replaced vertex cache."""

import struct
import zlib

from decompassets.n64 import deflate_catalog_models, preview

from .test_deflate_catalog import _image


def _model():
    data = bytearray(232)
    struct.pack_into('>2I10H', data, 0, len(data), 1, 28, 1, 36, 1, 68, 2, 92, 2, 152, 5)
    struct.pack_into('>8H', data, 68, 0, 0, 3, 0, 1, 3, 2, 2)
    struct.pack_into('>3H', data, 92, 0, 1, 2)
    struct.pack_into('>3H', data, 112, 1, 2, 3)
    for i, pos in enumerate(((0, 0, 0), (4, 0, 0), (0, 4, 0), (4, 4, 0), (4, 8, 0))):
        struct.pack_into('>3h', data, 152 + i * 16, *pos)
    return data


def test_catalog_model_preserves_unreplaced_vertex_slots():
    data = _model()
    packed = zlib.compress(data)
    image = _image() + struct.pack('>2I', len(data), len(packed)) + packed
    asset, = deflate_catalog_models.regions(image)
    result = preview(image, asset, {})
    assert [face['indices'] for face in result['surfaces']] == [(0, 1, 2), (1, 3, 4)]
    assert result['vertices'][4] == (4, 8, 0)

    invalid_header = bytearray(data)
    struct.pack_into('>H', invalid_header, 24, 148)
    assert deflate_catalog_models.geometry(invalid_header) is None
    struct.pack_into('>H', data, 112, 4)
    assert deflate_catalog_models.geometry(data) is None

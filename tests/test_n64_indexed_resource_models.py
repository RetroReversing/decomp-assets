import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import indexed_resource_models as models


def _model():
    data = bytearray(50)
    struct.pack_into('>BBH', data, 0, 2, 2, 2)
    for i, point in enumerate(((0, 0, 0), (10, 0, 0), (0, 10, 0))):
        struct.pack_into('>3h', data, 8 + i*6, *point)
    data[38:44] = b'\x01\x04\x12\x34\x56\x78'
    data[44:50] = bytes((0, 1, 2, 0, 1, 2))
    return bytes(data)


def test_grouped_model_geometry_and_preview():
    data = _model()
    vertices, faces = models.geometry(data)
    assert vertices == [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    assert faces == [(0, 1, 2)]
    item = dict(offset=0, size=len(data), vertices=3, triangles=1, label='Model')
    asset = dict(meshes=[item], preview_settings={'format': 'auto'})
    out = models.preview(data, asset, {})
    assert out['triangles'] == 1 and out['surfaces'][0]['indices'] == (0, 1, 2)
    with pytest.raises(AssetError):
        models.preview(data[:-1], asset, {})


def test_invalid_group_counts_and_triangle_indices():
    data = bytearray(_model())
    data[38] = 2
    assert models.geometry(data) is None
    data = bytearray(_model())
    data[44] = 3
    assert models.geometry(data) is None

import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import uso_models


def _section(kind, data):
    return struct.pack('>3I', kind, len(data), 0) + data


def test_polygon_model_resolves_relocated_remap_and_validates_indices():
    vertices = struct.pack('>9h', 0, 0, 0, 10, 0, 0, 0, 10, 0)
    remap = struct.pack('>12H', 0, 0, 0, 1, 0, 0, 2, 0, 0, 0, 0, 0)
    face = struct.pack('>4H', 0, 3, 1, 2)
    shape = b''.join(struct.pack('>HH2I', 2, cmd, count, 0) for cmd, count in ((27, 3), (32, 4), (28, 1)))
    data = vertices + remap + face + shape + struct.pack('>HH', 0, 2)
    symbols = b''.join(struct.pack('>3I', 0, offset, 0) for offset in (0, len(vertices), len(vertices+remap)))
    start = len(vertices+remap+face)
    relocs = b''.join(struct.pack('>3I', i*16+4, start+8+i*12, 1) for i in range(3))
    header = struct.pack('>3I20s8xI', 0x12345678, 1, 1, b'model.uso', 0x12345678)
    image = header + _section(6, data) + _section(1, symbols) + _section(3, relocs) + _section(11, b'')
    asset, = uso_models.regions(image)
    preview = n64.preview(image, asset, {})
    assert preview['vertices'] == [(0,0,0), (10,0,0), (0,10,0)]
    assert preview['surfaces'][0]['indices'] == (0,1,2)
    damaged = bytearray(image)
    struct.pack_into('>H', damaged, len(header)+12+len(vertices+remap)+2, 4)
    assert not uso_models.regions(damaged)
    with pytest.raises(AssetError, match='geometry changed'):
        n64.preview(damaged, asset, {})

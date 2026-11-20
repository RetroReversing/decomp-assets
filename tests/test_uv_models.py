import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import uv_models


def _fixture(*, load=0x20, triangle=0x4012, triangle_count=1):
    vertices = b''.join(struct.pack('>3hH2h4B', x, y, 0, 0, 0, 0, 100, 150, 200, 255)
                        for x, y in ((0, 0), (8, 0), (0, 8)))
    header = struct.pack('>HBBB', 3, 1, 1, 0)
    part = b'\x01\x00'+struct.pack('>4B6f', 1, 0, 0, 0, *([0]*6))
    material = struct.pack('>4H12xH', 0, 0xfff, 3, triangle_count, 2)
    commands = struct.pack('>HBH', 0, load, triangle)
    common = header+vertices+part+material+commands+bytes(4+64)
    body = b'UVMD'+b'COMM'+struct.pack('>I', len(common))+common
    return b'FORM'+struct.pack('>I', len(body))+body


def test_uvmd_local_mesh_uses_cached_indices():
    image = _fixture()
    asset, = uv_models.regions(image)
    result = n64.preview(image, asset, {})
    assert result['vertices'] == [(0, 0, 0), (8, 0, 0), (0, 8, 0)]
    assert result['surfaces'][0]['indices'] == (0, 1, 2)
    assert result['triangles'] == 1
    with pytest.raises(AssetError, match='Rescan'):
        n64.preview(image[:-1], asset, {})


@pytest.mark.parametrize('kwargs', [dict(load=0x30), dict(triangle=0x4013), dict(triangle_count=2)])
def test_uvmd_rejects_inconsistent_geometry(kwargs):
    assert uv_models.regions(_fixture(**kwargs)) == []

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


def _local_fixture(*, triangle=0x8022, first=0, extra_header=False):
    positions = ((0, 0, 0), (9, 0, 0), (0, 9, 0))
    vertices = b''.join(struct.pack('>3hH2h4B', *position, 0, 0, 0, 255, 255, 255, 255)
                        for position in positions)
    common = struct.pack('>4B3H3f', 2, 1, 0x80 if extra_header else 0, 0, 3, 1, 2, 1, 1, 1)
    if extra_header:
        common += bytes(47)
    empty = struct.pack('>BBf', 0, 0, 1)
    level = struct.pack('>BBf', 1, 0, 2)
    part = struct.pack('>3B6f3B', 0, 0, 0, *([0]*6), 0, 0, 1)
    material = struct.pack('>4I6H', 0, 0, 0, 0, 3, 1, 0, 0, 2, 0)
    commands = struct.pack('>HBH', first, 0x40, triangle)
    common += empty + level + part + material + vertices + commands + bytes(64)
    body = b'UVMD' + b'COMM' + struct.pack('>I', len(common)) + common
    return bytes(2) + b'FORM' + struct.pack('>I', len(body)) + body


@pytest.mark.parametrize('extra_header', [False, True])
def test_uvmd_local_material_draws_first_nonempty_lod(extra_header):
    image = _local_fixture(extra_header=extra_header)
    asset, = uv_models.regions(image)
    result = n64.preview(image, asset, {})
    assert result['vertices'] == [(0, 0, 0), (9, 0, 0), (0, 9, 0)]
    assert result['surfaces'][0]['indices'] == (0, 1, 2)


@pytest.mark.parametrize('kwargs', [dict(first=1), dict(triangle=0x8023)])
def test_uvmd_local_material_rejects_unloaded_vertices(kwargs):
    assert uv_models.regions(_local_fixture(**kwargs)) == []


def _paired_fixture(*, bad_index=False):
    vertices = b''.join(struct.pack('>3hH2h4B', i, i*2, i*3, 0, 0, 0, 255, 255, 255, 255)
                        for i in range(24))
    common = struct.pack('>4B3H3f', 1, 1, 3, 0, 24, 1, 2, 1, 1, 1)
    level = struct.pack('>BBf', 1, 0, 1)
    part = struct.pack('>3B6f3B', 0, 0, 0, *([0]*6), 0, 0, 1)
    material = struct.pack('>4I4H', 0, 0, 0, 0, 24, 2, 24, 2)
    last = 24 if bad_index else 23
    pair = 0x40000000 | (1 << 20) | (last << 15) | (last << 5) | 3
    commands = struct.pack('>HBI', 0x2000, 0xe0, pair)
    common += level + part + material + vertices + commands + bytes(64)
    body = b'UVMD' + b'COMM' + struct.pack('>I', len(common)) + common
    return b'FORM' + struct.pack('>I', len(body)) + body


def test_uvmd_paired_triangles_and_large_vertex_load():
    image = _paired_fixture()
    asset, = uv_models.regions(image)
    result = n64.preview(image, asset, {})
    assert result['triangles'] == 2
    assert [s['indices'] for s in result['surfaces']] == [(0, 1, 23), (0, 23, 3)]


def test_uvmd_paired_triangles_reject_unloaded_vertex():
    assert not uv_models.regions(_paired_fixture(bad_index=True))

"""Synthetic packed display lists exercise the catalog and model preview."""

import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import models, packed_models

from .test_native_textures import indexed_set, literal2

POINTS = [(-12, 4, 5), (60, -45, 7), (2, 80, -20)]
TRIANGLE = struct.pack('>H', 0x8000 | 1 << 5 | 2)


def model(commands=b'\x20\x03'+TRIANGLE+b'\0', *, material=bytes(24)):
    rows = [struct.pack('>hhh10x', *point) for point in POINTS]
    planes = bytes(row[column] for column in range(16) for row in rows)
    vertices = struct.pack('>II', 16, len(rows))+planes
    part = indexed_set([material, commands.ljust(8, b'\0')])
    lods = indexed_set([indexed_set([part])])
    return indexed_set([indexed_set([vertices]), indexed_set([]), lods])


def test_packed_display_list_is_detected_and_previewed_through_n64():
    raw = model()
    block = literal2(raw)
    image = bytes(32)+block
    asset, = [item for item in n64.regions(image) if item.get('layout') == packed_models.LAYOUT]
    assert asset['offset'] == 32
    assert asset['meshes'] == [dict(name='LOD 0', vertices=3, triangles=1)]
    preview = n64.preview(raw, asset, {})
    assert preview['vertices'] == [list(point) for point in POINTS]
    assert preview['edges'] == [(0, 1), (0, 2), (1, 2)]
    with pytest.raises(AssetError, match='Mesh'):
        n64.preview(raw, asset, dict(mesh=1))


@pytest.mark.parametrize('commands', [
    TRIANGLE+b'\0',
    b'\x20\x04'+TRIANGLE+b'\0',
    b'\x20\x03'+TRIANGLE+b'\0\xff',
    b'\x20\x03\x40\x01'+TRIANGLE+b'\0',
    b'\x20\x03\x63\x00\x00\x00\x00'+TRIANGLE+b'\0',
])
def test_invalid_commands_cannot_create_a_model(commands):
    assert not models.regions(literal2(model(commands)))


def test_truncated_or_checksum_invalid_models_are_declined():
    raw = model()
    assert not models.regions(literal2(raw[:-1]))
    broken = bytearray(literal2(raw))
    broken[-2] ^= 1
    assert not models.regions(broken)
    assert not models.regions(literal2(model(material=bytes(16))))

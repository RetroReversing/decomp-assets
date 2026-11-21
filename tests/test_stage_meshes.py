"""Synthetic vertex batches and signed-delta triangles."""

import struct

from decompassets.n64 import preview, stage_banks, stage_meshes


def _pack(*fields):
    value = offset = 0
    for width, number in fields:
        value |= (number & ((1 << width) - 1)) << offset
        offset += width
    return value.to_bytes((offset + 7) // 8, 'little')


def _bank(index):
    image = bytearray(400)
    struct.pack_into('>I', image, 4, 1)
    struct.pack_into('>II', image, 24, 3, 340)
    struct.pack_into('>3i', image, 48, 5, 0, -1)
    struct.pack_into('>III', image, 60, 0, 72, 0)
    struct.pack_into('>5I', image, 72 + 0x50, 1, 1, 1, 1, 220)
    # Load three vertices, emit one absolute triangle and one relative triangle, then end.
    commands = _pack((8, 0), (5, 2), (1, 1), (2, 3), (5, 0), (5, 1), (5, index),
                     (1, 1), (2, 0), (2, -2), (2, -1), (2, 0), (5, 0), (3, 7))
    struct.pack_into('>4H', image, 240, 3, 3, 256 - 72, 280 - 72)
    image[256:256 + len(commands)] = commands
    records = _pack((12, 0), (22, 0), (12, 1), (22, 0), (12, 2), (22, 0))
    image[280:280 + len(records)] = records
    points = _pack(*[(11, coord) for coord in (0, 0, 0, 1, 0, 0, 0, -1, 0)])
    image[340:340 + len(points)] = points
    asset = dict(offset=0, size=len(image), layout=stage_banks.TEXTURE, preview_settings={})
    return image, asset


def test_stage_mesh_preview_resolves_absolute_and_delta_indices():
    image, asset = _bank(2)
    model, = stage_meshes.regions(image, [asset], lambda: None)
    result = preview(image, model, {'mesh': 0})
    assert result['vertices'] == [(5, 0, -1), (6, 0, -1), (5, -1, -1)]
    assert [surface['indices'] for surface in result['surfaces']] == [(0, 1, 2), (0, 1, 2)]


def test_stage_mesh_rejects_triangle_outside_loaded_batch():
    image, asset = _bank(3)
    assert list(stage_meshes.regions(image, [asset], lambda: None)) == []

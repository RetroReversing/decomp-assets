"""Compressed section directories must bound every recovered mesh."""

import struct

import pytest

from decompassets import formats, n64
from decompassets.n64 import lz_section_meshes


def fixture():
    raw = bytearray(128)
    struct.pack_into('>I', raw, 0, 5)
    for i, (start, size) in enumerate(((48, 24), (72, 48), (120, 8), (128, 0), (128, 0))):
        struct.pack_into('>II', raw, 4+i*8, start, size)
    struct.pack_into('>6I', raw, 48, 0x01003006, 0x02000000, 0x05000204, 0, 0xdf000000, 0)
    for i, point in enumerate(((0, 0, 0), (100, 0, 0), (0, 100, 0))):
        struct.pack_into('>3hH2h4B', raw, 72+i*16, *point, 0, 0, 0, 255, 255, 255, 255)
    packed = bytearray(struct.pack('>I', len(raw)) + b'\xfe\xed\xf0' + raw[3:10])
    for at in range(10, len(raw), 8):
        packed += b'\xff' + raw[at:at+8]
    return bytes(raw), bytes(packed)


def test_detect_closed_mesh_and_preview():
    raw, packed = fixture()
    image = bytes(64) + packed
    rows = lz_section_meshes.meshes(raw)
    assert len(rows) == 1 and rows[0]['vertices'] == 3 and rows[0]['triangles'] == 1
    assets = lz_section_meshes.regions(image)
    assert len(assets) == 1
    preview = n64.preview(image, assets[0], {})
    assert preview['triangles'] == 1 and len(preview['vertices']) == 3
    assert 'transforms' in preview['note']
    with pytest.raises(formats.AssetError):
        n64.preview(image[:-1], assets[0], {})


def test_rejects_bad_sections_and_out_of_range_vertex_load():
    raw, _ = fixture()
    data = bytearray(raw)
    struct.pack_into('>I', data, 12, 80)
    assert not lz_section_meshes.meshes(data)
    data = bytearray(raw)
    struct.pack_into('>I', data, 52, 0x02000020)
    assert not lz_section_meshes.meshes(data)

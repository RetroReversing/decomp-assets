"""Validate model indices and texture extents in synthetic Siff archives."""

import struct

from decompassets.n64 import preview, siff_models


def _chunk(tag, payload):
    return struct.pack('>4sI', tag, len(payload)) + payload


def _archive(index):
    vertices = b''.join(struct.pack('>3h10x', *point) for point in [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    group = struct.pack('>2H', 3, 1) + vertices + bytes([0, 1, index, 0])
    node = struct.pack('>22x3H', 2, 6, 2) + group * 2
    texture = struct.pack('>2H16x', 2, 2) + bytes.fromhex('f801') + bytes(514)
    member = _chunk(b'Siff', _chunk(b'type', b'pdt2\0\0\0\0') + _chunk(b'node', node)
                    + _chunk(b'text', texture))
    data = struct.pack('>2I', 8, 0) + member
    return struct.pack('<I', len(data)) + b''.join(b'\0' + data[i:i + 8] for i in range(0, len(data), 8))


def _rom(index):
    image = bytearray(0x10100)
    offsets = []
    for _ in range(3):
        offsets.append(len(image))
        image.extend(_archive(index))
        image.extend(bytes(-len(image) % 16))
    struct.pack_into('>3I', image, 0x80, offsets[1], offsets[0], offsets[2])
    return image


def test_preview_model_and_its_texture_from_unordered_archive_table():
    image = _rom(2)
    rows = siff_models.regions(image)
    assert len(rows) == 6
    model = preview(image, rows[0], {'mesh': 0})
    assert model['details']['vertices'] == 6
    assert [surface['indices'] for surface in model['surfaces']] == [(0, 1, 2), (3, 4, 5)]
    texture = preview(image, rows[1], {'texture': 0})
    assert texture['media'] == 'image'
    assert texture['details']['format'] == 'ci8'


def test_reject_out_of_range_group_index():
    assert not siff_models.regions(_rom(3))

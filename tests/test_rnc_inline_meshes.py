"""Compressed local meshes require valid section bounds and resolved triangle slots."""
import struct

from decompassets import n64
from decompassets.n64 import rnc_inline_meshes as meshes

from .test_rnc import literal_block


def payload():
    points = b''.join(struct.pack('>hhhHhhBBBB', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                      for x, y in ((0, 0), (10, 0), (0, 10)))
    commands = b''.join(struct.pack('>II', a, b) for a, b in (
        (0x01003006, 0x04000000), (0x03000000, 0), (0xde000000, 0x07000000),
        (0x05000204, 0), (0xdf000000, 0)))
    start = 16+len(points)
    return struct.pack('>4I', 16, start, start+len(commands), 0) + points + commands


def test_checked_rnc_mesh_and_external_state():
    image = literal_block(payload())
    asset, = meshes.regions(image)
    preview = n64.preview(image, asset, {})
    assert preview['vertices'] == [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    assert preview['triangles'] == 1
    assert 'external sublists' in preview['note']


def test_invalid_sections_triangle_or_compression_are_rejected():
    raw = payload()
    assert not meshes.regions(literal_block(raw[:4] + struct.pack('>I', 65) + raw[8:]))
    assert not meshes.regions(literal_block(raw.replace(bytes.fromhex('05000204'), bytes.fromhex('05000206'))))
    assert not meshes.regions(literal_block(raw.replace(bytes.fromhex('07000000'), bytes.fromhex('08000000'))))
    assert not meshes.regions(literal_block(raw.replace(bytes.fromhex('07000000'), bytes.fromhex('07000008'))))
    packed = bytearray(literal_block(raw));packed[-1] ^= 1
    assert not meshes.regions(packed)

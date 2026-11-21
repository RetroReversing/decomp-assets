"""Check that an RNC scene resolves relative vertices inside its own record."""

import struct

from decompassets import n64
from decompassets.n64 import rnc_display_models

from .test_rnc import literal_block


def test_rnc_scene_resolves_vertices_and_skips_texture_placeholders():
    palette = b'palette ' + bytes(36) + struct.pack('>I', 2)
    texture = b'texture ' + bytes(52) + struct.pack('>I', 1)
    commands = struct.pack('>6I', 0x04000c2f, 0, 0xbf000000, 0x00000204, 0xb8000000, 0)
    points = [(32, 0, 0), (0, 32, 0), (0, 0, 32)]
    vertices = b''.join(struct.pack('>3h10x', *point) for point in points)
    vertex_base = 16+len(palette)+len(texture)+len(commands)
    raw = struct.pack('>II8x', 1, vertex_base) + palette + texture + commands + vertices
    image = literal_block(raw)
    asset, = [a for a in n64.regions(image) if a.get('layout') == rnc_display_models.LAYOUT]
    preview = n64.preview(image, asset, dict(mesh=0))
    assert preview['vertices'] == points
    assert preview['triangles'] == 1
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)
    assert preview['settings']['mesh'] == 0
    invalid = bytearray(raw)
    struct.pack_into('>I', invalid, vertex_base-len(commands)+4, 48)
    invalid = literal_block(invalid)
    assert not any(a.get('layout') == rnc_display_models.LAYOUT for a in n64.regions(invalid))

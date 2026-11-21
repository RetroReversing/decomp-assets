import struct

import pytest

from decompassets.n64 import lz_directory_models as models
from decompassets.n64 import lz_texture_directories as reader

from .test_lz_texture_directories import _pack


def _model():
    data = bytearray(240)
    struct.pack_into('>10I', data, 0, 96, len(data), 148, 148, 1, 0, 0, 64, 96, 0)
    struct.pack_into('>6I', data, 64, 0xfd100000, 40, 0xf3000000, 0, 0xdf000000, 0)
    struct.pack_into('>4I', data, 96, 1, 0, 0, 208)
    for i, (x, y) in enumerate(((0, 0), (40, 0), (0, 60))):
        struct.pack_into('>3hH2h4B', data, 160 + i*16, x, y, 0, 0x803f, 0, 0, 255, 255, 255, 255)
    struct.pack_into('>8I', data, 208, 0x01003006, 160, 0xde000000, 64,
                     0x05000204, 0, 0xdf000000, 0)
    return data


def test_indexed_object_uses_closed_geometry_and_texture_state():
    data = _model()
    entries = models.meshes(data, reader.layout(data), lambda: None)
    mesh, = entries
    assert (mesh['vertices'], mesh['triangles']) == (3, 1)
    packed = _pack(data)
    result = models.preview(packed, models.asset(0, len(packed), entries), {})
    assert result['vertices'] == [(0, 0, 0), (40, 0, 0), (0, 60, 0)]
    assert result['surfaces'][0]['indices'] == (0, 1, 2)


@pytest.mark.parametrize('offset,replacement', [(72, 0x01003006), (168-2, 0x82000000)])
def test_unrecognized_child_geometry_or_vertex_flags_are_rejected(offset, replacement):
    data = _model()
    struct.pack_into('>I', data, offset, replacement)
    assert not models.meshes(data, reader.layout(data), lambda: None)

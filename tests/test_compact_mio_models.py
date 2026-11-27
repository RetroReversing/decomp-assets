import struct

from decompassets.n64 import compact_mio_models as models

from .test_compact_mio_textures import _packed


def _mesh():
    data = bytearray(128)
    for i, (x, y, z) in enumerate(((0, 0, 0), (40, 0, 0), (0, 60, 0), (40, 60, 20))):
        struct.pack_into('>3hH2h4B', data, i*16, x, y, z, 0, 0, 0, 255, 255, 255, 255)
    struct.pack_into('>8I', data, 64, 0x01004008, 0x01000000,
                     0x06000204, 0x00020406, 0xdf000000, 0, 0, 0)
    return data


def test_meshes_require_bounded_vertices_and_closed_triangles():
    data = _mesh()
    found = models.meshes(data)
    assert len(found) == 1
    assert (found[0]['vertices'], found[0]['triangles']) == (4, 2)
    packed = _packed(data)
    asset = dict(offset=0, size=len(packed), unpacked=len(data), meshes=found,
                 preview_settings=dict(source='rom', format='auto', offset=0))
    result = models.preview(packed, asset, {})
    assert len(result['vertices']) == 4
    assert result['triangles'] == 2
    struct.pack_into('>I', data, 68, 0x0100fff0)
    assert models.meshes(data) == []


def test_model_banks_expose_aggregate_geometry_counts():
    data = _mesh()
    packed = _packed(data)
    image = bytearray(0x3000)
    for i in range(8):
        start = 0x1800 + i*len(packed)
        image[start:start+len(packed)] = packed
        struct.pack_into('>3I', image, 0x1000+i*12, start, start+len(packed), len(data))
    banks = models.regions(image)
    assert len(banks) == 8
    assert all((bank['vertices'], bank['triangles']) == (4, 2) for bank in banks)
    assert all('nodes' not in bank for bank in banks)

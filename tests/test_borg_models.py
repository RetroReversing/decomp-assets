import struct

from decompassets.n64 import borg_models


def test_borg_model_resolves_vertex_cache_and_rejects_invalid_indices():
    bounds, vertices, commands, table, materials = 80, 336, 384, 416, 420
    data = bytearray(440)
    struct.pack_into('>I', data, 4, 1)
    struct.pack_into('>6I', data, 44, table, bounds, vertices, 3, 0, materials)
    for i, (x, y) in enumerate(((0, 0), (8, 0), (0, 8))):
        struct.pack_into('>3h', data, vertices+i*16, x, y, 0)
    struct.pack_into('>8I', data, commands, 0x01008010, 0x0e000080, 0x01003006, 0x0a000000,
                     0x05000204, 0, 0xdf000000, 0)
    struct.pack_into('>I', data, table, commands)
    asset, = borg_models.regions(data, [(2, 0, len(data), len(data), 0)])
    result = borg_models.preview(data, asset, {})
    assert result['surfaces'][0]['indices'] == (0, 1, 2)
    assert result['vertices'][2] == (0, 8, 0)
    struct.pack_into('>I', data, commands+16, 0x05000208)
    assert borg_models.geometry(data) is None

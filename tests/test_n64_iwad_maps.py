import struct

from decompassets.n64 import iwad_maps


def test_sector_walls_from_a_bounded_nested_map():
    data = bytearray(12)
    entries = []
    def add(name, payload):
        entries.append((len(data), len(payload), name))
        data.extend(payload)
    add(b'VERTEXES', struct.pack('<4i', 0, 0, 128 << 16, 0))
    add(b'LINEDEFS', struct.pack('<HHIhhhh', 0, 1, 0, 0, 0, 0, -1))
    add(b'SIDEDEFS', struct.pack('<5Hh', 0, 0, 0, 0, 0, 0))
    add(b'SECTORS', struct.pack('<hh20x', 0, 128))
    for name in (b'THINGS', b'SEGS', b'NODES', b'LEAFS'):
        add(name, b'')
    directory = len(data)
    for start, size, name in entries:
        data.extend(struct.pack('<II8s', start, size, name))
    struct.pack_into('<4sII', data, 0, b'IWAD', len(entries), directory)
    vertices, triangles = iwad_maps.geometry(data)
    assert vertices == [(0, 0, 0), (128, 0, 0), (128, 128, 0), (0, 128, 0)]
    assert triangles == [(0, 1, 2), (0, 2, 3)]
    struct.pack_into('<H', data, entries[1][0], 2)
    assert iwad_maps.geometry(data) is None

import struct

from decompassets.n64 import be_iwad_maps


def test_sector_walls_validate_indices():
    lumps = {
        'VERTEXES': struct.pack('<4h', 0, 0, 128, 0),
        'LINEDEFS': struct.pack('<HH8xhh', 0, 1, 0, -1),
        'SIDEDEFS': struct.pack('<28xh', 0),
        'SECTORS': struct.pack('<hh22x', 0, 128),
    }
    vertices, triangles = be_iwad_maps.geometry(lumps)
    assert vertices == [(0, 0, 0), (128, 0, 0), (128, 128, 0), (0, 128, 0)]
    assert triangles == [(0, 1, 2), (0, 2, 3)]
    lumps['LINEDEFS'] = struct.pack('<HH8xhh', 2, 1, 0, -1)
    assert be_iwad_maps.geometry(lumps) is None
    lumps.pop('VERTEXES')
    assert be_iwad_maps.geometry(lumps) is None

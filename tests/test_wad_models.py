import struct

from decompassets.n64 import wad_models


def test_indexed_node_geometry_and_bounds():
    header = b'2KMD' + struct.pack('>3I', 1, 16, 0)
    node = struct.pack('>6I', 3, 1, 24, 72, 78, 0)
    vertices = b''.join(struct.pack('>hhhHhhBBBB', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                        for x,y in ((0,0), (1,0), (0,1)))
    data = header + node + vertices + struct.pack('>3H', 0, 1, 2)
    nodes = wad_models._model(data)
    assert nodes and nodes[0][1] == 3 and nodes[0][2] == [(0, 1, 2)]
    asset = dict(offset=0, size=len(data), decoded_size=len(data), meshes=[dict(node=0)])
    preview = wad_models.preview(data, asset, {})
    assert preview['vertices'][1] == (1, 0, 0)
    assert preview['triangles'] == 1
    assert wad_models._model(data[:-2] + b'\0\x03') is None
    assert wad_models._model(data[:-1]) is None

import struct

from decompassets.n64 import segmented_model_resources as models


def test_segmented_model_sections_and_indices():
    commands = (struct.pack('>I', 24) + b'\0\0\x08\x0b\x09\x04\x0a\0' + bytes(4)
                + struct.pack('>6I', 0x01003006, 0x09000000, 0x05000204, 0, 0xdf000000, 0))
    vertex = struct.pack('>HHI', 3, 0x200, 0)
    vertex += b''.join(struct.pack('>hhhHhhBBBB', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                       for x,y in ((0,0), (1,0), (0,1)))
    image = bytes(4) + struct.pack('<3I', len(commands), len(vertex), 0) + commands + vertex
    assets = models.regions(image)
    assert len(assets) == 1
    assert assets[0]['vertices'] == 3
    result = models.preview(image, assets[0], {'mesh': 0})
    assert result['triangles'] == 1
    assert result['surfaces'][0]['indices'] == (0, 1, 2)
    assert models.regions(image[:-1]) == []

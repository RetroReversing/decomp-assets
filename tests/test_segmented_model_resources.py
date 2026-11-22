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


def test_compressed_model_in_bounded_directory():
    commands = (struct.pack('>I', 24) + b'\0\0\x08\x0b\x09\x04\x0a\0' + bytes(4)
                + struct.pack('>6I', 0x01003006, 0x09000000, 0x05000204, 0, 0xdf000000, 0))
    vertex = struct.pack('>HHI', 3, 0x200, 0)
    vertex += b''.join(struct.pack('>hhhHhhBBBB', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                       for x,y in ((0,0), (1,0), (0,1)))
    raw = struct.pack('<3I', len(commands), len(vertex), 0) + commands + vertex
    packed = b''.join(bytes([(1 << len(raw[i:i+8])) - 1]) + raw[i:i+8] for i in range(0, len(raw), 8))
    table_end = 36 + 8 * 16
    header = struct.pack('>4I', 2, 8, 3, table_end + len(packed)) + b'\xff' * 20
    row = struct.pack('>4I', 17, table_end, len(packed), len(raw))
    image = header + row + bytes(7 * 16) + packed
    assets = models.regions(image)
    assert len(assets) == 1
    assert assets[0]['expanded_size'] == len(raw)
    assert models.preview(image, assets[0], {})['triangles'] == 1
    assert models.regions(image[:-1]) == []

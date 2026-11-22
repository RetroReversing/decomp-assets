"""A compressed graphics resource must resolve its local geometry and texture."""

import struct

from decompassets.n64 import mio0_graphics


def test_compressed_local_mesh_and_image_previews():
    raw = bytearray(4096)
    for i in range(3):
        struct.pack_into('>3h', raw, 0x100+i*16, i, 0, 0)
    struct.pack_into('>10I', raw, 0x200, 0x01003006, 0x08000100,
                     0x05000204, 0, 0x05000204, 0, 0x05000204, 0, 0xdf000000, 0)
    struct.pack_into('>8I', raw, 0x300, 0xfd100000, 0x08000400, 0xf5100000, 0,
                     0xf3000000, 0, 0xf2000000, 0x0000c00c)
    mask = bytes([255]) * (len(raw)//8)
    cursor = 16 + len(mask)
    image = b'MIO0' + struct.pack('>3I', len(raw), cursor, cursor) + mask + raw
    images = []
    models = mio0_graphics.regions(image, images=images)
    assert len(models) == len(images) == 1
    assert mio0_graphics.preview(image, models[0], {})['triangles'] == 3
    assert mio0_graphics.preview_image(image, images[0], {})['details']['width'] == 4
    raw[0x205] = 10
    assert not mio0_graphics.meshes(raw)

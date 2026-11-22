"""Models and texture pointers in mixed compressed resource archives."""

import struct

from decompassets.n64 import lzss_archive_images, lzss_archive_models


def test_mixed_directory_and_checked_model_lists():
    resource = bytearray(160)
    struct.pack_into('>3I', resource, 0, 0x05000010, 0x05000030, 0)
    for at in (16, 48):
        struct.pack_into('>6I', resource, at, 0x04000c2f, 0x05000060,
                         0xbf000000, 0x00000204, 0xb8000000, 0)
    struct.pack_into('>3h', resource, 96, 1, 0, 0)
    struct.pack_into('>3h', resource, 112, 0, 1, 0)
    struct.pack_into('>3h', resource, 128, 0, 0, 1)
    assert len(lzss_archive_models.meshes(resource)) == 2
    image = bytearray(40)
    struct.pack_into('>2I', image, 0, 2, 0)
    struct.pack_into('>I4sII', image, 8, 40, b'COPY', len(resource), len(resource))
    image.extend(resource)
    struct.pack_into('>I4sII', image, 24, len(image), b'LHUF', 8, 2)
    image.extend(b'\0\0')
    archive, = lzss_archive_images.archives(image)
    assert archive[0] == 0
    assert lzss_archive_images.unpack(image, *archive[:1], archive[1][0]) == resource
    items = lzss_archive_models.regions(image)
    assert len(items) == 1 and items[0]['nodes'] == 2
    assert lzss_archive_models.preview(image, items[0], {'mesh': 1})['triangles'] == 1
    resource[0] = 6
    assert not lzss_archive_models.meshes(resource)


def test_local_texture_commands_resolve_palette_and_pixels():
    image = bytearray(800)
    struct.pack_into('>12I', image, 0,
                     0xfd100000, 0x05000080,
                     0xf0000000, 0x073fc000,
                     0xfd080003, 0x05000280,
                     0xf5080000, 0,
                     0xf4000000, 0x0000000c,
                     0xf2000000, 0x0000c00c)
    items = [{'offset': 0, 'size': 48}]
    assert lzss_archive_models.textures(image, items) == [
        dict(offset=640, width=4, height=4, bits=8, palette=128)]
    struct.pack_into('>I', image, 20, 0x06000280)
    assert lzss_archive_models.textures(image, items) == []

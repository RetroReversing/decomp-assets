"""Exercise scene recognition with a synthetic textured triangle."""

import struct

from decompassets import formats
from decompassets.n64 import preview, yay0_scenes


def _scene():
    data = bytearray(0x140)
    struct.pack_into('>4sIII', data, 0, b'niff', 0x05000100, 0x20000, len(data))
    struct.pack_into('>I', data, 60, 0x13c)
    struct.pack_into('>H', data, 88, 1)
    struct.pack_into('>I', data, 0x13c, 0x118)
    struct.pack_into('>8I', data, 0x118, 0xc0, 0x90, 0, 0x78, 0, 0, 0, 0)
    data[0x78:0x80] = bytes.fromhex('f801 07c1 003f ffff')
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3hH2h4B', data, 0x90+i*16, x, y, 0, 0, 0, 0, 255, 255, 255, 255)
    struct.pack_into('>14I', data, 0xc0, 0xfd100000, 0x05000000, 0xf3000000, 0x07003000,
                     0xf5100200, 0, 0xf2000000, 0x0000c000, 0x01003006, 0x04000000,
                     0x05000204, 0, 0xdf000000, 0)
    return bytes(data)


def _pack(data):
    masks = bytes([255])*(((len(data)+31)//32)*4)
    return struct.pack('>4sIII', b'Yay0', len(data), 16+len(masks), 16+len(masks)) + masks + data


def test_yay0_scene_previews_textures_and_geometry_from_one_resource():
    packed = _pack(_scene())
    image = b'\0\0' + packed + b'padding'
    models, textures = yay0_scenes.regions(image)
    assert models['size'] == textures['size'] == len(packed)
    assert models['layout'] == yay0_scenes.MODEL and textures['layout'] == yay0_scenes.IMAGE
    result = preview(image, models, {'mesh': 0})
    assert result['vertices'] == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    assert result['triangles'] == 1
    png = preview(image, textures, {'texture': 0})
    assert (png['details']['width'], png['details']['height']) == (4, 1)
    assert formats.unpack_extent(packed+b'extra')[2] == len(packed)
    assert not yay0_scenes.regions(image[:-8])


def test_yay0_scene_rejects_invalid_vertex_mapping():
    data = bytearray(_scene())
    struct.pack_into('>I', data, 0xe4, 0x04000100)
    assert not yay0_scenes.regions(_pack(data))

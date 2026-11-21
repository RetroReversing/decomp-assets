import struct

from decompassets.n64 import nested_scenes, preview


def _scene():
    resource = bytearray(0x180)
    struct.pack_into('>4s5I', resource, 0, b'64\x008', 1, 0, 0, 0x3f800000, 0xf0)
    resource[0x30:0x38] = bytes.fromhex('0123456789abcdef')
    resource[0x40:0x60] = bytes.fromhex('f801 07c1 003f ffff')*4
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3hH2h4B', resource, 0xc0+index*16, x, y, 0, 0, 0, 0, 255, 255, 255, 255)
    struct.pack_into('>20I', resource, 0xf0,
                     0xba000e02, 0x8000, 0xfd100000, 0x02000040, 0xf0000000, 0x0703c000,
                     0xfd500000, 0x02000030, 0xf3000000, 0x07003000, 0xf5400200, 0,
                     0xf2000000, 0x0003c000, 0x04000c2f, 0x020000c0, 0xbf000000, 0x00000204,
                     0xb8000000, 0)
    outer = struct.pack('>4s5I', b'64\x008', 1, 0, 7, 1, 0x40).ljust(0x40, bytes(1))
    return outer + resource


def _pack(data):
    payload = b''.join(b'\xff'+data[at:at+8] for at in range(0, len(data), 8))
    return struct.pack('<I', len(payload)) + payload


def test_nested_scene_previews_local_palettes_and_model_geometry():
    compressed = _pack(_scene())
    image = compressed + b'extra'
    model, texture = nested_scenes.regions(image)
    assert model['size'] == texture['size'] == len(compressed)
    assert len(model['meshes']) == texture['texture_count'] == 1
    geometry = preview(image, model, {'mesh': 0})
    assert geometry['vertices'] == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    assert geometry['triangles'] == 1
    result = preview(image, texture, {'texture': 0})
    assert (result['details']['width'], result['details']['height']) == (16, 1)
    assert not nested_scenes.regions(compressed[:-1])


def test_nested_lzss_uses_full_ring_and_input_length():
    payload = bytes.fromhex('01 41 ee f0')
    stream = struct.pack('<I', len(payload)) + payload
    assert nested_scenes.unpack(stream) == b'AAAA'
    assert nested_scenes.unpack(stream[:-1]) is None

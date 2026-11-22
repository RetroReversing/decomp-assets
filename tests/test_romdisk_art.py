import struct

from decompassets.n64 import romdisk_art


def fixture():
    data = bytearray(508)
    struct.pack_into('>II', data, 0, 448, 5)
    data[16:80] = bytes([255, 0, 0, 255])*16
    struct.pack_into('>IIIHH', data, 128, 0, 176, 5, 4, 4)
    struct.pack_into('>II', data, 192+12, 320, 256)
    for i, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0))):
        struct.pack_into('>3h', data, 256+16*i, *point)
    struct.pack_into('>8I', data, 320, 0x01003006, 0x0e000000, 0xde000000, 176,
                     0x05000204, 0, 0xdf000000, 0)
    for i, (tag, at, size) in enumerate(((b'TEXR', 16, 64), (b'TXHD', 128, 1),
                                         (b'TXLD', 176, 16), (b'OBHD', 192, 1), (b'OBJS', 256, 96))):
        struct.pack_into('>4sII', data, 448+12*i, tag, at, size)
    return data


def test_chunked_textures_and_models_require_bounded_geometry():
    data = fixture()
    sections = romdisk_art.chunks(data)
    assert romdisk_art.textures(data, sections)[0]['format'] == 'rgba8888'
    assert romdisk_art.meshes(data, sections)[0]['triangles'] == 1
    struct.pack_into('>I', data, 336, 0x05000206)
    assert not romdisk_art.meshes(data, sections)
    data = fixture()
    struct.pack_into('>H', data, 140, 1025)
    assert not romdisk_art.textures(data, romdisk_art.chunks(data))

import struct
import zlib

from decompassets.n64 import deflate_segment_models


def _rom():
    data = bytearray(0x120)
    struct.pack_into('>4I', data, 0, 0x05000040, 0x05000050, 0x05000060, 0x05000070)
    for index, point in enumerate(((0, 0, 0), (10, 0, 0), (0, 10, 5))):
        struct.pack_into('>3hH2h4B', data, 0x40+16*index, *point, 0, 0, 0, 255, 255, 255, 255)
    struct.pack_into('>6I', data, 0x100, 0x01003006, 0x05000040, 0x05000204, 0, 0xdf000000, 0)
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(data) + compressor.flush()
    end = (0x100+len(packed)+15)&~15
    image = bytearray(end)
    struct.pack_into('>2I', image, 0x20, 0x100, end)
    image[0x100:0x100+len(packed)] = packed
    return bytes(image)


def test_segment_geometry_preview():
    image = _rom()
    assets = deflate_segment_models.regions(image)
    assert len(assets) == 1
    assert assets[0]['triangles'] == 1
    result = deflate_segment_models.preview(image, assets[0], {'mesh': 0})
    assert result['vertices'] == [(0, 0, 0), (10, 0, 0), (0, 10, 5)]
    assert result['triangles'] == 1


def test_requires_segment_mapping():
    assert not deflate_segment_models._meshes(bytes(512))

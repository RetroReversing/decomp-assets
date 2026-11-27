import struct

import pytest

from decompassets import formats
from decompassets.n64 import big_models, big_tagged_textures

from .test_n64_big_resources import _literal


def _archive():
    page = bytearray(8192)
    at = 100
    for width, height in ((8, 4), (4, 4)):
        header = b'TEX\0'+struct.pack('<I', 20)+struct.pack('>HH', width, height)+bytes(16)
        data = bytes(range(width*height))
        row = header+struct.pack('<II', 1, 12)+b'BMP\0'+struct.pack('<I', len(data))+data+bytes(4)
        page[at:at+len(row)] = row
        at += len(row)
    page[at:at+520] = b'PAL\0'+struct.pack('<I', 512)+b'\xff\xff'*256
    payload = _literal(page)
    return b'testBIG\0'+struct.pack('>I2I', len(page), (20 << 4)|1, (20+len(payload)) << 4)+payload


def test_tagged_paged_textures_and_frame_selection():
    image = _archive()
    textures = []
    big_models.regions(image, images=textures)
    assert len(textures) == 1 and textures[0]['frames'] == 2
    result = big_tagged_textures.preview(image, textures[0], {'frame': 1})
    assert result['details']['width'] == 4 and result['details']['height'] == 4
    with pytest.raises(formats.AssetError):
        big_tagged_textures.preview(image, textures[0], {'frame': 2})


def test_malformed_dimensions_and_truncated_palettes_are_rejected():
    image = bytearray(_archive())
    assert not list(big_models.regions(bytes(image[:-100]), images=[]))
    assert big_tagged_textures._group(b'TEX\0\x14\0\0\0'+bytes(64), 0) is None


def _model_archive(bad_index=False):
    page = bytearray(8192)
    vertices = b''.join(struct.pack('>3hHhhI', *point, 0, 0, 0, 0xffffffff)
                        for point in ((0,0,0), (10,0,0), (0,20,10)))
    commands = bytes((0x64,3,0,0,0x67,0,1,3 if bad_index else 2,0x69,1,0,0,0,0,0,0))
    model = (b'VER\0'+struct.pack('<I', len(vertices))+vertices+bytes(4)+b'SHP\0'
             +struct.pack('<I', 17)+bytes(8)+commands)
    page[100:100+len(model)] = model
    payload = _literal(page)
    return b'testBIG\0'+struct.pack('>I2I', len(page), (20 << 4)|1, (20+len(payload)) << 4)+payload


def test_tagged_paged_mesh_and_invalid_triangle():
    from decompassets.n64 import big_tagged_models

    image = _model_archive()
    model, = big_models.regions(image, images=[])
    assert model['vertices'] == 3 and model['triangles'] == 1
    preview = big_tagged_models.preview(image, model, {})
    assert preview['vertices'] == [(0,0,0), (10,0,0), (0,20,10)]
    assert preview['surfaces'][0]['indices'] == (0,1,2)
    assert not big_models.regions(_model_archive(bad_index=True), images=[])
    with pytest.raises(formats.AssetError):
        big_tagged_models.preview(image, model, {'mesh': 1})

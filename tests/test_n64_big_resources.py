import struct

import pytest

from decompassets import formats
from decompassets.n64 import big_models, big_pages, big_textures


def _literal(data):
    stream = b''.join(b'\x00' + data[i:i+8] for i in range(0, len(data), 8)) + b'\x03\x00\x00'
    return stream + b'\xff' * (-len(stream) % 4)


def _archive(compressed):
    page = bytearray(8192)
    model = bytearray(124)
    struct.pack_into('>2I', model, 0, 1, 96)
    for i, point in enumerate(((0, 0, 0), (10, 0, 0), (0, 20, 0))):
        struct.pack_into('>3hHhhI', model, 48+i*16, *point, 0, 0, 0, 0xffffffff)
    struct.pack_into('>4I', model, 96, 3, 48, 3, 112)
    model[112:124] = bytes.fromhex('100300002001000030000102')
    page[100:108] = b'ARN\0' + struct.pack('<I', len(model))
    page[108:108+len(model)] = model

    texture = bytearray(560)
    struct.pack_into('>2I', texture, 0, 2, 48)
    struct.pack_into('>4BI', texture, 8, 1, 2, 1, 0, 24)
    struct.pack_into('>4BI', texture, 16, 1, 2, 0, 1, 40)
    texture[24:40] = bytes(range(16))
    texture[40:48] = bytes.fromhex('0123456789abcdef')
    texture[48:] = b'\xff\xff' * 256
    page[500:508] = b'PKG\0' + struct.pack('<I', len(texture))
    page[508:508+len(texture)] = texture
    payload = _literal(page) if compressed else bytes(page)
    table_end = 20
    return (b'testBIG\0' + struct.pack('>I2I', len(page), (table_end << 4) | int(compressed),
                                      (table_end + len(payload)) << 4) + payload)


@pytest.mark.parametrize('compressed', [False, True])
def test_model_and_texture_from_paged_archive(compressed):
    image = _archive(compressed)
    archive, = big_pages.archives(image)
    assert big_pages.extract(image, archive, 100, 8).startswith(b'ARN\0')
    textures = []
    models = big_models.regions(image, images=textures)
    assert len(models) == len(textures) == 1
    model = big_models.preview(image, models[0], {})
    assert model['vertices'] == [(0, 0, 0), (10, 0, 0), (0, 20, 0)]
    assert model['triangles'] == 1 and model['surfaces'][0]['indices'] == (0, 1, 2)
    assert textures[0]['frames'] == 2
    assert big_textures.preview(image, textures[0], {'frame': 1})['details']['format'] == 'ci4'
    with pytest.raises(formats.AssetError):
        big_models.preview(image, models[0], {'mesh': 1})
    with pytest.raises(formats.AssetError):
        big_textures.preview(image, textures[0], {'frame': 2})


def test_page_and_mesh_validation_rejects_damage():
    image = _archive(False)
    assert not list(big_pages.archives(image[:-1]))
    damaged = bytearray(image)
    damaged[20+108+122] = 9
    textures = []
    assert not big_models.regions(bytes(damaged), images=textures)
    assert len(textures) == 1


def test_resources_sharing_one_page_remain_selectable():
    image = bytearray(_archive(False))
    image[20+2000:20+2132] = image[20+100:20+232]
    image[20+3000:20+3568] = image[20+500:20+1068]
    textures = []
    models = big_models.regions(bytes(image), images=textures)
    assert len(models) == len(textures) == 1
    assert len(models[0]['meshes']) == 2 and textures[0]['frames'] == 4
    assert big_models.preview(image, models[0], {'mesh': 1})['triangles'] == 1
    assert big_textures.preview(image, textures[0], {'frame': 3})['details']['format'] == 'ci4'

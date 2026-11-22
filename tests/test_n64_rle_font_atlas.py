import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import rle_font_atlas as atlas


def _fixture():
    base, count = 0x400, 16
    image = bytearray(base + 4 + count * 8)
    for i in range(16):
        struct.pack_into('>4BI', image, 0x100 + i * 8, 65 + i, 8, 2, 0, i * 16)
    struct.pack_into('>I', image, base, count)
    for i in range(count):
        offset = len(image) - base
        if i == 8:
            size, data = 512, b'\xff\xff' * 256
        elif i == 9:
            size, data = 0x82000100, b'\xff\x01\xfb\x01'
        else:
            size, data = 4, b'ABCD'
        struct.pack_into('>II', image, base + 4 + i*8, size, 0x01000000 | offset)
        image.extend(data)
    return bytes(image)


def test_rle_atlas_directory_and_preview():
    image = _fixture()
    assets = atlas.regions(image)
    assert len(assets) == 1 and assets[0]['texture_count'] == 16
    assert assets[0]['textures'][0]['preview_settings']['format'] == 'ci8'
    result = atlas.preview(image, assets[0], {'texture': 7})
    assert result['mime'] == 'image/png'
    assert result['details']['width'] == 8 and result['details']['height'] == 2
    with pytest.raises(AssetError):
        atlas.preview(image[:assets[0]['offset'] + 1], assets[0], {})


def test_rle_rejects_truncation_and_false_descriptors():
    assert atlas._rle(b'\xff', 130) is None
    assert atlas._rle(b'\x02AB', 3) is None
    image = bytearray(_fixture())
    image[0x100 + 3] = 1
    assert not atlas.regions(image)

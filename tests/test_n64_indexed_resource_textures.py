import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import indexed_resource_textures as textures


def test_paletted_texture_dimensions_and_palette_choices():
    palette = struct.pack('>II', 1, 2) + b'\x00\x01' * 256 + b'\xff\xff' * 256
    image = palette + struct.pack('>BBHI', 1, 2, 1, 0) + bytes(8)
    rows = [(0x30000000 | len(palette), 0), (0x40000010, len(palette))]
    item = textures.texture(image, 0, rows, 1)
    assert item['palettes'] == 2 and item['preview_settings']['width'] == 4
    asset = dict(textures=[item], preview_settings={'format':'auto'}, reason='checked')
    first = textures.preview(image, asset, {'palette':0})
    second = textures.preview(image, asset, {'palette':1})
    assert first['mime'] == second['mime'] == 'image/png'
    assert first['data_url'] != second['data_url']
    with pytest.raises(AssetError):
        textures.preview(image[:-1], asset, {})


def test_rejects_inconsistent_sizes_and_palette_references():
    image = struct.pack('>BBHI', 1, 2, 1, 3) + bytes(8)
    rows = [(0x40000010, 0)]
    assert textures.texture(image, 0, rows, 0) is None
    rgba = struct.pack('>BBHI', 1, 2, 0, 0) + bytes(16)
    assert textures.texture(rgba, 0, [(0x40000018, 0)], 0)['preview_settings']['format'] == 'rgba5551-be'
    assert textures.texture(rgba[:-1], 0, [(0x40000018, 0)], 0) is None

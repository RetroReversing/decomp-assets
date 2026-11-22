import struct

from decompassets.n64 import ia_font_textures


def test_indexed_intensity_font_and_palette():
    rows = b''.join(struct.pack('>H5B', 32 + 8*i, 33+i, 2, 2, 0, 0) for i in range(32))
    prefix = rows + b'\0\0'
    prefix += bytes(-len(prefix) % 16)
    palette = bytes(4) + b''.join(bytes((255 - i * 16, 255)) for i in range(14))
    image = prefix + palette + b'\x23\x45' + bytes(6) + bytes(8 * 31)
    assets = ia_font_textures.regions(image)
    assert len(assets) == 1
    assert assets[0]['texture_count'] == 32
    assert assets[0]['textures'][0]['preview_settings']['format'] == 'ci4'
    result = ia_font_textures.preview(image, assets[0], {'texture': 0})
    assert result['media'] == 'image'
    assert result['details']['glyph'] == '!'
    assert result['details']['format'] == 'CI4 / IA16'
    assert ia_font_textures.regions(image[:-8]) == []

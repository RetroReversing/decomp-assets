import base64

from decompassets.n64 import terminated_rgba_tiles as tiles


def test_only_repeated_bounded_tiles_are_previewed():
    marker = b'\xb8'+bytes(7)
    image = (marker+b'\xff\xff'*1024)*2+marker
    bank, = tiles.regions(image)
    assert bank['frames'] == 2
    result = tiles.preview(image, bank, {'frame': 1})
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')
    assert not tiles.regions(image[:tiles._STRIDE+8])


def test_indexed_and_ambiguous_tiles_are_not_rendered_as_rgba():
    marker = b'\xb8'+bytes(7)
    indexed = (marker+bytes([0x11, 0x22])*1024)*2+marker
    bank, = tiles.regions(indexed)
    assert bank['indexed'] and bank['width'] == 64
    result = tiles.preview(indexed, bank, {})
    assert result['details']['format'] == '4-bit indices, grayscale'
    ambiguous = (marker+bytes([0x11, 0x23])*1024)*2+marker
    assert not tiles.regions(ambiguous)
    rgba = (marker+bytes([0x12, 0x34])*1024)*2+marker
    bank, = tiles.regions(rgba)
    assert not bank['indexed'] and bank['width'] == 32

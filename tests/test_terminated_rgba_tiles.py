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

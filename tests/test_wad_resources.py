import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import lzhuf, wad_resources


def test_huffman_initial_codes_and_truncation():
    assert lzhuf.unpack(bytes.fromhex('e680'), 1) == b'A'
    assert lzhuf.unpack(bytes.fromhex('e700'), 1) == b'B'
    assert lzhuf.unpack(bytes.fromhex('c600'), 1) == b'\0'
    with pytest.raises(AssetError):
        lzhuf.unpack(b'', 1)


def test_nested_archive_texture():
    name = lambda s: s.encode().ljust(20, b'\0')
    texture = struct.pack('>4I', 2, 2, 0, 0) + b'\0\1\2\3' + bytes(512)
    inner_file = 8 + 32 + 36
    inner = (struct.pack('>II', 1, 1) + struct.pack('>20sIII', name('FOLDER'), 40, 1, 0)
             + struct.pack('>20sIIII', name('IMAGE.TEX'), inner_file, 1, len(texture), len(texture)) + texture)
    top_file = 8 + 32 + 4 * 36
    row = struct.pack('>20sIIII', name('INNER.WAD'), top_file, 4, len(inner), len(inner))
    image = (struct.pack('>II', 1, 1) + struct.pack('>20sIII', name('ROOT'), 40, 4, 0)
             + row * 4 + inner)
    assets = wad_resources.regions(image)
    assert len(assets) == 1
    result = wad_resources.preview(image, assets[0], {})
    assert result['media'] == 'image'
    assert result['details']['width'] == 2
    assert wad_resources.regions(image[:-1]) == []

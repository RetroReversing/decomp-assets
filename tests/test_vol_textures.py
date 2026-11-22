import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import vol_textures


def literal(data):
    return b''.join(b'\0\0' + data[i:i+16] for i in range(0, len(data), 16))


def fixture():
    metadata = b'\0\1\0\x37\0\0\0\4' + bytes(24)
    palette = b'\1' + bytes(7) + b'\xff\xff' * 256
    image = b'\0\x40\x08\x08\x33\x01\x01\x21' + bytes(8) + bytes(range(128))
    other = b'other'
    members = [metadata, palette, image, other]
    encoded = [literal(metadata), palette, literal(image), other]
    header = b'dvoL' + struct.pack('>IIII', 3, 0, 4, 52)
    table = b''.join(struct.pack('>II', (0x01200000 if i in (0, 2) else 0x01000000) | len(x), len(members[i]))
                     for i, x in enumerate(encoded))
    return header + table + b''.join(encoded)


def test_lz_literals_matches_and_bounds():
    assert vol_textures.unpack(b'\x08\0abc\x00\x03', 6) == b'abcabc'
    with pytest.raises(AssetError):vol_textures.unpack(b'\1\0\0\1', 3)
    with pytest.raises(AssetError):vol_textures.unpack(b'\0', 1)


def test_archive_preview_and_reject_damage():
    data=fixture(); assets=vol_textures.regions(data)
    assert len(assets)==1 and assets[0]['texture_count']==2
    assert vol_textures.preview(data, assets[0], {'texture': 1})['mime']=='image/png'
    assert vol_textures.regions(data[:-1])==[]
    with pytest.raises(AssetError):vol_textures.preview(data,assets[0],{'texture':2})

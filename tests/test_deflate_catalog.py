"""Synthetic native texture records and their exact zlib extents."""

import base64
import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import deflate_catalog, preview


def _image():
    base = 0x400
    image = bytearray(base)
    # Build the cartridge address from the masked catalog offset and base.
    struct.pack_into('>I', image, 0, 0x3c01f0ff)
    struct.pack_into('>5I', image, 32, 0x3421ffff, 0x3c080000, 0x25080400, 0x01215024, 0x01482021)
    image.extend(bytes(16))
    for index in range(4):
        entry = 0x80 + index * 48
        relative = len(image) - base
        struct.pack_into('>3I18H', image, entry, relative | 0x01000000, 0, 0,
                         2, 2, 0, 0, 0, 0, 1, 0, 1, 7, 1, 0xffff, 0xffff, 0, 0, 0, 0, 0)
        raw = bytes([0, 1, 1, 0]) + bytes.fromhex('f801 07c1') + bytes(508)
        compressed = zlib.compress(raw)
        image.extend(struct.pack('>2I', len(raw), len(compressed)))
        image.extend(compressed)
        image.extend(bytes(-len(image) % 4))
    return image


def test_texture_catalog_requires_loader_address_and_complete_members():
    image = _image()
    assets = deflate_catalog.regions(image)
    assert len(assets) == 4
    result = preview(image, assets[0], {})
    assert result['details']['format'] == 'ci8'
    assert result['details']['width'] == result['details']['height'] == 2
    png = base64.b64decode(result['data_url'].split(',', 1)[1])
    length, = struct.unpack_from('>I', png, 33)
    assert zlib.decompress(png[41:41 + length]) == bytes.fromhex(
        '00 ff0000ff 00ff00ff 00 00ff00ff ff0000ff')

    altered = bytearray(image)
    altered[assets[0]['offset'] + 3] ^= 1
    assert deflate_catalog.unpack(altered, assets[0]['offset']) is None
    with pytest.raises(AssetError, match='catalog texture changed'):
        preview(altered, assets[0], {})
    altered[0] = 0
    assert not deflate_catalog.regions(altered)

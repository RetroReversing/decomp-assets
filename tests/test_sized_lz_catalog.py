"""Synthetic cartridge texture directory and bounded LZ references."""

import struct

from decompassets.n64 import preview, sized_lz_catalog


def _encode(data):
    blocks = (data[i:i + 8] for i in range(0, len(data), 8))
    return struct.pack('<I', len(data)) + b''.join(b'\0' + block for block in blocks)


def _image():
    row = struct.pack('>8H', 6, 2, 2, 2, 0, 0, 0, 0)
    row += bytes.fromhex('f801 07c1') + bytes(28) + bytes([0x01] * 6) + bytes(2)
    packed = _encode(struct.pack('>2I', 8, 0) + row)
    image = bytearray(0x210)
    for i in range(3):
        at = len(image)
        struct.pack_into('>2I', image, 0x80 + i * 8, at, at - 0x200)
        image.extend(packed)
        image.extend(bytes(-len(image) % 16))
    return image


def test_declared_lz_size_supports_overlapping_copies():
    packed = bytes.fromhex('08000000 20 4142 3001')
    assert sized_lz_catalog.unpack(packed, 0, len(packed)) == (len(packed), b'ABABABAB')
    assert sized_lz_catalog.unpack(packed, 0, len(packed) - 1) is None
    assert sized_lz_catalog.unpack(packed[:-1] + b'\x02', 0, len(packed)) is None


def test_paired_offsets_validate_texture_layout_and_alignment():
    image = _image()
    assets = sized_lz_catalog.regions(image)
    assert len(assets) == 3
    result = preview(image, assets[0], {'texture': 0})
    assert result['media'] == 'image'
    assert result['details']['format'] == 'ci4'
    assert (result['details']['width'], result['details']['height']) == (6, 2)
    image[0x87] ^= 1
    assert not sized_lz_catalog.regions(image)

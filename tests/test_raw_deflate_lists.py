"""Synthetic native raw-deflate archive and mapped F3DEX previews."""

import struct
import zlib

from decompassets.n64 import preview, raw_deflate_lists


def _member():
    member = bytearray(0xa0)
    struct.pack_into('>12I', member, 0, 3, 1, 0xa0, 0x60, 0, 0, 0, 48, 0, 0, 0, 0)
    member[48:52] = bytes.fromhex('f801 07c1')
    member[80:96] = bytes([0x01] * 16)
    for i, v in enumerate(((0, 0, 0), (4, 0, 0), (0, 4, 0))):
        struct.pack_into('>3h', member, 0x60 + i * 16, *v)
    commands = (
        (0xfd100000, 0x04000000), (0xe8000000, 0), (0xf5000100, 0x07000000),
        (0xe6000000, 0), (0xf0000000, 0x0703c000), (0xfd500000, 0x04000020), (0xf5500000, 0x07000000),
        (0xe6000000, 0), (0xf3000000, 0x07007000), (0xe7000000, 0), (0xf5400200, 0),
        (0xf2000000, 0x0003c004), (0x04000c3f, 0x03000000), (0xbf000000, 0x00000204), (0xb8000000, 0),
    )
    member.extend(b''.join(struct.pack('>2I', *command) for command in commands))
    return member


def _archive_image(unpacked, image, directory):
    encoder = zlib.compressobj(wbits=-15)
    packed = encoder.compress(unpacked) + encoder.flush()
    packed = packed.ljust((len(packed) + 15) & ~15, b'\0')
    for row in range(4):
        start = len(image)
        image.extend(packed)
        struct.pack_into('>4I', image, directory + row * 16, 0x80102000, 0x400, len(image), start)
    return image


def test_raw_deflate_members_have_local_palette_and_geometry():
    unpacked = bytes.fromhex('aaaa0001 00000010') + bytes(8) + _member()
    image = _archive_image(unpacked, bytearray(0x200), 0x80)
    items = raw_deflate_lists.regions(image)
    assert len(items) == 8
    texture, model = items[:2]
    rendered = preview(image, texture, {})
    assert rendered['media'] == 'image' and rendered['details']['format'] == 'ci4'
    assert (rendered['details']['width'], rendered['details']['height']) == (16, 2)
    rendered = preview(image, model, {})
    assert rendered['surfaces'][0]['indices'] == (0, 1, 2)
    assert rendered['vertices'] == [(0, 0, 0), (4, 0, 0), (0, 4, 0)]
    image[0x80:0x90] = bytes(16)
    assert raw_deflate_lists.regions(image) == []

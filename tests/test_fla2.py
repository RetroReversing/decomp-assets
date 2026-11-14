"""FLA2-packed texture banks: homemade data only."""
import base64
import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import fla2

from .test_rom_assets import pixels

RED, GREEN = bytes.fromhex('f801'), bytes.fromhex('07c1')


def pack(raw, back=None):
    """Literals in groups of eight, one run (at, distance, length) if given, then the end marker."""
    items, at = [], 0
    while at < len(raw):
        if back and at == back[0]:
            items.append((1, bytes([((back[1] >> 4) & 0xF0) | (back[2] - 2), back[1] & 0xFF])));at += back[2]
        else:items.append((0, raw[at:at+1]));at += 1
    items.append((1, b'\0\0'))
    out = b'FLA2' + struct.pack('<I', len(raw))
    for group in range(0, len(items), 8):
        chunk = items[group:group+8]
        out += bytes([sum(bit << (7 - k) for k, (bit, _) in enumerate(chunk))]) + b''.join(data for _, data in chunk)
    return out


def texture(width, height, texel, colour, pixels_, palette=b''):
    length = 36 + len(pixels_) + len(palette)
    return struct.pack('>IBBHhhHHHHIHHII', 1, 0, 0, 0, 0, 0, width, height, 0, 0, length, colour, texel, 0,
                       36 + len(pixels_) if palette else 0) + pixels_ + palette


def bank(textures):
    return struct.pack('>I', len(textures)) + b''.join(textures) + b'one\0two\0'


def test_fla2_unpacks_literals_and_runs():
    raw = bytes(range(10)) * 3
    assert fla2.unpack(pack(raw, (10, 10, 10))) == raw
    with pytest.raises(AssetError):fla2.unpack(pack(raw)[:-3])
    with pytest.raises(AssetError):fla2.unpack(b'FLA2' + struct.pack('<I', 5) + b'\x80\0\0')   # ends before its size


def test_texture_banks_are_found_and_previewed():
    raw = bank([texture(4, 2, 0, 0, bytes([0x01, 0x10] * 2), RED + GREEN),
                texture(2, 1, 2, 0, GREEN + RED), texture(1, 1, 2, 3, bytes([0x80, 0xFF]))])
    image = bytes(32) + pack(raw) + bytes(16) + pack(b'not a bank' * 4)
    found = fla2.regions(image)
    assert len(found) == 1 and found[0]['offset'] == 32 and found[0]['size'] == len(pack(raw))
    assert [t['preview_settings']['format'] for t in found[0]['textures']] == ['ci4', 'rgba5551-be', 'ia16']
    assert [a['layout'] for a in n64.regions(image) if a.get('layout') == 'fla2-texbank'] == ['fla2-texbank']
    shown = pixels(base64.b64decode(n64.preview(image, found[0], {'texture': 0})['data_url'].split(',')[1]))
    assert shown[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])
    grey = pixels(base64.b64decode(n64.preview(image, found[0], {'texture': 2})['data_url'].split(',')[1]))
    assert grey == bytes([0x80, 0x80, 0x80, 0xFF])


def test_banks_whose_textures_do_not_fit_are_left_out():
    assert fla2.textures(bank([texture(64, 64, 2, 0, bytes(8))])) is None        # texels past its length
    assert fla2.textures(bank([texture(4, 2, 0, 0, bytes(4))])) is None           # indexed with no palette

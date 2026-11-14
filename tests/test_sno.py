"""Sno packing and its texture sheets: homemade data only."""
import base64
import struct

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import sno

from .test_rom_assets import pixels

RED, GREEN = bytes.fromhex('f801'), bytes.fromhex('07c1')


def pack(raw):
    return b''.join(bytes([0, value]) for value in raw)


def sheet(entries, palettes, texels):
    """entries: (texture offset, palette, width, height, format); offsets count from the sheet's start."""
    head = struct.pack('>II', 0, len(entries))
    head += b''.join(struct.pack('>I6H', o, p, w, h, 0, f, 0) for o, p, w, h, f in entries)
    return head + palettes + texels


def test_sno_unpacks_literals_and_runs():
    assert sno.unpack(b'\0\x01\0\x02' + bytes([0x30, 0x02]), 5) == bytes([1, 2, 1, 2, 1])
    with pytest.raises(AssetError):sno.unpack(b'\0\x01', 3)
    with pytest.raises(AssetError):sno.unpack(bytes([0x31, 0x05]), 3)          # refers back before the start


def test_sheet_textures_read_with_their_palettes():
    palettes = (RED + GREEN + RED*14) + (GREEN + RED*15)
    base = 8 + 16*2 + len(palettes)
    data = sheet([(base, 0, 4, 2, 0), (base + 4, 1, 2, 2, 0)], palettes, bytes([0x01, 0x10]*2) + bytes([0x00, 0x00]))
    items = sno.sheet(sno.unpack(pack(data), len(data)))
    assert [(i['preview_settings']['format'], i['preview_settings']['palette_offset']) for i in items] == [('ci4', 40), ('ci4', 72)]
    shown = pixels(base64.b64decode(sno.preview(data, items[0])['data_url'].split(',')[1]))
    assert shown[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])
    one = 8 + 16 + len(palettes)
    assert sno.sheet(sheet([(one, 0, 64, 64, 0)], palettes, bytes(8))) is None           # texels past the end
    assert sno.sheet(sheet([(one, 0, 4, 2, 7)], palettes, bytes(8))) is None              # an unknown format
    assert sno.sheet(sheet([(one, 0, 4, 2, 7)], palettes, bytes(8)), indexed_only=True)   # course tables are CI4

"""Sno, the packing a snowboarding sequel uses, and the texture sheets it packs.

Sno has no header: a stream of byte pairs, (0, byte) a literal, else a run (count = high nibble of the first,
distance = the low nibble × 256 + the second). Where a stream starts and how long it unpacks come from the game's
code, or from a project that has written them down (a decompilation's splat config, say), so it is read only where
the caller knows both: `unpack(data, size)`. Nothing scans a cartridge for it.

Its texture sheets (sprite sheets and course texture tables) unpack to a header (a texture base and a count),
16-byte entries (texture offset, palette number, width, height, a palette table number, a format: 0 CI4, 1 CI8;
course tables are all CI4), then palette slots of 32 bytes (16 RGBA16 colours; a CI8 palette takes 16 slots).
"""
from __future__ import annotations

import struct

from .. import formats as asset_formats
from ..formats import AssetError

MAX_OUTPUT = 4 * 1024 * 1024
SLOT = 0x20


def unpack(data, size):
    if not 0 < size <= MAX_OUTPUT:raise AssetError('Choose an unpacked size up to 4 MiB.')
    out, at = bytearray(), 0
    while len(out) < size:
        if at + 1 >= len(data):raise AssetError('The sno stream ends before its size. Check the declared size.')
        first, second = data[at], data[at+1];at += 2
        if not first:
            out.append(second);continue
        count, distance = first >> 4, ((first & 0x0F) << 8) | second
        if not count or not distance or distance > len(out):raise AssetError('The sno stream is not valid here. Check the declared start.')
        for _ in range(count):
            out.append(out[-distance])
            if len(out) >= size:break
    return bytes(out)


def sheet(data, *, indexed_only=False):
    """A sprite sheet's or course texture table's textures as preview items relative to `data`, or None.

    `indexed_only` reads every entry as CI4 (course tables carry no format)."""
    if len(data) < 8:return None
    count = int.from_bytes(data[4:8], 'big')
    palettes = 8 + 16*count
    if not 0 < count <= 4096 or palettes > len(data):return None
    items = []
    for index in range(count):
        offset, palette, width, height, table, kind, _pad = struct.unpack_from('>I6H', data, 8 + 16*index)
        if indexed_only:kind = 0
        if table or kind not in (0, 1) or not 0 < width <= 1024 or not 0 < height <= 1024:return None
        fmt, colours = ('ci4', 16) if kind == 0 else ('ci8', 256)
        size = (width*height + 1)//2 if kind == 0 else width*height
        start = palettes + SLOT*palette
        if offset + size > len(data) or start + 2*colours > len(data):return None
        settings = dict(format=fmt, width=width, height=height, offset=offset, palette_offset=start, palette_format='rgba5551-be')
        items.append(dict(preview_settings=settings, frames=1, palettes=1, frame_offsets=[offset], palette_offsets=[start],
                          palette_entries=[colours], levels=[dict(width=width, height=height, offset=0)]))
    return items


def preview(data, item):
    """One sheet texture from the unpacked sheet."""
    return asset_formats.preview(data, item['preview_settings'])

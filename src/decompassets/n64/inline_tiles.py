"""Tiles whose native headers carry RDP format, dimensions and RAM pointers."""

import re
import struct
from dataclasses import dataclass

_END = re.compile(rb'\xdf\0{7}')
_HEADER = struct.Struct('>4H2I')
_FORMATS = {(0, 2): 'rgba5551-be', (2, 0): 'ci4', (2, 1): 'ci8', (3, 1): 'ia8'}
_SIZE = _HEADER.size+8


@dataclass(frozen=True)
class Tile:
    start: int
    end: int
    displacement: int
    settings: dict


def _tile(image, offset):
    width, height, fmt, depth, palette, pixels = _HEADER.unpack_from(image, offset)
    if (fmt, depth) not in _FORMATS or not 4 <= width <= 1024 or not 4 <= height <= 1024:
        return None
    if not 0x80000000 <= pixels < 0x80800000 or pixels%8:
        return None
    start = offset+_SIZE
    end = start+(width*height*(4 << depth)+7)//8
    if end > len(image):
        return None
    settings = dict(offset=start, format=_FORMATS[fmt, depth], width=width, height=height)
    if fmt == 2:
        palette_size = (16 << (depth*4))*2
        at = start+palette-pixels
        if (not 0x80000000 <= palette < 0x80800000 or palette%8 or not 0 <= at <= len(image)-palette_size
                or (at < end and offset < at+palette_size) or not any(image[at:at+palette_size])):
            return None
        settings.update(palette_offset=at, palette_format='rgba5551-be')
    elif palette:
        return None
    return Tile(start, end, pixels-start, settings)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """Require adjacent tiles whose computed extents use the same loaded-bank mapping."""
    tiles = {}
    for marker in _END.finditer(image):
        offset = marker.start()-_HEADER.size
        if offset < 0 or offset%8:
            continue
        check()
        if tile := _tile(image, offset):
            tiles[offset] = tile
    verified = set()
    for offset, tile in tiles.items():
        following = (tile.end+7)&~7
        next_tile = tiles.get(following)
        if next_tile and tile.displacement == next_tile.displacement and not any(image[tile.end:following]):
            verified.update((offset, following))
    return [dict(offset=tile.start, size=tile.end-tile.start, kind='image', media='image',
                 layout='inline-rdp-tile', confidence='validated', label='Inline RDP tile',
                 reason='Adjacent headers agree on the loaded-bank mapping, pixel extent and RDP tile format.',
                 preview_settings=dict(source='rom', **tile.settings))
            for offset in sorted(verified) for tile in (tiles[offset],)]

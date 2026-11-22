"""Bounded N64 IWAD sprite directories and their palette-indexed graphics."""

import re
import struct

from .. import formats
from . import iwad_huffman

LAYOUT = 'iwad-sprite'
TEXTURE = 'iwad-texture'
_LIMIT = 4 * 1024 * 1024
_ENTRY = struct.Struct('<II8s')


def archives(image, check):
    for match in re.finditer(b'IWAD', image):
        base = match.start()
        if base % 4 or base + 12 > len(image):
            continue
        count, directory = struct.unpack_from('<II', image, base + 4)
        if not 8 <= count <= 8192 or directory < 12 or base + directory + count * 16 > len(image):
            continue
        check()
        rows = []
        for i in range(count):
            offset, size, rawname = _ENTRY.unpack_from(image, base + directory + i * 16)
            name = bytes([rawname[0] & 127]) + rawname[1:]
            name = name.split(b'\0', 1)[0]
            if (not name or any(c < 32 or c > 126 for c in name) or offset < 12
                    or offset > directory or size > _LIMIT or rows and offset < rows[-1][0]):
                break
            rows.append((offset, size, name.decode('ascii'), bool(rawname[0] & 128)))
        else:
            names = [row[2] for row in rows]
            if all(names.count(marker) == 1 for marker in ('S_START', 'S_END', 'T_START', 'T_END')):
                yield base, directory, rows


def jaguar(data, expected):
    if not 0 < expected <= _LIMIT:
        return None
    out = bytearray()
    at = 0
    while at < len(data):
        flags = data[at]
        at += 1
        for _ in range(8):
            if flags & 1:
                if at + 2 > len(data):
                    return None
                a, b = data[at:at+2]
                at += 2
                distance, count = (a << 4 | b >> 4) + 1, (b & 15) + 1
                if count == 1:
                    return bytes(out) if len(out) == expected else None
                if distance > len(out) or len(out) + count > expected:
                    return None
                for _ in range(count):
                    out.append(out[-distance])
            else:
                if at >= len(data) or len(out) == expected:
                    return None
                out.append(data[at])
                at += 1
            flags >>= 1
    return None


def member(image, base, directory, rows, index):
    offset, size, _, compressed = rows[index]
    stop = rows[index + 1][0] if index + 1 < len(rows) else directory
    if stop < offset or base + stop > len(image):
        return None
    raw = image[base+offset:base+stop]
    if compressed:
        return jaguar(raw, size)
    return bytes(raw[:size]) if len(raw) >= size else None


def _sprite(data, palette=None):
    if not data or len(data) < 16:
        return None
    tiles, encoding, stored, _, _, width, height, tileheight = struct.unpack_from('>8h', data)
    if not 0 < tiles <= 128 or not 0 < width <= 512 or not 0 < height <= 512 or not 0 < tileheight <= 512:
        return None
    if not (tiles - 1) * tileheight < height <= tiles * tileheight:
        return None
    if encoding == -1:
        bits, padded = 8, (width + 7) & ~7
        if not palette or len(palette) != 520:
            return None
        palette = palette[8:]
    elif encoding >= 0:
        bits, padded = 4, (width + 15) & ~15
        if stored < padded * height // 2 or 16 + stored + 32 > len(data):
            return None
        palette = data[16+stored:16+stored+32]
    else:
        return None
    row = padded * bits // 8
    if 16 + row * height > len(data):
        return None
    pixels = bytearray(data[16:16+row*height])
    for y in range(height):
        if (y % tileheight) % 2:
            for x in range(0, row, 8):
                p = y * row + x
                pixels[p:p+8] = pixels[p+4:p+8] + pixels[p:p+4]
    return bytes(pixels), bytes(palette), padded, height, bits



def _texture(data):
    if not data or len(data) < 8:
        return None
    _, palettes, xshift, yshift = struct.unpack_from('>4H', data)
    if not 1 <= palettes <= 16 or not 4 <= xshift <= 9 or not 1 <= yshift <= 9:
        return None
    width, height = 1 << xshift, 1 << yshift
    row = width // 2
    size = (row * height + 7) & ~7
    if 8 + size + palettes * 32 > len(data):
        return None
    pixels = bytearray(data[8:8+row*height])
    for y in range(1, height, 2):
        for x in range(0, row, 8):
            p = y * row + x
            pixels[p:p+8] = pixels[p+4:p+8] + pixels[p:p+4]
    return bytes(pixels), data[8+size:8+size+palettes*32], width, height, palettes


def _texture_member(image, base, directory, rows, index, check):
    offset, size, _, compressed = rows[index]
    stop = rows[index + 1][0] if index + 1 < len(rows) else directory
    if stop < offset or base + stop > len(image):
        return None
    raw = image[base+offset:base+stop]
    if compressed:
        return iwad_huffman.unpack(raw, size, check)
    return bytes(raw[:size]) if len(raw) >= size else None

def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, directory, rows in archives(image, check):
        names = {row[2]: i for i, row in enumerate(rows)}
        for i in range(names['S_START'] + 1, names['S_END']):
            if i % 32 == 0:
                check()
            offset, _, name, _ = rows[i]
            if name.startswith('PAL'):
                continue
            data = member(image, base, directory, rows, i)
            palette_index = names.get('PAL' + name[:4] + '0')
            palette = member(image, base, directory, rows, palette_index) if palette_index is not None else None
            parsed = _sprite(data, palette)
            if not parsed:
                continue
            _, _, width, height, bits = parsed
            end = rows[i+1][0]
            result.append(dict(offset=base+offset, size=end-offset, kind='image', layout=LAYOUT,
                               confidence='validated', directory=base, index=i, palette_index=palette_index,
                               label=f'{name} · {width}×{height} sprite', width=width, height=height,
                               reason='The IWAD directory, bounded decompression, sprite header and palette agree.',
                               preview_settings=dict(source='rom', format='auto', offset=base+offset)))
        for i in range(names['T_START'] + 1, names['T_END']):
            if i % 16 == 0:
                check()
            offset, _, name, _ = rows[i]
            data = _texture_member(image, base, directory, rows, i, check)
            parsed = _texture(data)
            if not parsed:
                continue
            _, _, width, height, palettes = parsed
            end = rows[i+1][0]
            result.append(dict(offset=base+offset, size=end-offset, kind='image', layout=TEXTURE,
                               confidence='validated', directory=base, index=i, palettes=palettes, frames=1,
                               label=f'{name} · {width}×{height} texture', width=width, height=height,
                               reason='The IWAD member, texture dimensions and palette extents agree.',
                               preview_settings=dict(source='rom', format='auto', offset=base+offset)))
    return result


def preview(image, asset, selection):
    for base, directory, rows in archives(image, lambda: None):
        if base != asset['directory'] or not 0 <= asset['index'] < len(rows):
            continue
        index = asset['index']
        if base + rows[index][0] != asset['offset']:
            break
        if asset['layout'] == TEXTURE:
            data = _texture_member(image, base, directory, rows, index, lambda: None)
            parsed = _texture(data)
            if not parsed:
                break
            pixels, palettes, width, height, count = parsed
            palette = formats.integer(selection.get('palette', 0), 'Palette', 0, count - 1)
            colors = palettes[palette*32:(palette+1)*32]
            result = formats.preview(pixels + colors, dict(source='rom', offset=0, format='ci4', width=width,
                                     height=height, palette_offset=len(pixels), palette_format='rgba5551-be'))
            result['details']['note'] = asset['reason']
            result['settings'] = dict(asset['preview_settings'], palette=palette)
            return result
        data = member(image, base, directory, rows, index)
        palette_index = asset['palette_index']
        palette = member(image, base, directory, rows, palette_index) if palette_index is not None else None
        parsed = _sprite(data, palette)
        if not parsed:
            break
        pixels, palette, width, height, bits = parsed
        result = formats.preview(pixels + palette, dict(source='rom', offset=0, format='ci4' if bits == 4 else 'ci8',
                                 width=width, height=height, palette_offset=len(pixels), palette_format='rgba5551-be'))
        result['details']['note'] = asset['reason']
        result['settings'] = asset['preview_settings']
        return result
    raise formats.AssetError('The sprite archive changed. Scan ROM Explorer again.')

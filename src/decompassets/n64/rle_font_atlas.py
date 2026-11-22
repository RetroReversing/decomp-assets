"""Indexed RLE font atlases with independently described glyph dimensions."""

import struct
from collections import defaultdict

from .. import formats

LAYOUT = 'rle-font-atlas'
_LIMIT = 4 * 1024 * 1024


def _rle(data, expected):
    if not 0 < expected <= _LIMIT:
        return None
    out, cursor = bytearray(), 0
    while len(out) < expected and cursor < len(data):
        control = data[cursor]
        cursor += 1
        if control & 0x80:
            length = (control & 0x7f) + 3
            if cursor >= len(data) or len(out) + length > expected:
                return None
            out.extend(bytes([data[cursor]]) * length)
            cursor += 1
        else:
            length = control + 1
            if cursor + length > len(data) or len(out) + length > expected:
                return None
            out.extend(data[cursor:cursor + length])
            cursor += length
    return (bytes(out), cursor) if len(out) == expected else None


def _directories(image, check):
    limit = min(len(image), 0x200000)
    for base in range(0, limit - 140, 4):
        if base % 0x10000 == 0:
            check()
        count = struct.unpack_from('>I', image, base)[0]
        table_size = 4 + 8 * count
        if not 16 <= count <= 65535 or base + table_size > len(image):
            continue
        first = struct.unpack_from('>I', image, base + 8)[0] & 0xffffff
        if first != table_size:
            continue
        rows = []
        for i in range(count):
            size, packed = struct.unpack_from('>II', image, base + 4 + 8 * i)
            offset = packed & 0xffffff
            if offset < table_size or base + offset >= len(image):
                break
            rows.append((size, packed))
        if len(rows) != count:
            continue
        # Aliases can move back in the table, but the physical archive is
        # overwhelmingly ordered and the first entries fill their extents.
        if sum((a[1] & 0xffffff) > (b[1] & 0xffffff) for a, b in zip(rows, rows[1:])) > count // 100:
            continue
        if any((rows[i+1][1] & 0xffffff) - (rows[i][1] & 0xffffff) != rows[i][0] & 0xffffff
               for i in range(8)):
            continue
        yield base, rows


def _glyph_tables(image, check):
    found = defaultdict(list)
    for start in range(0, len(image) - 128, 4):
        if start % 0x10000 == 0:
            check()
        char, width, height, flags, offset = struct.unpack_from('>4BI', image, start)
        if not 32 <= char <= 126 or not 1 <= width <= 64 or not 1 <= height <= 64 or flags or offset:
            continue
        items, seen, at, end = [], set(), start, 0
        while at + 8 <= len(image) and len(items) < 512:
            char, width, height, flags, offset = struct.unpack_from('>4BI', image, at)
            if (not 32 <= char <= 126 or char in seen or not 1 <= width <= 64 or not 1 <= height <= 64
                    or flags or offset != end):
                break
            seen.add(char)
            stride = (width + 7) & ~7
            items.append(dict(label=f'{chr(char)} · {width}×{height}', width=stride, height=height,
                              offset=offset, frames=1, palettes=1,
                              preview_settings=dict(format='ci8', width=stride, height=height, offset=offset),
                              levels=[dict(width=stride, height=height, offset=0)]))
            end += stride * height
            at += 8
        if len(items) >= 16 and end <= _LIMIT:
            found[end].append((start, items))
    return found


def regions(image, *, check=lambda: None, progress=lambda _: None):
    directories = list(_directories(image, check))
    if not directories:
        return []
    glyphs = _glyph_tables(image, check)
    result = []
    for base, rows in directories:
        for i, (size, packed) in enumerate(rows[:-1]):
            if size >> 24 != 0x82 or len(glyphs.get(size & 0xffffff, ())) != 1:
                continue
            end = base + (rows[i+1][1] & 0xffffff)
            start = base + (packed & 0xffffff)
            if not 0 < end-start <= _LIMIT or (end-start+255)//256 != packed >> 24:
                continue
            palette = None
            # Consecutive compressed atlases can share the last preceding palette.
            for previous in range(i-1, max(-1, i-5), -1):
                old_size, old = rows[previous]
                if old_size == 512:
                    palette = base + (old & 0xffffff)
                    break
                if old_size >> 24 != 0x82:
                    break
            if palette is None or palette + 512 > len(image):
                continue
            decoded = _rle(image[start:end], size & 0xffffff)
            if not decoded or end-start-decoded[1] > 3:
                continue
            table, items = glyphs[size & 0xffffff][0]
            result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                               confidence='validated', label=f'{len(items)} indexed font textures',
                               textures=items, texture_count=len(items), glyph_table=table,
                               decoded_size=size & 0xffffff, palette_offset=palette, frames=1, palettes=1,
                               levels=items[0]['levels'], preview_settings=dict(source='rom', format='auto', offset=start),
                               reason='A checked resource directory, palette and glyph table agree on every decoded extent.'))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    start, end = asset['offset'], asset['offset'] + asset['size']
    palette = asset['palette_offset']
    if not 0 <= start < end <= len(image) or not 0 <= palette <= len(image) - 512:
        raise formats.AssetError('The compressed font changed. Rescan ROM Explorer.')
    decoded = _rle(image[start:end], asset['decoded_size'])
    if not decoded or end-start-decoded[1] > 3:
        raise formats.AssetError('The compressed font changed. Rescan ROM Explorer.')
    item = asset['textures'][index]
    at = asset['glyph_table'] + 8 * index
    if not 0 <= at <= len(image) - 8:
        raise formats.AssetError('The font descriptors changed. Rescan ROM Explorer.')
    char, width, height, flags, offset = struct.unpack_from('>4BI', image, at)
    if (flags or not 32 <= char <= 126 or (width + 7) & ~7 != item['width']
            or height != item['height'] or offset != item['offset']):
        raise formats.AssetError('The font descriptors changed. Rescan ROM Explorer.')
    data = decoded[0] + image[palette:palette + 512]
    settings = dict(format='ci8', width=item['width'], height=item['height'], offset=item['offset'],
                    palette_offset=len(decoded[0]), palette_format='rgba5551-be')
    result = formats.preview(data, settings)
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
    return result

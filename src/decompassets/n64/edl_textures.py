"""Texture groups in consecutive compressed resource components."""

import struct

from .. import formats
from . import edl


def _group(data, start, image_size, palette_size):
    count = struct.unpack_from('>H', data, start)[0]
    if not 4 <= count <= 2048:
        return None
    pos, total, rows = start + 2, 0, []
    while total < count:
        if pos + 10 > len(data):
            return None
        offset, width, height, palette, children = struct.unpack_from('>5H', data, pos)
        pos += 10
        if not (1 <= width <= 256 and 1 <= height <= 256 and 1 <= children <= count - total
                and offset * 8 + width * height <= image_size and palette + 512 <= palette_size):
            return None
        if pos + children * 9 > len(data):
            return None
        flags = []
        for _ in range(children):
            if pos + 4 > len(data):
                return None
            flag = struct.unpack_from('>I', data, pos)[0]
            pos += 4 + (4 if flag & 1 else 3) * (1 if flag & 2 else 2) + 2
            if pos > len(data):
                return None
            flags.append(flag)
        if all(flag & 0xc0000008 == 0x40000000 for flag in flags):
            rows.append((offset * 8, width, height, palette))
        total += children
    return (rows, pos) if len(rows) >= 2 else None


def regions(image, blocks, check):
    result = []
    for at, (_, stored, decoded) in blocks.items():
        next_at = (at + stored + 15) & ~15
        if next_at not in blocks or decoded > 1024 * 1024:
            continue
        _, image_stored, image_size = blocks[next_at]
        tail = (next_at + image_stored + 15) & ~15
        if tail not in blocks:
            continue
        palette = (tail + blocks[tail][1] + 15) & ~15
        end = min((p for p in blocks if p > palette), default=len(image))
        if end - palette < 512:
            continue
        try:
            data = edl.unpack(image, at)
            edl.unpack(image, next_at)
            edl.unpack(image, tail)
        except formats.AssetError:
            continue
        check()
        pos = 0
        rows = []
        while pos + 12 <= len(data):
            if pos % 4096 == 0:
                check()
            found = _group(data, pos, image_size, end - palette)
            if found:
                group, pos = found
                rows.extend(group)
            else:
                pos += 2
        rows = list(dict.fromkeys(rows))
        if not rows:
            continue
        width, height = rows[0][1:3]
        result.append(dict(offset=at, size=stored, label='EDL compressed texture groups',
                           layout='eurocom-edl-textures', kind='image', media='image',
                           confidence='validated', reason='Adjacent compressed components and bounded texture groups agree.',
                           image_offset=next_at, palette_offset=palette, texture_rows=rows,
                           texture_count=len(rows), frames=1, palettes=1,
                           texture_groups=[(0, list(range(len(rows))))],
                           preview_settings=dict(source='rom', format='auto', offset=at,
                                                 width=width, height=height, display_format='ci8')))
    return result


def preview(image, asset, selection):
    slot = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['texture_rows']) - 1)
    offset, width, height, pal = asset['texture_rows'][slot]
    raw = edl.unpack(image, asset['image_offset'])[offset:offset + width * height]
    palette_at = asset['palette_offset'] + pal
    palette = image[palette_at:palette_at + 512]
    if len(raw) != width * height or len(palette) != 512:
        raise formats.AssetError('The texture data changed. Rescan ROM Explorer.')
    colors = formats._rgba(palette, 'rgba5551-be', 256)
    pixels = b''.join(colors[4 * i:4 * i + 4] for i in raw)
    result = formats.preview(pixels, dict(format='rgba8888', width=width, height=height, offset=0))
    result['details'].update(format='CI8', texture=slot, note='Stored palette preview.')
    result['settings'] = dict(format='auto', source='rom', offset=asset['offset'], texture=slot)
    return result

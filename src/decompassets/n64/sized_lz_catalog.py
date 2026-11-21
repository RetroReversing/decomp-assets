"""Cartridge texture directories with paired offsets and output-sized LZ streams."""

import struct
from itertools import pairwise

from .. import formats

TEXTURE = 'sized-lz-catalog-textures'
_LIMIT = 4 * 1024 * 1024
_PAIR = struct.Struct('>2I')
_TEXTURE = struct.Struct('>8H')


def directories(image, check):
    limit, cursor = min(0x200000, len(image)), 0
    for at in range(0, limit - _PAIR.size, 4):
        if at % 0x10000 == 0:
            check()
        if at < cursor:
            continue
        offset, relative = _PAIR.unpack_from(image, at)
        base = offset - relative
        if not at + _PAIR.size < base <= offset < len(image) or (base | relative) % 16:
            continue
        offsets = []
        while at + len(offsets) * _PAIR.size + _PAIR.size <= limit and len(offsets) < 256:
            value, relative = _PAIR.unpack_from(image, at + len(offsets) * _PAIR.size)
            if (value - relative != base or relative % 16 or not offset <= value < len(image)
                    or offsets and offsets[-1] >= value):
                break
            offsets.append(value)
        cursor = at + len(offsets) * _PAIR.size
        if len(offsets) >= 3:
            yield tuple(pairwise((*offsets, len(image))))


def unpack(image, start, end, check=lambda: None):
    """Decode MSB-first literals and overlapping matches to the declared size."""
    if not 0 <= start < start + 4 < end <= len(image):
        return None
    size = int.from_bytes(image[start:start + 4], 'little')
    if not 0 < size <= _LIMIT:
        return None
    data = bytearray()
    cursor, checkpoint = start + 4, 0
    while cursor < end and len(data) < size:
        if len(data) >= checkpoint:
            check()
            checkpoint = len(data) + 4096
        flags = image[cursor]
        cursor += 1
        for bit in range(7, -1, -1):
            if len(data) == size:
                return cursor - start, data
            if cursor == end:
                return None
            first = image[cursor]
            cursor += 1
            if not flags & (1 << bit):
                data.append(first)
                continue
            if cursor == end:
                return None
            count = (first >> 4) + 3
            distance = ((first & 15) << 8 | image[cursor]) + 1
            cursor += 1
            if distance > len(data) or len(data) + count > size:
                return None
            for _ in range(count):
                data.append(data[-distance])
    if len(data) == size:
        return cursor - start, data


def member_spans(data):
    first = int.from_bytes(data[:4], 'big')
    if not 8 <= first <= min(len(data), 4 * 257) or first % 4 or any(data[first - 4:first]):
        return []
    offsets = struct.unpack_from(f'>{first // 4 - 1}I', data)
    spans = list(pairwise((*offsets, len(data))))
    return spans if all(start % 4 == 0 and start < end for start, end in spans) else []


def textures(data):
    result = []
    for start, end in member_spans(data):
        if end - start < _TEXTURE.size:
            return []
        width, height, packing, colors, *reserved = _TEXTURE.unpack_from(data, start)
        if not (packing in (1, 2) and 0 < width <= 512 and 0 < height <= 512 and width % packing == 0):
            return []
        capacity = 256 if packing == 1 else 16
        palette = start + _TEXTURE.size
        pixels = palette + capacity * 2
        pixel_end = pixels + width * height // packing
        if (not 1 <= colors <= capacity or any(reserved)
                or end != (pixel_end + 3) & ~3 or any(data[pixel_end:end])):
            return []
        fmt = 'ci8' if packing == 1 else 'ci4'
        result.append(dict(label=f'{fmt.upper()} {width}×{height}', frames=1, palettes=1,
                           levels=[dict(width=width, height=height, offset=0)],
                           preview_settings=dict(format=fmt, width=width, height=height, offset=pixels,
                                                 palette_offset=palette, palette_format='rgba5551-be')))
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for spans in directories(image, check):
        rows = []
        for offset, end in spans:
            if (decoded := unpack(image, offset, end, check)) and (items := textures(decoded[1])):
                rows.append(dict(offset=offset, size=decoded[0], kind='image', layout=TEXTURE,
                                 confidence='validated', label=f'{len(items)} indexed textures',
                                 textures=items, texture_count=len(items), frames=1, palettes=1,
                                 levels=items[0]['levels'],
                                 reason='The decoded archive offsets and palette and pixel extents agree with each texture header.',
                                 preview_settings=dict(format='auto', source='rom', offset=offset)))
        if len(rows) >= 3:
            result.extend(rows)
    return result


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    decoded = unpack(image, offset, offset + size)
    if not decoded or decoded[0] != size or not (items := textures(decoded[1])):
        raise formats.AssetError('The compressed texture archive changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    result = formats.preview(decoded[1], items[index]['preview_settings'])
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
    return result

"""Indexed glyph tables followed by a four-bit intensity/alpha palette."""

import re
import struct
from itertools import islice

from .. import formats

LAYOUT = 'ia-font-textures'
_ROW = struct.Struct('>H5B')
_SHAPE = re.compile(rb'(?=(?:..[!-~][\x01-\x40][\x01-\x40]..){6})', re.S)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets, last = [], 0
    for hit in _SHAPE.finditer(image):
        start = hit.start()
        if start < last or start % 2:
            continue
        check()
        rows, seen, at, previous = [], set(), start, -1
        while at + _ROW.size <= len(image) and len(rows) < 95:
            offset, char, width, height, x, y = _ROW.unpack_from(image, at)
            if (offset % 8 or offset <= previous or char in seen or not 33 <= char <= 126
                    or not 1 <= width <= 64 or not 1 <= height <= 64 or x > 32 or y > 32):
                break
            if rows and offset < rows[-1][0] + (rows[-1][2] * rows[-1][3] + 1) // 2:
                break
            rows.append((offset, char, width, height))
            seen.add(char)
            previous = offset
            at += _ROW.size
        if len(rows) < 32 or image[at:at+2] != b'\0\0':
            continue
        palette = (at + 2 + 15) & ~15
        if palette + rows[-1][0] + (rows[-1][2] * rows[-1][3] + 1) // 2 > len(image):
            continue
        colors = image[palette:palette + 32]
        # The palette is transparent first, then a monotone opaque intensity ramp.
        if (len(colors) != 32 or colors[:4] != b'\0\0\0\0' or any(v != 255 for v in colors[5::2])
                or list(colors[4::2]) != sorted(colors[4::2], reverse=True)):
            continue
        textures = [dict(label=f'{chr(char)} · {width}×{height}', width=width, height=height,
                         frames=1, palettes=1, levels=[dict(width=width, height=height, offset=0)],
                         preview_settings=dict(format='ci4', width=width, height=height, offset=palette+offset))
                    for offset,char,width,height in rows]
        assets.append(dict(offset=start, size=at-start+2, label='Indexed intensity font', kind='image',
                           layout=LAYOUT, media='image', confidence='validated',
                           reason='Ordered glyph extents resolve to a bounded intensity palette and pixels.',
                           palette_offset=palette, glyphs=rows, textures=textures, texture_count=len(rows),
                           frames=1, palettes=1, preview_settings=dict(source='rom', format='auto', offset=start,
                                                                        width=rows[0][2], height=rows[0][3])))
        last = at + 2
    return assets


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['glyphs'])-1)
    offset, char, width, height = asset['glyphs'][index]
    at = asset['palette_offset']
    raw = image[at + offset:at + offset + (width * height + 1) // 2]
    palette = image[at:at + 32]
    if len(raw) != (width * height + 1) // 2 or len(palette) != 32:
        raise formats.AssetError('The font data changed. Rescan ROM Explorer.')
    colors = formats._rgba(palette, 'ia16', 16)
    indices = (v for byte in raw for v in (byte >> 4, byte & 15))
    pixels = b''.join(colors[4*i:4*i+4] for i in islice(indices, width*height))
    result = formats.preview(pixels, dict(format='rgba8888', width=width, height=height, offset=0))
    result['details'].update(format='CI4 / IA16', texture=index, glyph=chr(char),
                             note='Stored intensity palette; runtime tint may differ.')
    result['settings'] = dict(format='auto', source='rom', offset=asset['offset'], texture=index)
    return result

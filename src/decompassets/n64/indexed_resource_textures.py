"""Paletted and RGBA textures in indexed cartridge resources."""

import struct

from .. import formats
from . import rle_font_atlas

LAYOUT = 'indexed-resource-textures'
_GROUP = 128


def texture(image, base, rows, index):
    word, packed = rows[index]
    if word >> 24 != 0x40:
        return None
    offset, size = base + (packed & 0xffffff), word & 0xffffff
    if size < 8 or offset + size > len(image):
        return None
    width, height, flags, palette_id = struct.unpack_from('>BBHI', image, offset)
    width *= 4
    if not width or not height or flags & ~1:
        return None
    fmt = 'ci8' if flags & 1 else 'rgba5551-be'
    if size != 8 + width * height * (1 if flags & 1 else 2):
        return None
    palettes = []
    if flags & 1:
        if palette_id >= len(rows):
            return None
        palette_word, palette_packed = rows[palette_id]
        palette = base + (palette_packed & 0xffffff)
        length = palette_word & 0xffffff
        if palette_word >> 24 != 0x30 or length < 8 or palette + length > len(image):
            return None
        kind, count = struct.unpack_from('>II', image, palette)
        if kind != 1 or not 1 <= count <= 64 or 8 + 512 * count > length:
            return None
        palettes = [palette + 8 + 512 * i for i in range(count)]
    settings = dict(format=fmt, width=width, height=height, offset=offset+8)
    if palettes:
        settings.update(palette_offset=palettes[0], palette_format='rgba5551-be')
    return dict(label=f'{fmt} {width}×{height}', offset=offset, size=size, preview_settings=settings,
                palette_offsets=palettes, palettes=len(palettes), frames=1,
                levels=[dict(width=width, height=height, offset=0)])


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, rows in rle_font_atlas._directories(image, check):
        items = []
        for index in range(len(rows)):
            if index % 128 == 0:
                check()
            if item := texture(image, base, rows, index):
                items.append(item)
        items.sort(key=lambda item: item['offset'])
        for pos in range(0, len(items), _GROUP):
            group = items[pos:pos + _GROUP]
            start = group[0]['offset']
            end = max(item['offset'] + item['size'] for item in group)
            result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                               confidence='validated', label=f'{len(group)} indexed textures', textures=group,
                               texture_count=len(group), frames=1, palettes=group[0]['palettes'],
                               levels=group[0]['levels'], preview_settings=dict(source='rom', format='auto', offset=start),
                               reason='Resource headers give each image size and link indexed pixels to their palette.'))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures']) - 1)
    item = asset['textures'][index]
    offset, end = item['offset'], item['offset'] + item['size']
    if not 0 <= offset < end <= len(image) or end-offset < 8:
        raise formats.AssetError('The indexed texture changed. Rescan ROM Explorer.')
    width, height, flags, _ = struct.unpack_from('>BBHI', image, offset)
    settings = dict(item['preview_settings'])
    if (width * 4 != settings['width'] or height != settings['height']
            or flags != (1 if settings['format'] == 'ci8' else 0)
            or end-offset != 8 + width * 4 * height * (1 if flags else 2)):
        raise formats.AssetError('The indexed texture changed. Rescan ROM Explorer.')
    palette = formats.integer(selection.get('palette', 0), 'Palette', 0, max(0, item['palettes'] - 1))
    if item['palette_offsets']:
        settings['palette_offset'] = item['palette_offsets'][palette]
    result = formats.preview(image, settings)
    result['details'].update(texture=index, palette=palette, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=palette, mip=0)
    return result

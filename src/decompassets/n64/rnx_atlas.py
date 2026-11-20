"""Read directly stored CI4 tiles from a shared-palette graphics archive."""

import struct

from .. import formats

ROW = struct.Struct('>BBII')
TILE = struct.Struct('>BBBH')
FENCE = b'\xcd' * 6
PALETTE_SIZE = 32


def layout(data):
    if len(data) < 32 or data[4:10] != FENCE:
        return None
    start = struct.unpack_from('>I', data)[0]
    if not 30 <= start <= min(len(data) - 1, 65536) or (start - 10) % ROW.size:
        return None
    if data[start - 6:start] != FENCE:
        return None
    rows = list(ROW.iter_unpack(data[4:start - 6]))
    palette_end = rows[0][-1]
    if not start < palette_end < len(data) or (palette_end - start) % PALETTE_SIZE or rows[-1][-1] != len(data):
        return None
    result = []
    at = palette_end
    for index, (_, _, expanded, end) in enumerate(rows[1:], 1):
        if not at < end <= len(data) or end - at > expanded:
            return None
        if end - at >= TILE.size:
            mode, width, height, palette = TILE.unpack_from(data, at)
            pixels = width * height // 2
            palette_at = start + palette * PALETTE_SIZE
            if (mode == 0 and width in (8, 16, 32, 64, 128) and height in (8, 16, 32, 64, 128)
                    and end - at == TILE.size + pixels and expanded == PALETTE_SIZE + pixels
                    and palette_at + PALETTE_SIZE <= palette_end):
                settings = dict(format='ci4', width=width, height=height, offset=at + TILE.size,
                                palette_offset=palette_at, palette_format='rgba5551-be')
                result.append(dict(preview_settings=settings, frames=1, palettes=1, resource_index=index))
        at = end
    return result or None


def asset(items, offset, extent):
    settings = dict(items[0]['preview_settings'], source='decoded', block_offset=offset)
    return dict(offset=offset, size=extent, kind='image', confidence='validated', label='RNX shared-palette tiles',
                layout='rnx-ci4-atlas', textures=items, **(items[0] | {'preview_settings': settings}))


def preview(data, asset, selection):
    items = layout(data)
    if not items:
        raise formats.AssetError('The shared-palette texture archive changed. Rescan ROM Explorer.')
    selected = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    for key in ('frame', 'palette', 'mip'):
        formats.integer(selection.get(key, 0), key.capitalize(), 0, 0)
    item = items[selected]
    result = formats.preview(data, item['preview_settings'])
    result['details'].update(texture=selected, resource_index=item['resource_index'])
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=selected)
    return result

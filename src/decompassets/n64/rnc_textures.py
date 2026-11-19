"""Read RNC texture banks with a table of 16-byte pixel and palette descriptors."""

import struct

from .. import formats

RECORD_BYTES = 16


def layout(data):
    """Require the table and every tightly packed texture to cover the decoded bank."""
    if len(data) < RECORD_BYTES:
        return None
    table_end = struct.unpack_from('>I', data, 8)[0]
    if not RECORD_BYTES <= table_end < len(data) or table_end % RECORD_BYTES:
        return None
    textures = []
    cursor = table_end
    for record in range(0, table_end, RECORD_BYTES):
        mode, marker, width, height, log_width, log_height, palette, pixels = struct.unpack_from(
            '>B3sBBBBII', data, record
        )
        if mode not in (0, 1) or marker != b'\xff\xff\xff':
            return None
        if not (3 <= log_width <= 7 and 3 <= log_height <= 7):
            return None
        if (width, height) != (1 << log_width, 1 << log_height):
            return None
        palette_bytes = 0 if mode else 32
        if palette != cursor or pixels != palette + palette_bytes:
            return None
        cursor = pixels + (width * height * 4 if mode else width * height // 2)
        if cursor > len(data):
            return None
        settings = dict(format='rgba8888' if mode else 'ci4', width=width, height=height, offset=pixels)
        if palette_bytes:
            settings.update(palette_offset=palette, palette_format='rgba5551-be')
        textures.append(dict(preview_settings=settings, frames=1, palettes=int(bool(palette_bytes))))
    return textures if cursor == len(data) else None


def asset(items, offset, extent):
    settings = dict(items[0]['preview_settings'], source='decoded', block_offset=offset)
    return dict(offset=offset, size=extent, kind='image', label='RNC texture bank', confidence='validated',
                layout='rnc-sum32-texture-bank', textures=items, **(items[0] | {'preview_settings': settings}),
                reason='RNC output byte sum, texture dimensions, and all palette and pixel extents agree.')


def preview(data, asset, selection):
    items = layout(data)
    if not items:
        raise formats.AssetError('The decoded RNC texture bank no longer matches its layout. Rescan the ROM.')
    texture = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    for key in ('frame', 'palette', 'mip'):
        formats.integer(selection.get(key, 0), key.capitalize(), 0, 0)
    result = formats.preview(data, items[texture]['preview_settings'])
    result['details'].update(texture=texture, note=asset['reason'])
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=texture)
    return result

"""Size-prefixed raw-deflate texture packs in a contiguous cartridge directory."""

import struct

from .. import formats
from . import display_lists, rzip_catalog

LAYOUT = 'prefixed-deflate-textures'


def catalogs(image, check):
    limit = min(len(image), 0x100000)
    skip = 0
    for start in range(0, limit - 96, 4):
        if start < skip:
            continue
        if start % 0x10000 == 0:
            check()
        first, end, flags = struct.unpack_from('>III', image, start)
        if not 0x10000 <= first < end <= len(image) or (first | end) % 16 or not 1 <= flags <= 0x100:
            continue
        rows, pos, previous = [], start, first
        while pos + 12 <= limit and len(rows) < 4096:
            a, b, kind = struct.unpack_from('>III', image, pos)
            if a != previous or not a < b <= len(image) or (a | b) % 16 or not 1 <= kind <= 0x100:
                break
            rows.append((a, b))
            previous, pos = b, pos + 12
        skip = pos
        if len(rows) < 8:
            continue
        # Check the entire directory before accepting any entry. Padding is at
        # most one alignment unit after the actual compressed stream.
        for a, b in rows:
            chunk = rzip_catalog._chunk(image, a, b)
            if not chunk or b - chunk[0] >= 16:
                break
        else:
            yield rows


def textures(data):
    if len(data) < 24:
        return []
    count, table, _, end, _, _ = struct.unpack_from('>6I', data)
    if not 1 <= count <= 4096 or table != 24 or table + count * 8 > end or end > len(data):
        return []
    offsets = []
    for i in range(count):
        kind, start = struct.unpack_from('>II', data, table + i * 8)
        if (kind >> 24 not in (1, 4) or kind & 0x00ff00ff or not kind & 0x0000ff00
                or start % 8 or not table + count * 8 <= start < end):
            return []
        if offsets and start <= offsets[-1]:
            return []
        offsets.append(start)
    result = {}
    for start, stop in zip(offsets, offsets[1:] + [end]):
        # Lists use file-relative addresses which the loader relocates. Present
        # those addresses as a segment to the shared RDP state reader.
        patched = bytearray(data[start:stop])
        terminal = None
        for at in range(0, min(len(patched) - 7, 0x400), 8):
            if patched[at] == 0xfd and patched[at + 4] == 0:
                patched[at + 4] = 1
            if patched[at:at + 8] == b'\xdf' + bytes(7):
                terminal = at + 8
                break
        if terminal is None:
            continue
        for item in display_lists._textures(patched, dict(start=0, end=terminal - 0x100)):
            address = item['address']
            if (item['space'] != 1 or not start <= address <= stop - item['bytes']
                    or item['fmt'] == 'rgba8888' and item['swapped']):
                continue
            settings = dict(format=item['fmt'], width=item['width'], height=item['height'], offset=address)
            palettes = 0
            if 'palette_address' in item:
                palette = item['palette_address']
                needed = 16 if item['fmt'] == 'ci4' else 256
                if (item['palette_space'] != 1 or item['palette_entries'] < needed
                        or not start <= palette <= stop - needed * 2):
                    continue
                settings.update(palette_offset=palette, palette_format=item['palette_format'])
                palettes = 1
            key = (address, item['fmt'], item['width'], item['height'], settings.get('palette_offset'))
            result[key] = dict(label=f'{display_lists.NAMES[item["fmt"]]} {item["width"]}×{item["height"]}',
                               preview_settings=settings, swapped=item['swapped'], frames=1, palettes=palettes,
                               levels=[dict(width=item['width'], height=item['height'], offset=0)])
    return list(result.values())


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for rows in catalogs(image, check):
        for start, end in rows:
            check()
            chunk = rzip_catalog._chunk(image, start, end)
            items = textures(chunk[1]) if chunk else []
            if not items:
                continue
            result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT, confidence='validated',
                               label=f'{len(items)} compressed textures', textures=items, texture_count=len(items),
                               frames=1, palettes=items[0]['palettes'], levels=items[0]['levels'],
                               preview_settings=dict(source='rom', format='auto', offset=start),
                               reason='The resource directory and local display lists identify the pixels and palettes.'))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    start, end = asset['offset'], asset['offset'] + asset['size']
    if not 0 <= start < end <= len(image):
        raise formats.AssetError('The compressed texture pack changed. Rescan ROM Explorer.')
    chunk = rzip_catalog._chunk(image, start, end)
    items = textures(chunk[1]) if chunk else []
    if index >= len(items) or items[index] != asset['textures'][index]:
        raise formats.AssetError('The compressed texture pack changed. Rescan ROM Explorer.')
    item = items[index]
    data = bytearray(chunk[1])
    settings = item['preview_settings']
    if item['swapped']:
        row = (settings['width'] * formats._bits(settings['format']) + 7) // 8
        for y in range(1, settings['height'], 2):
            for at in range(settings['offset'] + y * row, settings['offset'] + (y + 1) * row - 7, 8):
                data[at:at+8] = data[at+4:at+8] + data[at:at+4]
    result = formats.preview(data, settings)
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
    return result

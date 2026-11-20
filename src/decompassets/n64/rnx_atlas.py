"""Read a paged graphics archive with a shared palette and cross-bank tile references."""

import struct

from .. import formats

ROW = struct.Struct('>BBII')
FENCE = b'\xcd' * 6
PALETTE_SIZE = 32
CI4_REFERENCES = (5, 22)
RGBA_REFERENCES = (13,)


def _dimensions(data, at):
    width, height = data[at + 1] & 127, data[at + 2] & 127
    return width, height


def _bank(data, at, end, slots):
    index = 0
    records = []
    while index < slots and at < end:
        mode = data[at]
        if end - at < 2 or mode > 30:
            return None
        advance = 1
        if mode == 30:
            advance = data[at + 1]
            size = 2
        elif mode in (0, 1, 2, 21):
            if end - at < 5:
                return None
            argument = int.from_bytes(data[at + 3:at + 5], 'big')
            if mode == 1:
                size = 6 + argument
            elif mode == 21:
                target = int.from_bytes(data[at + 1:at + 5], 'big') - 1
                if not 0 <= target < at - 2 or data[target] != 1:
                    return None
                width, height = _dimensions(data, target)
                size = 5 + width * height
            else:
                width, height = _dimensions(data, at)
                if not width or not height or width % 2:
                    return None
                size = 5 + width * height // 2
        elif mode in (3, 4):
            size = 3
        elif mode in (11, 12, 28, 29):
            size = 8
        elif mode in (19, 20):
            size = 6
        elif 13 <= mode <= 18:
            size = 5
        else:
            size = 7
        if not advance or at + size > end or index + advance > slots:
            return None
        if mode != 30:
            records.append((at, mode, size, index))
        at += size
        index += advance
    return records if at == end and index == slots else None


def _rgba_plan(data, at, size):
    width, height = _dimensions(data, at)
    pixels = width * height
    encoding = data[at + 5]
    encoded = size - 6
    if encoding == 0 and pixels % 2 == 0 and encoded == pixels // 2 + 32 + pixels:
        return width, height, 16
    if encoding == 1:
        palette, rem = divmod(encoded - 2 * pixels, 2)
        if not rem and 1 <= palette <= 256:
            return width, height, palette
    if encoding == 2 and encoded == pixels * 3:
        return width, height, 0
    return None


def _texture(data, at, mode, size, entries, palette_start, palette_end):
    if mode in CI4_REFERENCES + RGBA_REFERENCES:
        ptr_at = at + (3 if mode in CI4_REFERENCES else 1)
        target = int.from_bytes(data[ptr_at:ptr_at + 4], 'big') - 1
        reference = entries.get(target)
        expected = {5: 0, 22: 2, 13: 1}[mode]
        if reference is None or reference[0] != expected:
            return None
        if mode in CI4_REFERENCES:
            width, height = _dimensions(data, target)
            selector = int.from_bytes(data[at + 1:at + 3], 'big')
        else:
            at, (mode, size) = target, reference
    if mode in (0, 2):
        width, height = _dimensions(data, at)
        selector = int.from_bytes(data[at + 3:at + 5], 'big')
        target = at
    if mode in (0, 2) + CI4_REFERENCES:
        palette_at = palette_start + selector * PALETTE_SIZE
        if palette_at + PALETTE_SIZE > palette_end:
            return None
        return dict(format='ci4', width=width, height=height, offset=target + 5,
                    palette_offset=palette_at, palette_format='rgba5551-be')
    if mode == 1 and (plan := _rgba_plan(data, at, size)):
        width, height, _ = plan
        if width and height:
            return dict(format='rgba8888', width=width, height=height, offset=at, tile_size=size)
    if mode in (3, 4):
        return dict(format='rgba5551-be', width=4, height=8, offset=at + 1, solid=True)
    return None


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
    records = {}
    locations = []
    at = palette_end
    for bank, (slots, _, expanded, end) in enumerate(rows[1:]):
        if not at < end <= len(data) or end - at > expanded:
            return None
        found = _bank(data, at, end, slots or 256)
        if found is None:
            return None
        for pos, mode, size, slot in found:
            records[pos] = mode, size
            locations.append((pos, bank, slot))
        at = end
    result = []
    for pos, bank, slot in locations:
        mode, size = records[pos]
        if settings := _texture(data, pos, mode, size, records, start, palette_end):
            result.append(dict(preview_settings=settings, frames=1, palettes=int('palette_offset' in settings),
                               bank=bank, slot=slot))
    return result or None


def _decode_rgba(data, settings):
    at, size = settings['offset'], settings['tile_size']
    width, height, palette_size = _rgba_plan(data, at, size)
    pixels = width * height
    encoding = data[at + 5]
    payload = data[at + 6:at + size]
    if encoding == 0:
        indices = (index for byte in payload[:pixels // 2] for index in (byte >> 4, byte & 15))
        palette_at = pixels // 2
    elif encoding == 1:
        indices = iter(payload[:pixels])
        palette_at = pixels
    else:
        indices = None
        palette_at = 0
        palette_size = pixels
    colors = [bytes(((word >> 10 & 31) << 3, (word >> 5 & 31) << 3, (word & 31) << 3))
              for word, in struct.iter_unpack('>H', payload[palette_at:palette_at + 2 * palette_size])]
    alpha = payload[-pixels:]
    if indices is None:
        return b''.join(color + bytes((a,)) for color, a in zip(colors, alpha))
    try:
        return b''.join(colors[index] + bytes((a,)) for index, a in zip(indices, alpha))
    except IndexError:
        raise formats.AssetError('An RGBA tile references a missing palette entry.') from None


def asset(items, offset, extent):
    settings = dict(items[0]['preview_settings'], source='decoded', block_offset=offset)
    groups = {}
    for item in items:
        groups.setdefault(item['bank'], []).append(item['slot'])
    return dict(offset=offset, size=extent, kind='image', confidence='validated', label='RNX shared-palette tiles',
                layout='rnx-ci4-atlas', texture_count=len(items), texture_groups=list(groups.items()),
                **(items[0] | {'preview_settings': settings}))


def preview(data, asset, selection):
    items = layout(data)
    if not items:
        raise formats.AssetError('The shared-palette texture archive changed. Rescan ROM Explorer.')
    selected = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    for key in ('frame', 'palette', 'mip'):
        formats.integer(selection.get(key, 0), key.capitalize(), 0, 0)
    item = items[selected]
    settings = item['preview_settings']
    if settings.get('tile_size'):
        data = _decode_rgba(data, settings)
        settings = dict(settings, offset=0)
    elif settings.get('solid'):
        at = settings['offset']
        data = data[at:at + 2] * (settings['width'] * settings['height'])
        settings = dict(settings, offset=0)
    result = formats.preview(data, settings)
    result['details'].update(texture=selected, bank=item['bank'], slot=item['slot'])
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=selected)
    return result

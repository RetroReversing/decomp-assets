"""Display-list textures in a compact chunked MIO resource directory."""
import struct

from .. import formats

LAYOUT = 'compact-mio-textures'
_CHUNK = 0x2000
_LIMIT = 4 * 1024 * 1024


def unpack(image, start, end, expected):
    """Decode bounded chunks; a reference may reach a preceding chunk."""
    if not (0 <= start < end <= len(image) and 0 < expected <= _LIMIT):
        return None
    output = bytearray()
    for pos in range(start, end, _CHUNK):
        chunk = image[pos:min(pos + _CHUNK, end)]
        if len(chunk) < 8:
            return None
        _, size, links, literals = struct.unpack_from('>4H', chunk)
        if not (0 < size <= expected - len(output) and 8 <= links <= literals < len(chunk)):
            return None
        mask, flags, bits, link_end = 8, 0, 0, literals
        target = len(output) + size
        while len(output) < target:
            if not bits:
                if mask >= links:
                    return None
                flags = chunk[mask]; mask += 1; bits = 8
            bits -= 1
            if flags & (1 << bits):
                if literals >= len(chunk):
                    return None
                output.append(chunk[literals]); literals += 1
            else:
                if links + 2 > link_end:
                    return None
                word = int.from_bytes(chunk[links:links + 2], 'big'); links += 2
                distance, count = (word & 0xfff) + 1, (word >> 12) + 3
                if distance > len(output) or len(output) + count > target:
                    return None
                for _ in range(count):
                    output.append(output[-distance])
    return bytes(output) if len(output) == expected else None


def texture(data):
    """Require a trailing F3DEX2 texture setup, its tile and bounded pixels."""
    if len(data) < 96 or data[-16:] != b'\xdf' + bytes(15):
        return None
    commands = [struct.unpack_from('>II', data, pos) for pos in range(len(data)-160, len(data)-8, 8) if pos >= 0]
    tile = None
    for x, y in commands:
        if x >> 24 == 0xf5 and (y >> 24) & 7 == 0:
            tile = ((x >> 21) & 7, (x >> 19) & 3)
        elif x >> 24 == 0xf2 and (y >> 24) & 7 == 0 and tile in ((0, 2), (2, 0)):
            w, h = ((y >> 12) & 0xfff)//4+1, (y & 0xfff)//4+1
            if not (1 <= w <= 512 and 1 <= h <= 512):
                return None
            fmt = 'rgba5551-be' if tile == (0, 2) else 'ci4'
            offset = 0 if fmt == 'rgba5551-be' else 32
            size = w*h*2 if offset == 0 else (w*h+1)//2
            if offset + size > len(data)-80:
                return None
            pointers = [b for a, b in commands if a >> 24 == 0xfd]
            if (0x01000000 + offset) not in pointers:
                return None
            if offset and 0x01000000 not in pointers:
                return None
            settings = dict(format=fmt, width=w, height=h, offset=offset)
            if offset:
                settings.update(palette_offset=0, palette_format='rgba5551-be')
            return settings
    return None


def directories(image, check):
    skip = 0
    for at in range(0x1000, min(len(image)-120, 0x10000), 4):
        if at < skip:
            continue
        if not at % 0x1000:
            check()
        first, end, size = struct.unpack_from('>3I', image, at)
        if first % 16 or end % 16 or not 0 < first < end <= len(image) or not 0 < size <= _LIMIT:
            continue
        rows = []
        previous = first
        for n in range(512):
            if at + 12*(n+1) > min(len(image), 0x10000):
                break
            lo, hi, length = struct.unpack_from('>3I', image, at + 12*n)
            if lo != previous or hi < lo or hi > len(image) or hi % 16 or length > _LIMIT or (hi == lo) != (length == 0):
                break
            rows.append((lo, hi, length)); previous = hi
        if len(rows) >= 8 and unpack(image, *rows[0]) is not None:
            skip = at + 12*len(rows)
            yield rows


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for rows in directories(image, check):
        items = []
        for i, (start, end, size) in enumerate(rows):
            if not i % 16:
                check()
            data = unpack(image, start, end, size) if size else None
            if data and (settings := texture(data)):
                items.append(dict(offset=start, size=end-start, unpacked=size, settings=settings,
                                  label=f"{settings['format']} {settings['width']}×{settings['height']}"))
        for pos in range(0, len(items), 128):
            group = items[pos:pos+128]
            start, end = group[0]['offset'], group[-1]['offset'] + group[-1]['size']
            found.append(dict(offset=start, size=end-start, kind='image', media='image', layout=LAYOUT,
                              label=f'{len(group)} compact MIO textures', confidence='validated',
                              reason='Chunk directory bounds the data; each decoded display list specifies its pixels and tile.',
                              textures=group, texture_count=len(group), frames=1, palettes=1, levels=[],
                              preview_settings=dict(source='rom', format='auto', offset=start)))
    return found


def preview(image, asset, selection):
    i = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    item = asset['textures'][i]
    data = unpack(image, item['offset'], item['offset']+item['size'], item['unpacked'])
    if data is None or texture(data) != item['settings']:
        raise formats.AssetError('The compressed texture changed. Scan ROM Explorer again.')
    result = formats.preview(data, item['settings'])
    result['details'].update(texture=i, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=i, frame=0, palette=0, mip=0)
    return result

"""Textures loaded from indexed compressed resources by constructed RDP commands."""

import struct

from .. import formats
from . import paired_resources

LAYOUT = 'constructed-resource-texture'


def _mapped(address, size, segments):
    offsets = {s['rom_start'] + address - s['vram'] for s in segments
               if s['vram'] <= address and address + size <= s['vram'] + s['rom_end'] - s['rom_start']}
    return offsets.pop() if len(offsets) == 1 else None


def _commands(events):
    """Pair constant stores into the same display-list word, in execution order."""
    pairs = {}
    for event in events:
        place, value = event.get('place'), event.get('value')
        if (event.get('kind') != 'store' or event.get('width') != 4 or not place
                or place.get('kind') != 'memory' or place.get('offset') not in (0, 4)
                or not value or value.get('kind') != 'constant'):
            continue
        key = event['block'], place['value']
        pair = pairs.setdefault(key, {})
        pair[place['offset']] = value['value']
    blocks = {}
    for (block, _), pair in pairs.items():
        if 0 in pair and 4 in pair:
            blocks.setdefault(block, []).append((pair[0], pair[4]))
    return blocks.values()


def _draw(commands):
    """Require a complete TLUT load followed by an indexed tile load."""
    for i in range(len(commands)-12):
        c = commands[i:i+13]
        if ([a >> 24 for a, _ in c] != [0xfd, 0xe8, 0xf5, 0xe6, 0xf0, 0xe7,
                                         0xfd, 0xf5, 0xe6, 0xf3, 0xe7, 0xf5, 0xf2]
                or c[0][0] != 0xfd100000 or c[1] != (0xe8000000, 0)
                or c[2][0] != 0xf5000100 or c[3] != (0xe6000000, 0)
                or c[5] != (0xe7000000, 0) or c[8] != (0xe6000000, 0)
                or c[10] != (0xe7000000, 0) or c[12][0] != 0xf2000000):
            continue
        tile, bounds = c[11], c[12]
        kind, size = tile[0] >> 21 & 7, tile[0] >> 19 & 3
        if kind != 2 or size != 0 or bounds[1] & 0x003003 or tile[1] >> 24 != bounds[1] >> 24:
            continue
        width, height = ((bounds[1] >> 14) & 1023)+1, ((bounds[1] >> 2) & 1023)+1
        stride = (width+1)//2
        if not 8 <= width <= 1024 or (tile[0] >> 9 & 511)*8 != stride:
            continue
        if (c[4][1] >> 14 & 1023)+1 < 16 or (c[9][1] >> 12 & 0xfff)+1 < (stride*height+1)//2:
            continue
        yield c[6][1], c[0][1] + ((tile[1] >> 20) & 15)*32, width, height


def _tables(image, context, check):
    """Find a loader that indexes paired addresses and selects compressed entries."""
    segments = context.get('segments', ())
    for fn in context.get('functions', ()):
        check()
        start, size = fn.get('rom_offset'), fn.get('size', 0)
        if start is None or not 24 <= size <= 0x8000 or not 0 <= start <= len(image)-size:
            continue
        code = image[start:start+size]
        if not all(word in code for word in (b'\x00\x04\x78\xc0', b'\x8c\x6a\x00\x14',
                                             b'\x05\x20\x00\x0e', b'\x3c\x01\x7f\xff')):
            continue
        words = struct.unpack(f'>{len(code)//4}I', code[:len(code)//4*4])
        for a,b,c,d,e,f in zip(words,words[1:],words[2:],words[3:],words[4:],words[5:]):
            if (a != 0x000478c0 or b >> 16 != 0x3c19 or c >> 16 != 0x2739
                    or d != 0x25f8fff8 or e != 0x03191821 or f != 0x8c670010):
                continue
            low = c & 0xffff
            address = ((b & 0xffff) << 16) + (low if low < 0x8000 else low-0x10000)
            if (offset := _mapped(address, 16, segments)) is not None:
                yield offset


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    context = context or {}
    read = context.get('read_code')
    if not read:
        return []
    tables = set(_tables(image, context, check))
    if not tables:
        return []
    members = {offset: size for _, entries in paired_resources.directories(image, check) for offset, size in entries}
    found = {}
    for fn in context.get('functions', ()):
        check()
        start, size = fn.get('rom_offset'), fn.get('size', 0)
        if start is None or not 24 <= size <= 0x8000 or not 0 <= start <= len(image)-size:
            continue
        code = image[start:start+size]
        if not all(part in code for part in (b'\xfd\x10', b'\xfd\x50', b'\xf5\x40', b'\xf2\x00')):
            continue
        events = read(fn['vram'], code, gp=context.get('gp', 0), check=check)['events']
        draws = (draw for commands in _commands(events) for draw in _draw(commands))
        for destination, palette, width, height in draws:
            palette_rom = _mapped(palette, 32, context.get('segments', ()))
            if palette_rom is None or not 0 <= palette_rom <= len(image)-32:
                continue
            needle = struct.pack('>I', destination)
            position = image.find(needle)
            while position >= 0:
                check()
                descriptor = struct.unpack_from('>I', image, position-4)[0] if position >= 4 else 0
                index = descriptor & 0x0fffffff
                if position % 4 == 0 and descriptor >> 28 == 4 and 0 < index <= 65535:
                    for table in tables:
                        at = table+8+index*8
                        if not 0 <= at <= len(image)-8:
                            continue
                        encoded, end = struct.unpack_from('>2I', image, at)
                        offset = encoded & 0x7fffffff
                        size = members.get(offset)
                        if not encoded & 0x80000000 or not size or offset+((size+1)&~1) != end:
                            continue
                        decoded = paired_resources.unpack(image, offset, size)
                        stride = (width+1)//2
                        rows = min(height, len(decoded or b'')//stride)
                        if rows < 8 or rows < height-1:
                            continue
                        found[offset] = dict(offset=offset, size=size, kind='image', layout=LAYOUT,
                            confidence='validated', label=f'CI4 {width}×{rows} packed texture',
                            palette_offset=palette_rom, width=width, height=rows, tile_height=height,
                            preview_settings=dict(source='rom',format='auto',offset=offset),
                            reason='The indexed loader and constructed RDP commands identify this resource, palette and tile. '
                                   'Only complete rows stored in the resource are shown.')
                position = image.find(needle, position+1)
    return list(found.values())


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    decoded = paired_resources.unpack(image, offset, size)
    palette = asset['palette_offset']
    if not decoded or not 0 <= palette <= len(image)-32:
        raise formats.AssetError('The packed texture or palette changed. Scan ROM Explorer again.')
    result = formats.preview(decoded + image[palette:palette+32],
                             dict(format='ci4', width=asset['width'], height=asset['height'], offset=0,
                                  palette_offset=len(decoded), palette_format='rgba5551-be'))
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=offset)
    return result

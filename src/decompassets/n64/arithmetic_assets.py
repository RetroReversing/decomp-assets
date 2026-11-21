"""Resource directories in arithmetic-packed cartridge data."""

import struct
from collections import defaultdict
from itertools import pairwise

from .. import formats
from . import lzari


def directory(data):
    """Read the aligned offset table found at the start of these decoded banks."""
    count = int.from_bytes(data[:4], 'big')
    first = (4 * count + 15) & ~7
    if not 0 < count <= 256 or first >= len(data) or len(data) % 8:
        return None
    end_of_table = 4 + 4 * count
    offsets = [int.from_bytes(data[at:at + 4], 'big') for at in range(4, end_of_table, 4)]
    if offsets[0] != first or any(data[end_of_table:first]):
        return None
    entries = list(pairwise([*offsets, len(data)]))
    return entries if all(start < end and not start % 8 for start, end in entries) else None


def _constant(event, slot):
    value = event['args'][slot]
    return value['value'] if value and value['kind'] == 'constant' else None


def loads(image, context, check):
    """Identify bounded cartridge reads immediately consumed by the decoder."""
    read = context.get('read_code')
    if read is None:
        return
    functions = {}
    decoders = set()
    dma = set()
    for fn in context.get('functions', ()):
        check()
        start, size = fn.get('rom_offset'), fn['size']
        if start is None or not 0 <= start < start + size <= len(image) or not 0 < size <= 0x8000:
            continue
        pc = fn['vram']
        code = image[start:start+size]
        functions.setdefault(pc, []).append(code)
        if 0x140 <= size <= 0x300:
            words = set(struct.unpack(f'>{len(code)//4}I', code[:len(code)//4*4]))
            # Window initialization, ring mask and the copy-length bias must agree.
            if {0x24060FC3, 0x24110FC4, 0x32310FFF, 0x2607FF03} <= words:
                decoders.add(pc)
        if 0x70 <= size <= 0x110 and all(word in code for word in (
                b'\x00\x80\x90\x21', b'\x00\xa0\x88\x21', b'\x00\xc0\x80\x21',
                b'\xaf\xb0\x00\x14', b'\x02\x40\x38\x21', b'\xaf\xb1\x00\x10')):
            dma.add(pc)
    decoders = {pc for pc in decoders if len(functions[pc]) == 1}
    dma = {pc for pc in dma if len(functions[pc]) == 1}
    if not decoders or not dma:
        return
    calls = {struct.pack('>I', 0x0c000000 | ((pc >> 2) & 0x3ffffff)) for pc in decoders}
    found = set()
    expanded = 0
    for pc, copies in functions.items():
        check()
        if len(copies) != 1 or not any(word in copies[0] for word in calls):
            continue
        events = read(pc, copies[0], gp=context.get('gp', 0), check=check)['events']
        outgoing = [event for event in events if event['kind'] == 'call']
        for transfer, decode in pairwise(outgoing):
            if (transfer['target'] not in dma or decode['target'] not in decoders
                    or transfer['block'] != decode['block']
                    or not 0 < decode['instruction']-transfer['instruction'] <= 64):
                continue
            source, staging, size = (_constant(transfer, slot) for slot in range(3))
            limit = _constant(decode, 2)
            if (source is None or staging is None or size is None or limit is None
                    or not 0x80000000 <= staging < 0x80800000
                    or _constant(decode, 1) != staging or _constant(decode, 0) != size):
                continue
            start = source - 0xb0000000
            if not 0 <= start < start + size <= len(image) or not 7 <= size <= 0x200000:
                continue
            key = (start, size, pc)
            if key in found:
                continue
            found.add(key)
            limit = min(limit, 0x100000)
            packed = image[start:start+size]
            try:
                # The game's bit reader may look into up to 17 terminating padding bits.
                decoded, _ = lzari.unpack(packed+bytes(3), limit=limit, check=check)
            except lzari.LzariError:
                continue
            if not (entries := directory(decoded)):
                continue
            expanded += len(decoded)
            if expanded > 16 * 1024 * 1024:
                return
            yield start, size, decoded, entries, events, decode


TEXTURES = 'arithmetic-packed-textures'


def _global(events, argument):
    if argument and argument['kind'] == 'memory':
        return next((_constant_load(event) for event in events
                     if event['instruction'] == argument['value']), None)
    return None


def _constant_load(event):
    place = event.get('place')
    if event['kind'] == 'load' and event['width'] == 4 and place and place['kind'] == 'constant':
        return place['value']
    return None


def _palette_member(code, pc, events, draw, bank):
    """Prove the texture pointer is bank + bank[4 + 4*i] + 512."""
    at = draw['instruction'] - pc
    if code[at+4:at+8] != b'\x24\xa5\x02\x00':
        return None
    before = max(0, at-192)
    words = [word for word, in struct.iter_unpack('>I', code[before:at])]
    if not words or words[-1] & 0xfc1fffff != 0x00052821:
        # The other operand of addu a1, a1, base can be in rt.
        if not words or words[-1] & 0xffe0ffff != 0x00a02821:
            return None
        base = words[-1] >> 16 & 31
    else:
        base = words[-1] >> 21 & 31
    for index in range(len(words)-2, -1, -1):
        word = words[index]
        if word & 0xffff0000 != (0x8c050000 | (base << 21)):
            continue
        offset = word & 0xffff
        if not 4 <= offset <= 1024 or offset % 4:
            return None
        global_load = next((event for event in reversed(events)
                            if pc <= event['instruction'] < pc + before + 4*index
                            and _constant_load(event) == bank), None)
        if not global_load:
            return None
        load = int.from_bytes(code[global_load['instruction']-pc:global_load['instruction']-pc+4], 'big')
        # The draw sets both the palette-load opcode and its 256-entry count.
        prior = [value for value, in struct.iter_unpack('>I', code[max(0, at-300):at])]
        if (load >> 16 & 31 == base
                and any(value & 0xffe0ffff == 0x3c00073f for value in prior)
                and any(value & 0xffe0ffff == 0x3c00f000 for value in prior)
                and any(value & 0xfc00ffff == 0x3400c000 for value in prior)):
            return offset//4-1
        return None
    return None


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    context = context or {}
    read = context.get('read_code')
    if not read:
        return []
    code_at = defaultdict(list)
    for fn in context.get('functions', ()):
        if (offset := fn.get('rom_offset')) is not None and 0 < fn['size'] <= 0x8000:
            code_at[fn['vram']].append(image[offset:offset+fn['size']])
    seen = set()
    results = {}
    for start, size, data, entries, loader, decode in loads(image, context, check):
        check()
        if (bank := _global(loader, decode['args'][3])) is None:
            continue
        for edge in loader:
            if edge['kind'] != 'call' or edge['instruction'] <= decode['instruction']:
                continue
            pc = edge['target']
            codes = code_at.get(pc, ())
            if len(codes) != 1 or (start, pc) in seen:
                continue
            seen.add((start, pc))
            code, = codes
            if b'\x02\x00' not in code:
                continue
            events = read(pc, code, gp=context.get('gp', 0), check=check)['events']
            for draw in events:
                if draw['kind'] != 'call' or [_constant(draw, i) for i in (2, 3)] != [2, 1]:
                    continue
                width, height = (_constant(draw, i) for i in (4, 5))
                if not width or not height or not 0 < width <= 1024 or not 0 < height <= 1024:
                    continue
                helpers = code_at.get(draw['target'], ())
                if len(helpers) != 1 or not all(word in helpers[0] for word in (
                        b'\x30\xc2\x00\x07', b'\x30\xe2\x00\x03',
                        b'\x3c\x02\xfd\x00', b'\x3c\x03\xf4\x00')):
                    continue
                index = _palette_member(code, pc, events, draw, bank)
                if index is None or index >= len(entries):
                    continue
                palette, end = entries[index]
                pixels = palette + 512
                if ((pixels + width*height + 7) & ~7) != end:
                    continue
                item = dict(preview_settings=dict(format='ci8', width=width, height=height,
                                                   offset=pixels, palette_offset=palette),
                            frames=1, palettes=1, levels=[dict(width=width,height=height,offset=0)])
                results.setdefault((start, size), {})[(index, width, height)] = item
    assets = []
    for (start, size), items in results.items():
        items = list(items.values())
        first = items[0]
        assets.append(dict(offset=start, size=size, kind='image', layout=TEXTURES,
                           confidence='validated', label='Packed indexed textures',
                           reason='The cartridge loader and drawing code establish the palette, image dimensions and packed extent.',
                           textures=items, frames=1, palettes=1, levels=first['levels'],
                           preview_settings=dict(first['preview_settings'], source='rom', offset=start)))
    return assets


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    try:
        data, _ = lzari.unpack(image[start:start+size]+bytes(3))
    except lzari.LzariError as error:
        raise formats.AssetError('The packed texture bank changed. Scan ROM Explorer again.') from error
    result = formats.preview(data, asset['textures'][index]['preview_settings'])
    result['settings'] = dict(source='rom', format='auto', offset=start, texture=index)
    result['decoded'] = dict(codec='LZARI', bytes=len(data), block_offset=start, member=asset['label'])
    return result

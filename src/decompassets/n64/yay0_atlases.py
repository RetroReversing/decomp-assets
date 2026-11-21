"""Compressed IA4 atlases linked by a loader table and matching glyph drawing code."""

import struct

from .. import formats

LAYOUT = 'yay0-ia4-atlas'
_PAIRS = struct.Struct('>8I')
_SIZE = 4096
_WIDTH, _HEIGHT = 128, 64
_DRAW_LUI = {0xfd70, 0xf560, 0xf300, 0xf200, 0x077f, 0x001f}
_DRAW_ORI = {0x1000, 0xf100, 0xc0fc}


def _constant_loads(events):
    return {e['place']['value'] for e in events if e['kind'] == 'load' and e['width'] == 4
            and e.get('place') and e['place']['kind'] == 'constant'}


def _mapped(address, segments):
    positions = {s['rom_start']+address-s['vram'] for s in segments
                 if s['vram'] <= address and address+_PAIRS.size <= s['vram']+s['rom_end']-s['rom_start']}
    return positions.pop() if len(positions) == 1 else None


def _table(image, offset):
    if not 0 <= offset <= len(image)-_PAIRS.size:
        return []
    pairs = _PAIRS.unpack_from(image, offset)
    ranges = []
    for source, size in zip(pairs[::2], pairs[1::2]):
        begin = source-0xb0000000
        end = begin+size
        if (not 16 <= size <= _SIZE*2 or not 0 <= begin < end <= len(image)
                or image[begin:begin+8] != b'Yay0\x00\x00\x10\x00'):
            return []
        ranges.append((begin, end))
    ordered = sorted(ranges)
    return ranges if all(a[1] <= b[0] for a,b in zip(ordered,ordered[1:])) else []


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    context = context or {}
    read = context.get('read_code')
    segments = context.get('segments', ())
    if not read or not segments or b'Yay0\x00\x00\x10\x00' not in image:
        return []
    drawing = []
    loaders = []
    for fn in context.get('functions', ()):
        check()
        offset, size = fn.get('rom_offset'), fn['size']
        if offset is None or not 0 < size <= 0x8000 or not 0 <= offset <= len(image)-size:
            continue
        code = image[offset:offset+size]
        if (b'\xfd\x70' not in code or b'\xc0\xfc' not in code) and b'\x8d\x23\x00\x00' not in code:
            continue
        words = [word for word, in struct.iter_unpack('>I',code[:len(code)//4*4])]
        lui = {word&0xffff for word in words if word>>26 == 15}
        ori = {word&0xffff for word in words if word>>26 == 13}
        if _DRAW_LUI <= lui and _DRAW_ORI <= ori:
            drawing.append(_constant_loads(read(fn['vram'],code,check=check)['events']))
        if {0x8d230000,0x8d27001c,0xae240000,0x26730008,0x26310004} <= set(words):
            loaders.append((words,_constant_loads(read(fn['vram'],code,check=check)['events'])))
    found = {}
    for words, loads in loaders:
        # The loader installs decoded atlas pointers into a second table. Its
        # base is used by the renderer for all four independently drawn tiles.
        for first, second in zip(words,words[1:]):
            if first>>16 != 0x3c02 or second>>16 != 0x2455:
                continue
            lo = second&0xffff
            output = ((first&0xffff)<<16)+(lo if lo < 0x8000 else lo-0x10000)
            if not any({output,output+4,output+8,output+12} <= regions for regions in drawing):
                continue
            for address in sorted(loads):
                if not all(address+delta in loads for delta in range(0,_PAIRS.size,4)):
                    continue
                offset = _mapped(address,segments)
                if offset is None:
                    continue
                for start,end in _table(image,offset):
                    try:
                        formats.unpack(image[start:end])
                    except formats.AssetError:
                        continue
                    found[start] = dict(offset=start,size=end-start,kind='image',
                                        layout=LAYOUT,label='Packed IA4 glyph atlas',confidence='validated',
                                        reason='The original loader table and drawing code establish the packed extent and IA4 tile settings.',
                                        preview_settings=dict(source='rom',format='auto',offset=start,
                                                              width=_WIDTH,height=_HEIGHT))
    return list(found.values())


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data, codec = formats.unpack(image[start:start+size])
    if len(data) != _SIZE:
        raise formats.AssetError('The packed atlas changed. Scan ROM Explorer again.')
    result = formats.preview(data,dict(format='ia4',width=_WIDTH,height=_HEIGHT,offset=0))
    result['settings'] = dict(source='rom',format='auto',offset=start)
    result['decoded'] = dict(codec=codec,bytes=len(data),block_offset=start,member=asset['label'])
    return result

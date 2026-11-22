"""Fixed-size sprite textures identified by their MIPS constructor calls."""
from .. import formats

LAYOUT = 'constructor-rgba16-sprite'
# The constructor records the pixel argument and sets type 1, depth 16 and
# both dimensions to 16. Requiring the complete sequence avoids guessing
# image dimensions from arbitrary pixel data.
_SHAPE = bytes.fromhex('ac860008 a08e0000 a4820002 a4820004 10a0001c a0820001')
_PREFIX = bytes.fromhex('24020010 240e0001')


def regions(image, *, context=None, check=lambda: None, **kwargs):
    context = context or {}
    read, segments = context.get('read_code'), context.get('segments', ())
    if not read or not segments:
        return []
    functions = context.get('functions', ())
    constructors = set()
    for fn in functions:
        at, size = fn.get('rom_offset'), fn.get('size', 0)
        if at is None or not 0 < size <= 0x1000 or not 0 <= at <= len(image)-size:
            continue
        code = image[at:at+size]
        if _PREFIX in code and _SHAPE in code:
            constructors.add(fn['vram'])
    if not constructors:
        return []
    pointers = set()
    for fn in functions:
        check()
        at, size = fn.get('rom_offset'), fn.get('size', 0)
        if at is None or not 0 < size <= 0x8000 or not 0 <= at <= len(image)-size:
            continue
        for event in read(fn['vram'], image[at:at+size], gp=context.get('gp', 0), check=check)['events']:
            if event['kind'] != 'call' or event['target'] not in constructors:
                continue
            value = event['args'][2]
            if value and value['kind'] == 'constant':
                pointers.add(value['value'])
    if len(pointers) < 2:
        return []
    result = []
    for address in sorted(pointers):
        positions = {s['rom_start']+address-s['vram'] for s in segments
                     if s['vram'] <= address and address+512 <= s['vram']+s['rom_end']-s['rom_start']}
        if len(positions) != 1:
            continue
        at = positions.pop()
        if at < 0 or at+512 > len(image) or len(set(image[at:at+512])) < 8:
            continue
        result.append(dict(offset=at, size=512, kind='image', media='image', layout=LAYOUT,
                           label='16 × 16 sprite texture', confidence='inferred',
                           reason='A sprite constructor records these pixels with fixed 16 × 16 dimensions and 16-bit depth; RGBA5551 is inferred.',
                           preview_settings=dict(source='rom', format='rgba5551-be', offset=at, width=16, height=16)))
    return result


def preview(image, asset, selection):
    result = formats.preview(image, asset['preview_settings'])
    result['settings'] = asset['preview_settings']
    result['note'] = asset['reason']
    return result

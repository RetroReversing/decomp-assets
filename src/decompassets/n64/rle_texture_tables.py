"""Texture tables and bounded 16-bit run-length streams identified by loader code."""

import struct

from .. import formats

LAYOUT = 'rle-texture-table'
_ROW = struct.Struct('>II4B')


def _address(high, low):
    return ((high & 0xffff) << 16) + struct.unpack('>h', struct.pack('>H', low & 0xffff))[0]


def _mapped(address, segments):
    matches = {s['rom_start']+address-s['vram'] for s in segments
               if s['vram'] <= address < s['vram']+s['rom_end']-s['rom_start']}
    return next(iter(matches)) if len(matches) == 1 else None


def _references(image, context, check):
    tables, banks = set(), set()
    segments = context.get('segments', ())
    for fn in context.get('functions', ()):
        check()
        start, size = fn.get('rom_offset'), fn['size']
        if start is None or not 0 <= start < start+size <= len(image) or size > 0x10000:
            continue
        code = image[start:start+size]
        for at in range(0, len(code)-8, 4):
            high, low = struct.unpack_from('>2I', code, at)
            if high >> 16 != 0x3c03 or low >> 16 != 0x2463:
                continue
            address = _address(high, low)
            table = _mapped(address, segments)
            if table is not None:
                tables.add(table)
            if at+20 <= len(code):
                high_end, branch, low_end = struct.unpack_from('>3I', code, at+8)
                if high_end >> 16 == 0x3c02 and branch >> 26 == 2 and low_end >> 16 == 0x2442:
                    end = _address(high_end, low_end)
                    if 0 <= address < end <= len(image) and not (address % 16 or end % 16):
                        banks.add((address, end))
    return sorted(tables), sorted(banks)


def _rows(image, start):
    rows = []
    for i in range(1024):
        at = start+i*_ROW.size
        if at < 0 or at+_ROW.size > len(image):
            break
        offset, runtime, width, height, flags, reserved = _ROW.unpack_from(image, at)
        if (runtime or not 0 < width <= 128 or not 0 < height <= 128 or flags > 3 or reserved
                or offset > 0x800000 or rows and offset <= rows[-1][0]):
            break
        rows.append((offset, width, height, flags))
    return rows


def _inflate(data, width, height):
    target = 4*width*height
    if not 0 < target <= formats.MAX_DIMENSION**2:
        return None
    out = bytearray()
    cursor = 0
    previous = None
    pixels = 0
    while pixels < target and cursor+2 <= len(data):
        value, = struct.unpack_from('>H', data, cursor)
        cursor += 2
        if value & 1:
            count = value >> 1
            if not count or cursor+2 > len(data):
                return None
            value, = struct.unpack_from('>H', data, cursor)
            cursor += 2
        else:
            count = 1
        if value == 0xf83e:
            if previous is None:
                return None
            value = previous
        else:
            previous = value
            value |= 1
        pixels += count
        if pixels > target:
            return None
        out.extend(struct.pack('>H', value)*count)
    if pixels != target or len(data)-cursor > 3:
        return None
    return bytes(out)


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    if not context:
        return []
    tables, banks = _references(image, context, check)
    result, seen = [], set()
    for table in tables:
        rows = _rows(image, table)
        if len(rows) < 5:
            continue
        matches = []
        for base, end in banks:
            check()
            found = []
            for left, right in zip(rows, rows[1:]):
                offset, width, height, _ = left
                finish = base+right[0]
                start = base+offset
                if start < finish <= end and _inflate(image[start:finish], width, height) is not None:
                    found.append((start, finish, width, height))
            if len(found) >= 4:
                matches.append(found)
        if len(matches) != 1:
            continue
        for start, end, width, height in matches[0]:
            if start in seen:
                continue
            seen.add(start)
            result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                               confidence='inferred', width=width*2, height=height*2,
                               label=f'RLE texture {width*2}×{height*2}',
                               reason='A code-referenced texture table uniquely fits this loader-bounded RLE bank.',
                               preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    width, height = asset['width'], asset['height']
    data = _inflate(image[start:start+size], width//2, height//2)
    if data is None:
        raise formats.AssetError('The RLE texture changed. Rescan ROM Explorer.')
    result = formats.preview(data, dict(format='rgba5551-be', offset=0, width=width, height=height))
    result['settings'] = asset['preview_settings']
    result['details']['note'] = asset['reason']
    return result

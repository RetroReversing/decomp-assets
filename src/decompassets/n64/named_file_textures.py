"""Textures from checked named file tables used by an N64 renderer.

File table and texture records are documented by the MIT-licensed hwtr-decomp project.
"""
import re
import struct

from .. import formats

LAYOUT = 'named-file-texture'
_ENTRY = struct.Struct('>7I')
_NAMES = re.compile(rb'[A-Z0-9_]{1,8}\.[A-Z0-9]{2,3}\0')
_CANDIDATE = re.compile(rb'\x80[\x00-\x7f]..[\x00-\x02]\0\0\0', re.S)


def _row(image, at):
    if at + _ENTRY.size > len(image):
        return None
    ptr, kind, packed, size, chunk, start, end = _ENTRY.unpack_from(image, at)
    if (ptr >> 24 != 0x80 or kind not in (0, 0x1000000, 0x2000000)
            or not 0 < packed <= size <= formats.MAX_BYTES or start % 16 or not start < end <= len(image)
            or packed > end-start or kind == 0 and packed != size):
        return None
    return ptr, kind, packed, size, chunk, start, end


def tables(image, check=lambda: None):
    names = {m.start(): m.group()[:-1].decode('ascii') for m in _NAMES.finditer(image)}
    covered = -1
    for hit in _CANDIDATE.finditer(image):
        at = hit.start()
        if at % 4 or at < covered:
            continue
        first, second = _row(image, at), _row(image, at+28)
        if not first or not second or first[6] != second[5]:
            continue
        delta = second[0] - first[0]
        bases = [first[0] - pos for pos in names if pos + delta in names and names[pos] < names[pos+delta]]
        best_rows, best_end = [], at
        for base in bases:
            rows, last_end, last_name = [], None, ''
            cursor = at
            while row := _row(image, cursor):
                name = names.get(row[0]-base)
                if not name or name <= last_name or last_end is not None and row[5] != last_end:
                    break
                rows.append((name, *row[1:]))
                last_name, last_end = name, row[6]
                cursor += 28
            if len(rows) > len(best_rows):
                best_rows, best_end = rows, cursor
        if len(best_rows) >= 8:
            check()
            covered = best_end
            yield at, best_rows


def _textures(image, row):
    name, kind, packed, size, _, start, end = row
    if kind or not name.endswith('.TEX'):
        return
    cursor = start
    while cursor + 8 <= start + size:
        w, h, fmt, _, ptr = struct.unpack_from('>4BI', image, cursor)
        bpp = {0: 2, 1: 1, 3: 4}.get(fmt)
        if not bpp or not w or not h or ptr or cursor+8+w*h*bpp > start+size:
            break
        yield cursor, w, h, {0: 'rgba5551-be', 1: 'i8', 3: 'rgba8888'}[fmt], 8+w*h*bpp
        cursor = (cursor + 8 + w*h*bpp + 7) & ~7


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for table, rows in tables(image, check):
        for row in rows:
            for index, (at, width, height, fmt, size) in enumerate(_textures(image, row)):
                result.append(dict(offset=at, size=size, kind='image', layout=LAYOUT,
                                   confidence='validated', table=table, name=row[0], index=index,
                                   width=width, height=height, label=f'{row[0]} · {width}×{height} texture {index+1}',
                                   reason='The named file extent and texture dimensions and pixel format agree.',
                                   preview_settings=dict(source='rom', format='auto', offset=at)))
    return result


def preview(image, asset, selection):
    for table, rows in tables(image):
        if table != asset['table']:
            continue
        row = next((row for row in rows if row[0] == asset['name']), None)
        if row:
            for index, (at, width, height, fmt, size) in enumerate(_textures(image, row)):
                if index == asset['index'] and at == asset['offset']:
                    result = formats.preview(image, dict(source='rom', offset=at+8, format=fmt,
                                              width=width, height=height))
                    result['details']['note'] = asset['reason']
                    result['settings'] = asset['preview_settings']
                    return result
    raise formats.AssetError('The texture file changed. Scan ROM Explorer again.')

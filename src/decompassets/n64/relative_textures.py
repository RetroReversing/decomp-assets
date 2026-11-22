"""Textures named by display-list commands in relative resource tables."""

import struct
from collections import defaultdict

from .. import formats
from . import relative_directory

LAYOUT = 'relative-directory-texture'
_FORMATS = {(0, 2): 'rgba5551-be', (0, 3): 'rgba8888', (3, 0): 'ia4',
            (3, 1): 'ia8', (3, 2): 'ia16', (4, 0): 'i4', (4, 1): 'i8'}


def references(data, count):
    """Read image indices and tile settings from nearby RDP commands."""
    found = defaultdict(set)
    for pos in range(0, len(data) - 16, 8):
        a, index = struct.unpack_from('>2I', data, pos)
        if a >> 24 != 0xfd or a & 0x7ffff or index >= count:
            continue
        tile = None
        for at in range(pos + 8, min(pos + 112, len(data) - 7), 8):
            x, y = struct.unpack_from('>2I', data, at)
            op = x >> 24
            if op == 0xfd:
                break
            if op == 0xf5 and (y >> 24) & 7 == 0:
                tile = ((x >> 21) & 7, (x >> 19) & 3)
            elif op == 0xf2 and (y >> 24) & 7 == 0 and tile in _FORMATS:
                width, height = ((y >> 12) & 0xfff) // 4 + 1, (y & 0xfff) // 4 + 1
                if 1 <= width <= 512 and 1 <= height <= 512:
                    found[index].add((tile, width, height))
                break
    return found


def _member(image, base, entries, index):
    if not 0 <= index < len(entries) - 1 or entries[index] & 0x80000000:
        return None
    start = base + (entries[index] & 0x7fffffff)
    end = base + (entries[index + 1] & 0x7fffffff)
    if data := relative_directory.unpack(image, start, end):
        return start, end, data
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, tables in relative_directory.tables(image, check=check):
        texture_table = tables[25]
        if not texture_table:
            continue
        refs = defaultdict(set)
        for table in (1, 4, 5):
            for index in range(len(tables[table]) - 1):
                if index % 32 == 0:
                    check()
                member = _member(image, base, tables[table], index)
                if member:
                    for key, uses in references(member[2], len(texture_table) - 1).items():
                        refs[key].update(uses)
        for index, uses in refs.items():
            if len(uses) != 1 or not (member := _member(image, base, texture_table, index)):
                continue
            start, end, data = member
            (tile, width, height), = uses
            fmt = _FORMATS[tile]
            bits = 4 << tile[1]
            if width * height * bits > len(data) * 8 or width * bits % 8:
                continue
            result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                               confidence='validated', label=f'{fmt.upper()} {width}×{height} texture',
                               directory=base, index=index, format=fmt, width=width, height=height,
                               reason='A display list identifies the resource and its tile format and dimensions.',
                               preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    for base, tables in relative_directory.tables(image):
        if base != asset['directory']:
            continue
        member = _member(image, base, tables[25], asset['index'])
        if member and member[:2] == (asset['offset'], asset['offset'] + asset['size']):
            data = member[2]
            result = formats.preview(data, dict(source='rom', offset=0, format=asset['format'],
                                                width=asset['width'], height=asset['height']))
            result['details']['note'] = asset['reason']
            result['settings'] = asset['preview_settings']
            result['decoded'] = dict(codec='gzip', bytes=len(data), block_offset=asset['offset'])
            return result
    raise formats.AssetError('The texture directory changed. Scan ROM Explorer again.')

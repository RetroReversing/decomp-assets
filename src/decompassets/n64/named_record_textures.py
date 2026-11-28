"""Textures in adjacent named records with complete self-describing payloads."""
import re
import struct

from .. import formats

LAYOUT = 'named-record-texture'
_NAME = re.compile(rb'[A-Za-z0-9_-]{1,12}\.tex\0')


def _record(image, start):
    if start < 0 or start+40 > len(image):
        return None
    size, reserved = struct.unpack_from('>II', image, start)
    name = image[start+8:start+24].split(b'\0', 1)[0]
    if reserved or not _NAME.fullmatch(name+b'\0') or start+size > len(image):
        return None
    width, height, depth = struct.unpack_from('>3H', image, start+24)
    if not 1 <= width <= formats.MAX_DIMENSION or not 1 <= height <= formats.MAX_DIMENSION:
        return None
    if depth == 16:
        expected = 40+width*height*2
    elif depth == 4 and width*height % 2 == 0:
        expected = 40+32+width*height//2
    else:
        return None
    if size != expected:
        return None
    return name.decode('ascii'), width, height, depth, size


def regions(image, *, check=lambda: None, progress=lambda _: None):
    records = {}
    for match in _NAME.finditer(image):
        start = match.start()-8
        if start % 8:
            continue
        record = _record(image, start)
        if record:
            records[start] = record
        check()
    adjacent = {start for start, row in records.items() if start+row[4] in records}
    adjacent.update(start+records[start][4] for start in tuple(adjacent))
    result = []
    for start in sorted(adjacent):
        name, width, height, depth, size = records[start]
        result.append(dict(offset=start, size=size, kind='image', layout=LAYOUT,
                           confidence='validated', name=name, width=width, height=height,
                           label=f'{name} · {width}×{height} texture',
                           reason='Adjacent named records bound the complete texture, dimensions and pixel data.',
                           preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    at = asset['offset']
    record = _record(image, at)
    if not record or not any(item['offset'] == at for item in regions(image)):
        raise formats.AssetError('The texture record changed. Scan ROM Explorer again.')
    _, width, height, depth, _ = record
    options = dict(source='rom', offset=at+40+(32 if depth == 4 else 0),
                   format='ci4' if depth == 4 else 'rgba5551-be', width=width, height=height)
    if depth == 4:
        options['palette_offset'] = at+40
    result = formats.preview(image, options)
    result['details']['note'] = asset['reason']
    result['settings'] = asset['preview_settings']
    return result

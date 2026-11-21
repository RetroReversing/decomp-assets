"""RNC sprite images packed as a grid of independently loaded CI8 tiles."""

import re
import struct

from .. import formats, rnc

LAYOUT = 'rnc-tiled-ci8'
_PIXELS = 0x208
_MAGIC = re.compile(rb'RNC[\x01\x02]')


def layout(data):
    if len(data) < _PIXELS:
        return None
    reserved, vertical, horizontal, mode = struct.unpack_from('>IHBB', data)
    if reserved or mode != 3:
        return None
    columns = [min(64, 8 << bit) for bit in range(7, -1, -1) if horizontal & (1 << bit)]
    rows = [min(32, 2 << bit) for bit in range(11, -1, -1) if vertical & (1 << bit)]
    width, height = sum(columns), sum(rows)
    if (not width or not height or (width+63)//64 != (vertical>>12)+1
            or _PIXELS+width*height != len(data)):
        return None
    return columns, rows


def _decode(image, start):
    if start+18 > len(image) or image[start:start+4] not in (b'RNC\1', b'RNC\2'):
        return None
    unpacked, packed = struct.unpack_from('>II', image, start+4)
    end = start+18+packed
    if (not _PIXELS < unpacked <= _PIXELS+376*286 or (unpacked-_PIXELS)%16
            or not 0 < packed <= formats.MAX_BYTES or end > len(image)):
        return None
    decoder = rnc.unpack if image[start+3] == 1 else rnc.unpack_m2
    try:
        return decoder(image[start:end], max_output=unpacked), end
    except rnc.RncError:
        return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    for magic in _MAGIC.finditer(image):
        check()
        start = magic.start()
        decoded = _decode(image, start)
        if decoded is None:
            continue
        data, end = decoded
        if grid := layout(data):
            columns, rows = grid
            assets.append(dict(
                kind='image', offset=start, size=end-start, label='RNC tiled image', layout=LAYOUT,
                confidence='validated', width=sum(columns), height=sum(rows),
                reason='The validated RNC output contains a palette and an exact grid of indexed tiles.',
                preview_settings=dict(format='auto', source='rom', offset=start),
            ))
    return assets


def _raster(data, columns, rows):
    width = sum(columns)
    pixels = bytearray(width*sum(rows))
    cursor = _PIXELS
    y = 0
    for height in rows:
        x = 0
        for tile_width in columns:
            for row in range(y, y+height):
                at = row*width+x
                pixels[at:at+tile_width] = data[cursor:cursor+tile_width]
                cursor += tile_width
            x += tile_width
        y += height
    return data[8:_PIXELS]+pixels


def preview(image, asset, selection):
    decoded = _decode(image, asset['offset'])
    if decoded is None or not (grid := layout(decoded[0])):
        raise formats.AssetError('The compressed image layout changed. Rescan ROM Explorer.')
    columns, rows = grid
    data = _raster(decoded[0], columns, rows)
    result = formats.preview(data, dict(format='ci8', width=sum(columns), height=sum(rows),
                                       palette_offset=0, offset=512))
    result['details']['note'] = asset['reason']
    result['settings'] = asset['preview_settings']
    return result

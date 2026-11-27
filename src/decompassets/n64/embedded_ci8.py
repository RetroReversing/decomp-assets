"""Named inline indexed images whose palettes follow word-swapped pixel rows."""
import re
import struct

from .. import formats

LAYOUT = 'embedded-indexed'
_HEADER = re.compile(rb'T[\x00-\x03]..\x00{4}', re.S)
_NAME = re.compile(rb'[A-Z0-9_]{1,11}\x00')


def record(image, at):
    if at < 12 or at+40 > len(image) or not _HEADER.match(image, at):
        return None
    name = image[at-12:at]
    if not _NAME.fullmatch(name):
        return None
    size = int.from_bytes(image[at+1:at+4], 'big')
    zero, colors, bits, flags, width, height, a, b, c = struct.unpack_from('>9I', image, at+4)
    if (zero or a or b or c or bits not in (4, 8) or flags & 255 != (37 if bits == 4 else 21)
            or not 0 < width <= 1024 or width*bits % 64 or not 0 < height <= 1024
            or not 16 <= colors <= 256 or colors % (16 if bits == 4 else 256)
            or size != 36+width*height*bits//8+colors*2 or at+4+size > len(image)):
        return None
    return width, height, bits, colors, size


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _HEADER.finditer(image):
        at = match.start()
        if at % 4 or not (item := record(image, at)):
            continue
        check()
        width, height, bits, colors, size = item
        result.append(dict(offset=at, size=size+4, kind='image', layout=LAYOUT,
                           confidence='validated', width=width, height=height, frames=1,
                           palettes=colors//(16 if bits == 4 else 256),
                           label=f'Embedded CI{bits} · {width}×{height} image',
                           reason='The record, dimensions, indexed pixel extent and palette agree.',
                           preview_settings=dict(source='rom', format='auto', offset=at,
                                                 width=width, height=height)))
    return result


def preview(image, asset, selection):
    at = asset['offset']
    item = record(image, at)
    if not item or item[4]+4 != asset['size']:
        raise formats.AssetError('The image record changed. Scan ROM Explorer again.')
    width, height, bits, colors, _ = item
    start = at+40
    row = width*bits//8
    pixels = bytearray(image[start:start+row*height])
    # The game loads each strip with dxt zero: odd TMEM rows exchange their two words.
    for y in range(1, height, 2):
        for x in range(0, row, 8):
            p = y*row+x
            pixels[p:p+8] = pixels[p+4:p+8]+pixels[p:p+4]
    count = 16 if bits == 4 else 256
    palette = formats.integer(selection.get('palette', 0), 'Palette', 0, colors//count-1)
    palette_start = start+row*height+palette*count*2
    colors = image[palette_start:palette_start+count*2]
    result = formats.preview(pixels+colors, dict(source='rom', offset=0, format='ci4' if bits == 4 else 'ci8',
                             width=width, height=height, palette_offset=len(pixels), palette_format='rgba5551-be'))
    result['settings'] = dict(asset['preview_settings'], palette=palette)
    result['details']['note'] = asset['reason']
    return result

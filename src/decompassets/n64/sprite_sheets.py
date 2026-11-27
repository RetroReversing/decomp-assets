"""Indexed SPR sheets with a palette and a complete directory of frames."""
import base64
import re
import struct

from .. import formats

LAYOUT = 'indexed-sprite-sheet'
_MAGIC = re.compile(b'SPR\x1a')


def _read(image, at):
    if at < 0 or at+12 > len(image) or image[at:at+4] != b'SPR\x1a':
        return None
    size, flags, colours = struct.unpack_from('<IHH', image, at+4)
    end = at+size
    if flags != 0x8008 or not 1 <= colours <= 127 or end > len(image):
        return None
    header = (at+12+colours*3+3)&~3
    if header+12 > end or any(image[header:header+4]):
        return None
    width, height, count = struct.unpack_from('<HHH', image, header+6)
    if not (1 <= width <= 1024 and 1 <= height <= 1024 and 1 <= count <= 64
            and width*height*count <= 1024*1024 and height*count <= 4096):
        return None
    pixels = header+12+count*12
    if pixels+width*height*count != end:
        return None
    for i in range(count):
        offset, x, y, w, h = struct.unpack_from('<IHHHH', image, header+12+i*12)
        if (offset, x, y, w, h) != (i*width*height, 0, 0, width, height):
            return None
    if any(x > colours for x in image[pixels:end]):
        return None
    return size, width, height, count, colours, pixels


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in _MAGIC.finditer(image):
        check()
        at = match.start()
        if not (record := _read(image, at)):
            continue
        size, width, height, count, _, _ = record
        result.append(dict(offset=at, size=size, kind='image', layout=LAYOUT, label='Indexed sprite frames',
                           confidence='validated', width=width, height=height*count, frame_count=count,
                           reason='The sprite frame directory, palette and complete indexed pixels agree.',
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def preview(image, asset, selection):
    at = asset['offset']
    if not (record := _read(image, at)):
        raise formats.AssetError('The sprite sheet changed. Rescan ROM Explorer.')
    size, width, height, count, colours, start = record
    palette = [bytes(4)] + [image[at+12+i*3:at+15+i*3]+b'\xff' for i in range(colours)]
    rgba = b''.join(palette[index] for index in image[start:at+size])
    png = formats._png(width, height*count, rgba)
    return dict(media='image', mime='image/png', details=dict(width=width, height=height*count, frames=count),
                data_url='data:image/png;base64,'+base64.b64encode(png).decode('ascii'),
                settings=dict(format='auto', source='rom', offset=at))

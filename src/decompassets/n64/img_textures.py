"""Bounded indexed IMG images with an inline RGB palette and optional LZ stream."""
import base64
import re
import struct

from .. import formats

LAYOUT = 'img-indexed-texture'
_MAGIC = re.compile(b'IMG\x1a')


def _read(image, at):
    if at < 0 or at + 12 > len(image) or image[at:at+4] != b'IMG\x1a':
        return None
    size, flags, count = struct.unpack_from('<IHH', image, at+4)
    end = at + size
    if flags not in (0x8008, 0xc008) or not 1 <= count <= 127 or end > len(image):
        return None
    dims = at+12+count*3
    if dims+4 > end:
        return None
    width, height = struct.unpack_from('<HH', image, dims)
    if not (1 <= width <= 1024 and 1 <= height <= 1024 and width % 4 == 0):
        return None
    start = (dims+7) & ~3
    if start > end:
        return None
    expected = width*height
    if flags == 0x8008:
        if start+expected != end:
            return None
        pixels = image[start:end]
    else:
        pixels = bytearray()
        pos = start
        while pos < end:
            token = image[pos]
            pos += 1
            if token < 128:
                pixels.append(token)
            else:
                if pos >= end:
                    return None
                distance = ((token & 7) << 8) | image[pos]
                pos += 1
                if token & 0x78:
                    length = ((token >> 3) & 15)+2
                    distance += 1
                else:
                    if not distance:
                        break
                    if pos >= end:
                        return None
                    length = image[pos]+18
                    pos += 1
                if distance > len(pixels) or len(pixels)+length > expected:
                    return None
                for _ in range(length):
                    pixels.append(pixels[-distance])
            if len(pixels) > expected:
                return None
        else:
            return None
        if pos != end or len(pixels) != expected:
            return None
    if len(pixels) != expected or any(index > count for index in pixels):
        return None
    return size, width, height, count, pixels


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in _MAGIC.finditer(image):
        check()
        at = match.start()
        if not (record := _read(image, at)):
            continue
        size, width, height, _, _ = record
        result.append(dict(offset=at, size=size, kind='image', layout=LAYOUT, label='Indexed IMG texture',
                           confidence='validated', width=width, height=height,
                           reason='The IMG header, RGB palette, dimensions and complete pixel stream agree.',
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def preview(image, asset, selection):
    at = asset['offset']
    if not (record := _read(image, at)):
        raise formats.AssetError('The indexed image changed. Rescan ROM Explorer.')
    _, width, height, count, pixels = record
    palette = [bytes(4)] + [image[at+12+i*3:at+15+i*3]+b'\xff' for i in range(count)]
    rgba = b''.join(palette[index] for index in pixels)
    png = formats._png(width, height, rgba)
    return dict(media='image', mime='image/png', details=dict(width=width, height=height),
                data_url='data:image/png;base64,'+base64.b64encode(png).decode('ascii'),
                settings=dict(format='auto', source='rom', offset=at))

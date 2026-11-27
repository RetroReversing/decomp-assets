"""PIC image banks in indexed runtime archives.

The PIC bitstream follows the public-domain decoder in Goemons-Great-Adventure-Decomp/src/pic.c.
"""
import re
import struct

from .. import formats
from . import indexed_runtime_archive

LAYOUT = 'indexed-pic-images'


def header(data, at):
    if data[at:at+3] != b'PIC':
        return None
    comment_end = data.find(b'\x1a', at+3, min(len(data), at+260))
    if comment_end < 0:
        return None
    reserved_end = data.find(b'\0', comment_end+1, min(len(data), comment_end+260))
    p = reserved_end+2
    if reserved_end < 0 or p+7 > len(data):
        return None
    mode = data[p] >> 4
    bits, width, height = struct.unpack_from('>3H', data, p+1)
    if mode == 4 or bits != 15 or not 0 < width <= 1024 or not 0 < height <= 1024:
        return None
    transparent = None
    comment = data[at+3:comment_end]
    if len(comment) >= 4:
        try:transparent = int(comment[:4], 16)
        except ValueError:pass
    return dict(offset=at, payload=p+7, width=width, height=height, transparent=transparent)


def frames(data):
    return [record for m in re.finditer(b'PIC', data) if m.start()%16 == 0
            and (record := header(data, m.start()))]


class Bits:
    def __init__(self, data, at):
        self.data, self.pos = data, at*8

    def read(self, n):
        if n < 0 or n > 24 or self.pos+n > len(self.data)*8:
            raise ValueError
        value = 0
        for _ in range(n):
            value = (value << 1) | ((self.data[self.pos//8] >> (7-self.pos%8)) & 1)
            self.pos += 1
        return value


def decode(data, record):
    width, height = record['width'], record['height']
    bits = Bits(data, record['payload'])
    pixels = [0] * (width*height)
    colors = [0]*128
    previous = [(i-1)%128 for i in range(128)]
    following = [(i+1)%128 for i in range(128)]
    newest = 0

    def color():
        nonlocal newest
        if bits.read(1):
            index = bits.read(7)
            if index != newest:
                previous[following[index]] = previous[index]
                following[previous[index]] = following[index]
                previous[following[newest]] = index
                following[index] = following[newest]
                following[newest] = index
                previous[index] = newest
                newest = index
            return colors[index] << 1
        raw = bits.read(15)
        value = ((raw >> 5) & 0x3ff) + ((raw & 31) << 10)
        newest = following[newest]
        colors[newest] = value
        return value << 1

    def chain(x, y, value):
        for _ in range(len(data)*4):
            code = bits.read(2)
            if code == 0:
                if not bits.read(1):
                    return
                x += 2 if bits.read(1) else -2
            elif code == 1:x -= 1
            elif code == 3:x += 1
            if x >= width:
                return
            y += 1
            if 0 <= x < width and y < height:
                pixels[y*width+x] = value
        raise ValueError

    try:
        pos = -1
        value = 0
        while True:
            n = 1
            while bits.read(1):
                n += 1
                if n > 22:raise ValueError
            run = bits.read(n)+(1 << n)-2
            for _ in range(run):
                pos += 1
                if pos >= len(pixels):break
                above = pixels[pos]
                if above:
                    value = above & 0xfffe
                pixels[pos] = value
            if pos >= len(pixels):break
            pos += 1
            if pos >= len(pixels):break
            value = color()
            pixels[pos] = value
            if bits.read(1):chain(pos % width, pos // width, value)
    except (ValueError, IndexError) as error:
        raise formats.AssetError('The PIC image stream is incomplete or invalid.') from error
    out = bytearray()
    for value in pixels:
        if record['transparent'] is not None and record['transparent'] == (value & 0xfffe):
            rgba = 0
        else:
            rgba = (((value & 0x3e) >> 1) << 11) | (((value & 0x7c0) >> 6) << 6) | (((value & 0xf800) >> 11) << 1) | 1
        out.extend(rgba.to_bytes(2, 'big'))
    return bytes(out)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for row in indexed_runtime_archive.members(image, check):
        check()
        try:data = indexed_runtime_archive.unpack(image, row)
        except formats.AssetError:continue
        if data[:3] != b'PIC':continue
        found = frames(data)
        if not found:continue
        result.append(dict(offset=row['start'], size=row['end']-row['start'], compressed=row['compressed'],
                           kind='image', layout=LAYOUT, confidence='inferred', frames=len(found), palettes=0,
                           label=f'Archive member {row["index"]} · {len(found)} PIC images',
                           width=found[0]['width'], height=found[0]['height'],
                           reason='Aligned PIC headers inside a bounded archive member record image dimensions.',
                           preview_settings=dict(format='auto', source='rom', offset=row['start'], frame=0,
                                                 width=found[0]['width'], height=found[0]['height'])))
    return result


def preview(image, asset, selection):
    row = dict(start=asset['offset'], end=asset['offset']+asset['size'], compressed=asset['compressed'])
    data = indexed_runtime_archive.unpack(image, row)
    found = frames(data)
    index = formats.integer(selection.get('frame', 0), 'Image', 0, len(found)-1)
    record = found[index]
    end = found[index+1]['offset'] if index+1 < len(found) else len(data)
    pixels = decode(data[:end], record)
    result = formats.preview(pixels, dict(source='rom', format='rgba5551-be', offset=0,
                             width=record['width'], height=record['height']))
    result['details']['note'] = asset['reason']
    result['settings'] = dict(asset['preview_settings'], frame=index)
    return result

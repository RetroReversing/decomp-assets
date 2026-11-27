"""TGA and packed bitmap files in a bounded, hierarchical LJAM archive.

Packed bitmap framing is documented by LibLR1: https://github.com/DustStormPettigrew/LibLR1
"""
import re
import struct

from .. import formats

LAYOUT = 'ljam-tga'
BMP_LAYOUT = 'ljam-bmp'


def _files(image, base):
    pending, seen, files = [base+4], set(), []
    while pending:
        directory = pending.pop()
        if directory in seen or len(seen) >= 256 or directory < base+4 or directory+4 > len(image):
            return []
        seen.add(directory)
        count, = struct.unpack_from('<I', image, directory)
        end = directory+4+count*20
        if count > 8192 or end+4 > len(image) or len(files)+count > 20000:
            return []
        for at in range(directory+4, end, 20):
            name = image[at:at+12].split(b'\0', 1)[0]
            offset, size = struct.unpack_from('<II', image, at+12)
            if not name or any(c < 32 or c > 126 for c in name) or offset > len(image)-base or size > len(image)-base-offset:
                return []
            if size:
                files.append((name, base+offset, size))
        count, = struct.unpack_from('<I', image, end)
        if count > 256 or end+4+count*16 > len(image):
            return []
        for at in range(end+4, end+4+count*16, 16):
            name = image[at:at+12].split(b'\0', 1)[0]
            offset, = struct.unpack_from('<I', image, at+12)
            if not name or any(c < 32 or c > 126 for c in name) or not 0 < offset < len(image)-base:
                return []
            pending.append(base+offset)
    return files


def _tga(image, start, size):
    if size < 18 or not 0 <= start <= len(image)-size:
        return None
    ident, cmap, kind = struct.unpack_from('<3B', image, start)
    width, height, bits, flags = struct.unpack_from('<HHBB', image, start+12)
    pixels = start+18+ident
    if (cmap or kind != 2 or bits != 32 or flags & 0x10 or not 0 < width <= formats.MAX_DIMENSION
            or not 0 < height <= formats.MAX_DIMENSION or width*height > formats.MAX_PIXELS
            or pixels+width*height*4 > start+size):
        return None
    return pixels, width, height, flags


def regions(image, *, check=lambda: None, **kwargs):
    found = {}
    for match in re.finditer(b'LJAM', image):
        base = match.start()
        for name, start, size in _files(image, base):
            check()
            if name.upper().endswith(b'.BMP'):
                item = _bmp(image, start, size)
                if item:
                    width, height, _ = item
                    found[(start, size)] = dict(offset=start, size=size, kind='image', layout=BMP_LAYOUT,
                        label='Archive packed bitmap', confidence='validated', width=width, height=height,
                        frames=1, palettes=0, reason='A bounded archive names a complete packed bitmap.',
                        preview_settings=dict(source='rom', format='auto', offset=start, width=width, height=height, frame=0))
                continue
            if not name.upper().endswith(b'.TGA') or not (item := _tga(image, start, size)):
                continue
            _, width, height, _ = item
            found[(start, size)] = dict(offset=start, size=size, kind='image', layout=LAYOUT,
                label='Archive TGA image', confidence='validated', width=width, height=height, frames=1, palettes=0,
                reason='A bounded archive directory names a complete 32-bit true-colour TGA image.',
                preview_settings=dict(source='rom', format='auto', offset=start, width=width, height=height, frame=0))
    return list(found.values())


def preview(image, asset, selection):
    if asset.get('layout') == BMP_LAYOUT:
        parsed = _bmp(image, asset['offset'], asset['size'])
        if not parsed:
            raise formats.AssetError('The archive image changed. Scan ROM Explorer again.')
        width, height, pixels = parsed
        result = formats.preview(pixels, dict(format='rgba8888', offset=0, width=width, height=height))
        result['settings'] = asset['preview_settings']
        result['details']['note'] = asset['reason']
        return result
    parsed = _tga(image, asset['offset'], asset['size'])
    if not parsed:
        raise formats.AssetError('The archive image changed. Scan ROM Explorer again.')
    start, width, height, flags = parsed
    raw = image[start:start+width*height*4]
    rows = [raw[i:i+width*4] for i in range(0, len(raw), width*4)]
    if not flags & 0x20:
        rows.reverse()
    pixels = b''.join(bytes((p[2], p[1], p[0], p[3])) for row in rows
                      for p in (row[i:i+4] for i in range(0, len(row), 4)))
    result = formats.preview(pixels, dict(format='rgba8888', offset=0, width=width, height=height))
    result['settings'] = asset['preview_settings']
    result['details']['note'] = asset['reason']
    return result


def _bmp(image, start, size):
    """Decode bounded packed archive bitmaps, including their framed LZ blocks."""
    end = start+size
    if size < 10 or start < 0 or end > len(image):
        return None
    tag, count, width, height = struct.unpack_from('<BBHH', image, start)
    bits = tag & 0x3c
    if (bits not in (4, 8, 24, 32) or (bits <= 8 and tag & 0x80)
            or not 0 < width <= formats.MAX_DIMENSION or not 0 < height <= formats.MAX_DIMENSION
            or width*height > formats.MAX_PIXELS):
        return None
    colors = count+1 if bits <= 8 else 0
    pos = start+6
    if pos+colors*3 > end:
        return None
    palette = image[pos:pos+colors*3]
    pos += colors*3
    row = (width*bits+7)//8
    needed = row*height
    pixels = bytearray()
    while len(pixels) < needed:
        if pos+4 > end:
            return None
        expanded, packed = struct.unpack_from('<HH', image, pos)
        pos += 4
        if not 0 < packed <= expanded <= 1500 or pos+packed > end or len(pixels)+expanded > needed:
            return None
        block = image[pos:pos+packed]
        pos += packed
        if packed == expanded:
            pixels.extend(block)
            continue
        decoded = bytearray(block[:1])
        cursor = 1
        finished = False
        while not finished:
            if cursor >= len(block):
                return None
            flags = block[cursor]
            cursor += 1
            for bit in range(8):
                if not flags & (0x80 >> bit):
                    if cursor >= len(block):
                        return None
                    decoded.append(block[cursor])
                    cursor += 1
                else:
                    if cursor+2 > len(block):
                        return None
                    token, low = block[cursor:cursor+2]
                    cursor += 2
                    length, back = token & 15, ((token & 0xf0) << 4) | low
                    if not length and not back:
                        finished = True
                        break
                    if not length:
                        if cursor >= len(block):
                            return None
                        length = block[cursor]+18
                        cursor += 1
                    else:
                        length = 18-length
                    if not 0 < back <= len(decoded) or len(decoded)+length > expanded:
                        return None
                    for _ in range(length):
                        decoded.append(decoded[-back])
                if len(decoded) > expanded:
                    return None
        if len(decoded) != expanded:
            return None
        pixels.extend(decoded)
    rgba = bytearray()
    for y in range(height):
        for x in range(width):
            at = y*row
            if bits <= 8:
                index = pixels[at+x] if bits == 8 else (pixels[at+x//2] >> (4 if x % 2 == 0 else 0)) & 15
                if index >= colors:
                    return None
                blue, green, red = palette[index*3:index*3+3]
                rgba.extend((red, green, blue, 255))
            else:
                at += x*(bits//8)
                blue, green, red = pixels[at:at+3]
                rgba.extend((red, green, blue, pixels[at+3] if bits == 32 else 255))
    return width, height, bytes(rgba)

"""Indexed images in chunked bitstream-compressed package resources."""

import re
import struct

from .. import formats

LAYOUT = 'chunked-package-image'
_LIMIT = 2 * 1024 * 1024


def _chunk(source):
    at, flags, output = 0, 1, bytearray()

    def byte():
        nonlocal at
        if at >= len(source):
            raise ValueError
        result = source[at]
        at += 1
        return result

    def bit():
        nonlocal flags
        if flags == 1:
            flags = byte() | 0x100
        result = flags & 1
        flags >>= 1
        return result

    def bits(count, value=0):
        for _ in range(count):
            value = value * 2 + bit()
        return value

    try:
        while len(output) <= _LIMIT:
            if not bit():
                output.append(byte())
                continue
            length = 0
            if bit():
                length = bits(2)
                if not length:
                    length = bits(4) + 3
                    if length == 3:
                        value = byte()
                        if not value:
                            return bytes(output), at
                        length = value + 18
            length += 2
            count, base = ((5, 1), (7, 33), (9, 161), (10, 673))[bits(2)]
            value = byte() if count >= 8 else 0
            if count >= 8:
                count -= 8
            distance = base + bits(count, value)
            if distance > len(output) or len(output) + length > _LIMIT:
                return None
            for _ in range(length):
                output.append(output[-distance])
    except (IndexError, ValueError):
        pass
    return None


def _header(data):
    if not data.startswith(b'PKG'):
        return None
    for at in range(8, min(36, len(data) - 15), 4):
        kind, size = struct.unpack_from('>2I', data, at)
        tiles, height, pixel_kind, reserved, pixel_offset = struct.unpack_from('>4BI', data, at + 8)
        width = tiles * 8
        if (kind == 1 and pixel_kind == 1 and not reserved and pixel_offset == 16
                and 8 <= width <= 1024 and 1 <= height <= 255
                and size == 16 + width * height):
            offset = at + 16
            return offset, width, height, offset + width * height + 512
    return None


def _package(image, start, end):
    pos = start
    data = bytearray()
    header = None
    for _ in range(256):
        if not (result := _chunk(memoryview(image)[pos:end])):
            return None
        block, used = result
        if not block or len(data) + len(block) > _LIMIT:
            return None
        data.extend(block)
        pos = (pos + used + 3) & ~3
        if pos > end:
            return None
        if header is None:
            header = _header(data)
            if header is None:
                return None
        if len(data) >= header[3]:
            return bytes(data), pos, header
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in re.finditer(b'PKG', image):
        start = match.start() - 1
        if start < 0 or start % 4 or image[start] & 7:
            continue
        check()
        package = _package(image, start, len(image))
        if not package:
            continue
        _, end, (_, width, height, _) = package
        result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                           confidence='validated', width=width, height=height,
                           label='Compressed indexed package image',
                           reason='A complete compressed package contains a bounded indexed image and palette.',
                           preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    package = _package(image, start, start + size)
    if not package:
        raise formats.AssetError('The compressed image package changed. Rescan ROM Explorer.')
    data, _, (offset, width, height, _) = package
    pixels = data[offset:offset+width*height]
    # The package stores scanlines bottom-to-top, as the game draws them.
    pixels = b''.join(pixels[row:row+width] for row in range(len(pixels)-width, -1, -width))
    palette = data[offset+width*height:offset+width*height+512]
    result = formats.preview(pixels + palette, dict(format='ci8', offset=0, width=width, height=height,
                                                   palette_offset=len(pixels), palette_format='rgba5551-be'))
    result['settings'] = dict(asset['preview_settings'])
    result['details']['note'] = asset['reason']
    return result

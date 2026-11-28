"""Indexed images in a directory of byte-counted chunked LZ resources."""

import struct

from .. import formats

LAYOUT = 'chunked-lz-indexed-image'
_LIMIT = 4 * 1024 * 1024


def decode(source, expected):
    """Decode independent input chunks with a shared backward-copy window."""
    if source[:5] == b'\x03\0\0\x10\0':
        from . import chunked_bits
        return chunked_bits.decode(source, expected)
    if not 0 < expected <= _LIMIT or len(source) < 6 or len(source) > _LIMIT:
        return None
    result = bytearray()
    terminated = False
    for start in range(0, len(source), 0x1000):
        end = min(start + 0x1000, len(source))
        pos = start + (5 if start == 0 else 0)
        while pos < end:
            command = source[pos]
            pos += 1
            if not command:
                if end == len(source):
                    terminated = pos == end
                break
            count = command & 0x7f
            if len(result) + count > expected:
                return None
            if command & 0x80:
                if pos + count > end:
                    return None
                result.extend(source[pos:pos + count])
                pos += count
            else:
                if pos + 2 > end:
                    return None
                distance = source[pos] | source[pos + 1] << 8
                pos += 2
                if not 0 < distance <= len(result):
                    return None
                for _ in range(count):
                    result.append(result[-distance])
    return bytes(result) if terminated and len(result) == expected else None


def image_info(data):
    if len(data) < 22:
        return None
    first, second, third, sentinel, image_size, width, height = struct.unpack_from('>4HI2H', data)
    if (first, second, third, sentinel) != (8, 1, 1, 0xffff):
        return None
    if not 8 <= width <= 1024 or not 8 <= height <= 1024 or image_size != width * height + 8:
        return None
    palette = 16 + width * height
    if palette + 518 != len(data) or data[palette:palette + 6] != b'\x02\x06\x01\x00\x00\x08':
        return None
    return width, height, palette + 6


def directories(image, check=lambda: None):
    """Require a full consecutive directory with at least three members."""
    for at in range(0, len(image) - 36, 2):
        if at % 0x10000 == 0:
            check()
        first, expanded, packed = struct.unpack_from('>III', image, at)
        if not 36 <= first <= 0x6000 or first % 12 or not 0 < expanded <= _LIMIT or not packed & 0x80000000:
            continue
        count = first // 12
        if at + first > len(image):
            continue
        previous = first
        entries = []
        for index in range(count):
            offset, size, flags = struct.unpack_from('>III', image, at + index * 12)
            if flags and not flags & 0x80000000:
                break
            packed_size = flags & 0x7fffffff if flags else size
            if (offset != previous or not 0 < size <= _LIMIT
                    or not 0 < packed_size <= _LIMIT or at + offset + packed_size > len(image)):
                break
            if flags:
                entries.append((at + offset, packed_size, size))
            previous = (offset + packed_size + 1) & ~1
        else:
            yield at, entries


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    seen = set()
    for directory, entries in directories(image, check):
        for offset, size, expanded in entries:
            if offset in seen:
                continue
            seen.add(offset)
            check()
            decoded = decode(image[offset:offset + size], expanded)
            info = image_info(decoded or b'')
            if not info:
                continue
            width, height, _ = info
            found.append(dict(offset=offset, size=size, expanded=expanded, directory=directory,
                              kind='image', layout=LAYOUT, confidence='validated',
                              label=f'CI8 {width}×{height} packed image', width=width, height=height,
                              frames=1, palettes=1, levels=[dict(width=width, height=height, offset=0)],
                              preview_settings=dict(source='rom', format='auto', display_format='CI8',
                                                    width=width, height=height, offset=offset),
                              reason='The resource directory, decoded dimensions and embedded palette agree.'))
    return found


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    decoded = decode(image[offset:offset + size], asset['expanded'])
    info = image_info(decoded or b'')
    if not info:
        raise formats.AssetError('The compressed image changed. Scan ROM Explorer again.')
    width, height, palette = info
    result = formats.preview(decoded, dict(format='ci8', width=width, height=height, offset=16,
                                           palette_offset=palette, palette_format='rgba5551-be'))
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=offset)
    return result

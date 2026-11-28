"""Indexed images in output-sized streams with a 4 KiB LZSS window."""

import struct

from .. import formats

LAYOUT = 'lz-indexed-image'
_LIMIT = formats.MAX_BYTES
_SIGNATURE = bytes.fromhex('edf0100001')


def unpack(data):
    """Decode a bounded stream, returning its output and consumed input length."""
    if len(data) < 5 or not 0 < (size := int.from_bytes(data[:4], 'big')) <= _LIMIT:
        return None
    window = bytearray(4096)
    write, cursor, out = 0xfee, 4, bytearray()
    while len(out) < size:
        if cursor >= len(data):
            return None
        flags = data[cursor]
        cursor += 1
        for _ in range(8):
            if len(out) == size:
                break
            if flags & 1:
                if cursor >= len(data):
                    return None
                value = data[cursor]
                cursor += 1
                out.append(value)
                window[write] = value
                write = (write + 1) & 0xfff
            else:
                if cursor + 2 > len(data):
                    return None
                lo, hi = data[cursor:cursor+2]
                cursor += 2
                source = lo | (hi & 0xf0) << 4
                for index in range((hi & 15) + 3):
                    if len(out) == size:
                        break
                    value = window[(source + index) & 0xfff]
                    out.append(value)
                    window[write] = value
                    write = (write + 1) & 0xfff
            flags >>= 1
    return bytes(out), cursor


def record(data):
    """Validate the section offsets, palette count and complete indexed image."""
    if len(data) < 0x40:
        return None
    header, kind, palette_header, image_header, palette_bytes, _, _, marker = struct.unpack_from('>8I', data)
    if (header != 0x10 or kind not in (0x10000, 0x10001) or palette_header != 0x10
            or marker != 0xffffffff or image_header != 0x20 + palette_bytes
            or image_header + 16 > len(data)):
        return None
    bits = 4 if kind == 0x10000 else 8
    palette_size = 32 if bits == 4 else 512
    if not palette_size <= palette_bytes <= 512 or palette_bytes % palette_size:
        return None
    _, _, _, _, words, height, sentinel = struct.unpack_from('>6HI', data, image_header)
    width = words * (4 if bits == 4 else 2)
    if (sentinel != 0xffffffff or not 0 < width <= formats.MAX_DIMENSION
            or not 0 < height <= formats.MAX_DIMENSION or width * height > formats.MAX_PIXELS
            or image_header + 16 + width * height * bits // 8 != len(data)):
        return None
    return width, height, bits, palette_bytes // palette_size


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """Find streams whose compressed prefix and complete image descriptor agree."""
    result, cursor, attempts, expanded = [], 0, 0, 0
    while (hit := image.find(_SIGNATURE, cursor)) >= 0:
        cursor = hit + 1
        start = hit - 5
        if start < 0 or start % 4 or image[hit-1] & 15 != 14:
            continue
        check()
        attempts += 1
        if attempts > 4096:
            break
        decoded = unpack(memoryview(image)[start:start+_LIMIT])
        if not decoded:
            continue
        expanded += len(decoded[0])
        if expanded > 128 * 1024 * 1024:
            break
        if not (item := record(decoded[0])):
            continue
        width, height, bits, palettes = item
        result.append(dict(offset=start, size=decoded[1], kind='image', layout=LAYOUT,
                           confidence='validated', width=width, height=height, frames=1, palettes=palettes,
                           label=f'Compressed CI{bits} · {width}×{height} image',
                           preview_settings=dict(source='rom', format='auto', offset=start,
                                                 width=width, height=height),
                           reason='The complete LZSS stream and its indexed image and palette extents agree.'))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    if not 0 <= start < start+size <= len(image):
        raise formats.AssetError('The compressed image changed. Scan ROM Explorer again.')
    decoded = unpack(image[start:start+size])
    if not decoded or decoded[1] != size or not (item := record(decoded[0])):
        raise formats.AssetError('The compressed image changed. Scan ROM Explorer again.')
    data = decoded[0]
    width, height, bits, palettes = item
    if (width, height, palettes) != (asset['width'], asset['height'], asset['palettes']):
        raise formats.AssetError('The compressed image changed. Scan ROM Explorer again.')
    palette = formats.integer(selection.get('palette', 0), 'Palette', 0, palettes-1)
    image_header = int.from_bytes(data[12:16], 'big')
    settings = dict(format='ci4' if bits == 4 else 'ci8', width=width, height=height,
                    offset=image_header+16, palette_offset=0x20+palette*(32 if bits == 4 else 512),
                    palette_format='rgba5551-be')
    result = formats.preview(data, settings)
    result['settings'] = dict(asset['preview_settings'], palette=palette)
    result['details']['note'] = asset['reason']
    return result

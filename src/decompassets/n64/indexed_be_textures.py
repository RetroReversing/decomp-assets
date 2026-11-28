"""Textures in a sectioned archive with big-endian dimensions."""

import re
import struct

from .. import formats
from . import indexed_deflate_models

LAYOUT = 'indexed-be-texture'
_FORMATS = [('rgba8888', 32), ('rgba5551-be', 16), ('i8', 8), ('i4', 4),
            ('ia16', 16), ('ia8', 8), ('ia4', 4)]


def archives(image, check=lambda: None):
    for match in re.finditer(b'\0\0\0C\0\0\0\0', image):
        check()
        at = match.start()
        if at % 16 or at + 0x120 > len(image):
            continue
        sections = struct.unpack_from('>68I', image, at + 4)
        base = at + 0x120
        if (sections[0] or base + sections[-1] > len(image) or any(image[at + 0x114:base])
                or any(a > b for a, b in zip(sections, sections[1:]))):
            continue
        yield base, sections


def texture(image, start, end):
    if not 0 <= start <= end <= len(image) or end - start < 32:
        return None
    header = image[start:start + 32]
    if header[3] == 1:
        data = indexed_deflate_models.unpack(image, start + 32, end)
        if data is None:
            return None
    elif header[3] == 0:
        data = image[start:end]
    else:
        return None
    if len(data) < 32:
        return None
    width, height = struct.unpack_from('>HH', data, 6)
    kind = data[2] & 15
    if not (1 <= width <= 512 and 1 <= height <= 512 and kind < len(_FORMATS)):
        return None
    fmt, bits = _FORMATS[kind]
    stride = (width * bits + 7) // 8
    size = stride * height
    if (struct.unpack_from('>I', data, 12)[0] != size or len(data) < 32 + size
            or len(data) > 32 + size + (15 if header[3] == 0 else 0)):
        return None
    if header[2] != data[2] or header[6:10] != data[6:10]:
        return None
    pixels = bytearray(data[32:32 + size])
    half = 8 if bits == 32 else 4
    for row in range(1, height, 2):
        for x in range(0, stride - 2 * half + 1, 2 * half):
            pos = row * stride + x
            pixels[pos:pos + 2 * half] = pixels[pos + half:pos + 2 * half] + pixels[pos:pos + half]
    return pixels, width, height, fmt


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for archive in archives(image, check):
        for table, data in ((1, 0), (3, 2)):
            members = indexed_deflate_models.members(image, archive, table, data)
            for i, (start, end) in enumerate(members):
                if i % 64 == 0:
                    check()
                    progress(dict(phase='Checking indexed texture resources', done=i, total=len(members)))
                found = texture(image, start, end)
                if not found:
                    continue
                _, width, height, fmt = found
                result.append(dict(offset=start, size=end - start, kind='image', media='image', layout=LAYOUT,
                    label=f'Indexed texture {table}:{i} · {width}×{height}', confidence='validated',
                    width=width, height=height, format=fmt, frames=1, palettes=0,
                    levels=[dict(width=width, height=height, offset=0)],
                    reason='The archive bounds the texture and its decoded header matches its complete pixel data.',
                    preview_settings=dict(source='rom', format='auto', offset=start, width=width, height=height)))
    return result


def preview(image, asset, selection):
    start = asset['offset']
    found = texture(image, start, start + asset['size'])
    if not found:
        raise formats.AssetError('The indexed texture changed. Scan ROM Explorer again.')
    pixels, width, height, fmt = found
    result = formats.preview(pixels, dict(format=fmt, offset=0, width=width, height=height))
    result['details']['note'] = 'Decoded indexed texture with odd-row interleaving reversed; runtime use is not established.'
    result['settings'] = asset['preview_settings']
    return result

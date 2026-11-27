"""Bounded RGBA16 image records with runtime address headers."""
import re
import struct

from .. import formats

LAYOUT = 'rgba-runtime-header'
_HEADER = struct.Struct('>4H6I')


def image_at(image, offset):
    if offset < 0 or offset % 4 or offset+_HEADER.size > len(image):
        return None
    height, width, kind, count, flags, address, repeat, a, b, c = _HEADER.unpack_from(image, offset)
    if (kind != 0x0201 or not 4 <= width <= 256 or not 4 <= height <= 256 or count != width*height
            or flags not in (0, 0x10000) or not 0x80000000 <= address < 0x80800000
            or repeat != height << 16 or a or b or c):
        return None
    size = _HEADER.size+count*2
    if offset+size > len(image):
        return None
    return size, width, height


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, match in enumerate(re.finditer(b'\x02\x01', image)):
        if index % 256 == 0:
            check()
        offset = match.start()-4
        if not (found := image_at(image, offset)):
            continue
        size, width, height = found
        result.append(dict(offset=offset, size=size, kind='image', confidence='inferred', layout=LAYOUT,
                           label=f'RGBA16 image {width}×{height}', width=width, height=height,
                           frames=1, palettes=0, frame_offsets=[0], palette_offsets=[], palette_entries=[],
                           levels=[dict(width=width, height=height, offset=_HEADER.size)],
                           reason='The image dimensions, pixel count, runtime pointer and bounded pixel extent agree.',
                           preview_settings=dict(source='rom', format='rgba5551-be', offset=offset,
                                                 width=width, height=height)))
    return result


def preview(image, asset, selection):
    found = image_at(image, asset['offset'])
    if not found or found[0] != asset['size']:
        raise formats.AssetError('The image record changed. Scan ROM Explorer again.')
    _, width, height = found
    result = formats.preview(image, dict(format='rgba5551-be', offset=asset['offset']+_HEADER.size,
                                         width=width, height=height))
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], frame=0, palette=0, mip=0)
    return result

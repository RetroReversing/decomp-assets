"""Sprite tables in cartridge-bounded raw-DEFLATE resources."""

import struct

from .. import formats
from . import graphbin

LAYOUT = 'deflate-sprite-pack'


def _images(data):
    if len(data) < 24:
        return []
    table, end = struct.unpack_from('>2I', data)
    if not (16 <= table < end <= len(data) and (end - table) % 8 == 0 and end - table <= 32768):
        return []
    images = []
    previous = None
    for pointers, header in struct.iter_unpack('>2I', data[table:end]):
        if pointers + 8 > table or header + 8 > table:
            return []
        palette, pixels = struct.unpack_from('>2I', data, pointers)
        width, height, bits, flag = struct.unpack_from('>4H', data, header)
        if (bits not in (4, 8, 16) or flag not in (0, 1) or not 0 < width <= 1024
                or not 0 < height <= 1024 or width * bits % 8
                or pixels + width * height * bits // 8 > table or pixels < header + 8):
            return []
        if bits < 16 and not palette:
            # Consecutive same-sized animation frames may reuse the first palette.
            if previous is None or previous[:3] != (width, height, bits):
                previous = None
                continue
            palette = previous[3]
        elif bits < 16 and not (header + 8 <= palette and palette + (1 << bits) * 2 <= pixels):
            return []
        previous = (width, height, bits, palette) if bits < 16 else None
        settings = dict(format={4: 'ci4', 8: 'ci8', 16: 'rgba5551-be'}[bits],
                        offset=pixels, width=width, height=height)
        if bits < 16:
            settings.update(palette_offset=palette, palette_format='rgba5551-be')
        images.append(settings)
    return images


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for start, end in graphbin.pairs(image, check):
        check()
        data = graphbin._unpack(image, start, end)
        if not data or not (images := _images(data)):
            continue
        first = images[0]
        result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                           confidence='validated', frames=len(images), width=first['width'], height=first['height'],
                           label=f"Sprite pack ({len(images)} images)",
                           reason='The sprite table bounds each image and its palette inside a compressed resource.',
                           preview_settings=dict(source='rom', format='auto', offset=start, frame=0)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = graphbin._unpack(image, start, start + size)
    images = _images(data) if data else []
    if not images:
        raise formats.AssetError('The compressed sprite pack changed. Rescan ROM Explorer.')
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, len(images)-1)
    result = formats.preview(data, images[frame])
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result

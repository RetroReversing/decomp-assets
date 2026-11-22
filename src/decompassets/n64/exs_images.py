"""Indexed backgrounds in bounded EXS streams."""

import re

from .. import formats

LAYOUT = 'exs-indexed-image'
_SIZE = 304 * 208


def unpack(image, start, expected):
    if not 0 < expected <= formats.MAX_BYTES or not 0 <= start < len(image):
        return None
    output = bytearray()
    at, mask, flags = start, 0, 0
    try:
        while len(output) <= expected:
            if not mask:
                flags = image[at]
                at += 1
                mask = 1
            if flags & mask:
                output.append(image[at])
                at += 1
            else:
                value = image[at] | image[at + 1] << 8
                at += 2
                offset = value & 4095
                if not offset:
                    return (bytes(output), at) if len(output) == expected else None
                count = (value >> 12) + 2
                position = len(output) % 4096 + 1
                base = len(output) - position
                source = base + offset - (4096 if offset > position else 0)
                if source < 0 or source >= len(output) or len(output) + count > expected:
                    return None
                for i in range(count):
                    output.append(output[source + i])
            mask = (mask << 1) & 255
    except IndexError:
        return None
    return None



def bank(data):
    if len(data) < 24 or data[:8] != b'_GTNEVR1':
        return []
    count = int.from_bytes(data[16:20], 'big')
    if not 1 <= count <= 256 or int.from_bytes(data[20:24], 'big') != 4:
        return []
    descriptors = 24 + count * 8
    palette = descriptors + count * 24
    pixels = palette + count * 32
    if pixels > len(data):
        return []
    frames = []
    for index in range(count):
        at = descriptors + index * 24
        width = int.from_bytes(data[at+4:at+6], 'big')
        height = int.from_bytes(data[at+6:at+8], 'big')
        if not 0 < width <= 512 or not 0 < height <= 512 or width * height % 2:
            return []
        size = width * height // 2
        if pixels + size > len(data):
            return []
        frames.append((pixels, width, height, palette + index * 32))
        pixels += size
    return frames if pixels == len(data) else []

def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'EXS\x01', image):
        at = match.start()
        if at + 8 > len(image):
            continue
        size = int.from_bytes(image[at+4:at+8], 'little')
        if size != _SIZE + 512 and not 64 <= size <= 512 * 1024:
            continue
        decoded = unpack(image, at + 8, size)
        if decoded is None:
            continue
        data, end = decoded
        frames = bank(data)
        if frames:
            result.append(dict(offset=at, size=end-at, kind='image', layout=LAYOUT, bank=True,
                               frames=len(frames), width=frames[0][1], height=frames[0][2],
                               label=f'Indexed texture bank ({len(frames)} images)', confidence='validated',
                               reason='The checked stream contains bounded image descriptors and palettes.',
                               preview_settings=dict(format='auto', source='rom', offset=at, frame=0)))
        elif size == _SIZE + 512 and len(set(data[_SIZE:_SIZE+512])) >= 8:
            result.append(dict(offset=at, size=end-at, kind='image', layout=LAYOUT,
                               label='Indexed background', confidence='inferred', width=304, height=208,
                               reason='The checked stream contains an inferred 304 by 208 image and trailing palette.',
                               preview_settings=dict(format='auto', source='rom', offset=at)))
        check()
    return result


def preview(image, asset, selection):
    at = asset['offset']
    expected = int.from_bytes(image[at+4:at+8], 'little')
    decoded = unpack(image, at + 8, expected)
    if decoded is None:
        raise formats.AssetError('The compressed image changed. Rescan ROM Explorer.')
    data = decoded[0]
    if asset.get('bank'):
        frames = bank(data)
        frame = formats.integer(selection.get('frame', 0), 'Frame', 0, len(frames)-1)
        offset, width, height, palette = frames[frame]
        settings = dict(format='ci4', offset=offset, width=width, height=height,
                        palette_offset=palette, palette_format='rgba5551-be')
    else:
        frame = None
        settings = dict(format='ci8', offset=0, width=304, height=208,
                        palette_offset=_SIZE, palette_format='rgba5551-be')
    result = formats.preview(data, settings)
    result['settings'] = dict(asset['preview_settings'])
    if frame is not None:
        result['settings']['frame'] = frame
    result['details']['note'] = asset['reason']
    return result

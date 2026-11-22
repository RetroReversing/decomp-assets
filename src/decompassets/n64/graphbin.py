"""Images in bounded raw-DEFLATE resources with GraphBin headers."""

import struct
import zlib

from .. import formats

LAYOUT = 'graphbin-images'
_LIMIT = 4 * 1024 * 1024


def _unpack(image, start, end):
    if not 0 <= start < end <= len(image) or end - start > _LIMIT:
        return None
    try:
        decoder = zlib.decompressobj(-15)
        data = decoder.decompress(image[start:end], _LIMIT + 1)
    except zlib.error:
        return None
    if len(data) > _LIMIT or not decoder.eof or len(decoder.unused_data) > 31:
        return None
    return data


def _images(data):
    images = []
    offset = 0
    while data[offset:offset + 8] == b'GraphBin' and offset + 528 <= len(data):
        width, height, count, kind = struct.unpack_from('>4H', data, offset + 8)
        bits = kind >> 8
        if (count != 1 or kind not in (0x400, 0x800, 0x1000) or not 0 < width <= 1024
                or not 0 < height <= 1024 or width * bits % 8):
            break
        end = offset + 528 + width * height * bits // 8
        if end > len(data):
            break
        settings = dict(format={4: 'ci4', 8: 'ci8', 16: 'rgba5551-be'}[bits],
                        offset=offset + 528, width=width, height=height)
        if bits < 16:
            settings.update(palette_offset=offset + 16, palette_format='rgba5551-be')
        images.append(settings)
        offset = end
    return images


def pairs(image, check):
    # The cartridge carries start/end pairs for the compressed resources. Require
    # the stream itself to agree before interpreting any decoded image headers.
    pairs = set()
    previous = None
    for index, (value,) in enumerate(struct.iter_unpack('>I', image[:len(image) // 4 * 4])):
        if index % 65536 == 0:
            check()
        if previous is not None and previous % 16 == value % 16 == 0 and 0 < previous < value <= len(image):
            if value - previous <= _LIMIT:
                pairs.add((previous, value))
        previous = value
    return sorted(pairs)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for start, end in pairs(image, check):
        check()
        data = _unpack(image, start, end)
        if not data or not data.startswith(b'GraphBin') or not (images := _images(data)):
            continue
        first = images[0]
        result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                           confidence='validated', frames=len(images), width=first['width'], height=first['height'],
                           label=f"GraphBin image pack ({len(images)} images)",
                           reason='A bounded raw-DEFLATE resource contains image headers and palette data.',
                           preview_settings=dict(source='rom', format='auto', offset=start, frame=0)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = _unpack(image, start, start + size)
    images = _images(data) if data else []
    if not images:
        raise formats.AssetError('The compressed image pack changed. Rescan ROM Explorer.')
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, len(images)-1)
    result = formats.preview(data, images[frame])
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result

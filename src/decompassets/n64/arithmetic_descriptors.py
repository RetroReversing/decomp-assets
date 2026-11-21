"""Packed bitmaps sized by native texture descriptors and a matching loader."""

import re
import struct

from .. import formats
from . import display_lists, lzari

LAYOUT = 'arithmetic-texture-descriptor'
_RECORD = struct.Struct('>BB5H4I')
_HEADER = re.compile(rb'[\x00-\x04][\x00-\x03].{10}\x00{8}\xb0', re.DOTALL)
# The loader reads two successive cartridge bounds through the same argument,
# subtracts them and skips 32 or 512 palette bytes according to the pixel size.
_LOADER = (0x8e630018, 0x8e620014, 0x00628823, 0x26420020, 0x26420200)
_DECODER = (0x24060fc3, 0x24110fc4, 0x32310fff, 0x2607ff03)


def entries(image, check):
    """Return bounded descriptors whose expanded sizes agree with their format."""
    for hit in _HEADER.finditer(image):
        check()
        at = hit.start()
        if at % 4 or at+_RECORD.size > len(image):
            continue
        fmt, depth, width, height, tx, ty, palette_index, _, _, start, end = _RECORD.unpack_from(image, at)
        pixel_format = display_lists.FORMATS.get((fmt, depth))
        if (not pixel_format or not 0 < width <= 1024 or not 0 < height <= 1024
                or tx > 1024 or ty > 1024 or palette_index > 255):
            continue
        start -= 0xb0000000
        end -= 0xb0000000
        if not 0 <= start < end <= len(image) or not 7 <= end-start <= formats.MAX_BYTES:
            continue
        color_size = (32 if depth == 0 else 512) if fmt == 2 else 0
        size = ((width*display_lists.BITS[depth]+7)//8)*height + color_size
        if size != int.from_bytes(image[start:start+4], 'big') or size > formats.MAX_BYTES:
            continue
        yield start, end, size, dict(format=pixel_format, width=width, height=height, offset=color_size)


def _has_functions(image, context, check):
    calls, decoders = set(), set()
    for fn in context.get('functions', ()):
        check()
        offset, size = fn.get('rom_offset'), fn['size']
        if offset is None or not 0x80 <= size <= 0x300 or not 0 <= offset <= len(image)-size:
            continue
        words = {word for word, in struct.iter_unpack('>I', image[offset:offset+size//4*4])}
        if words.issuperset(_LOADER):
            high = fn['vram'] & 0xf0000000
            calls.update(high | ((word & 0x3ffffff) << 2) for word in words if word >> 26 == 3)
        if words.issuperset(_DECODER):
            decoders.add(fn['vram'])
    return bool(calls & decoders)


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    if not _has_functions(image, context or {}, check):
        return []
    found = {}
    expanded = 0
    for start, end, size, settings in entries(image, check):
        key = start, settings['format'], settings['width'], settings['height']
        if key in found:
            continue
        if expanded+size > 32*1024*1024:
            break
        expanded += size
        try:
            lzari.unpack(image[start:end]+bytes(3), limit=size, check=check)
        except lzari.LzariError:
            continue
        found[key] = dict(offset=start, size=end-start, expanded_size=size, kind='image',
                          layout=LAYOUT, label=f"{display_lists.NAMES[settings['format']]} packed texture",
                          confidence='validated',
                          reason='A texture descriptor gives the format, dimensions and cartridge extent. The decoded byte count fits them.',
                          decoded_settings=settings, preview_settings=dict(settings, offset=start, source='rom'))
    return list(found.values())


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    try:
        data, _ = lzari.unpack(image[start:start+size]+bytes(3), limit=asset['expanded_size'])
    except lzari.LzariError as error:
        raise formats.AssetError('The packed texture changed. Scan ROM Explorer again.') from error
    settings = asset['decoded_settings']
    if settings['offset']:
        settings = dict(settings, palette_offset=0)
    result = formats.preview(data, settings)
    result['settings'] = dict(source='rom', format='auto', offset=start)
    result['decoded'] = dict(codec='LZARI', bytes=len(data), block_offset=start, member=asset['label'])
    return result

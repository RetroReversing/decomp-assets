"""Find CI8 texture banks with USO symbol and relocation evidence."""

import re
import struct
from itertools import islice
from math import isqrt

from .. import formats

_MAGIC = b'\x12\x34\x56\x78'
_NAME = re.compile(rb'\x12\x34\x56\x78\x00\x00\x00.\x00\x00\x00\x01([A-Za-z0-9_]{1,15}\.uso)\0', re.S)
_SECTION = struct.Struct('>3I')
_MAX_EXPANDED = 16 * 1024 * 1024


def _section(image, at, kind):
    if at + _SECTION.size > len(image):
        return None
    tag, size, _ = _SECTION.unpack_from(image, at)
    start = at + _SECTION.size
    end = start + size
    if tag != kind or size > formats.MAX_BYTES or end > len(image):
        return None
    return start, end


def _module(image, offset):
    module = offset + 40
    if image[module:module+4] != _MAGIC:
        return None
    compressed = _section(image, module+4, 6)
    if compressed is None:
        return None
    start, end = compressed
    if image[start:start+4] != b'Yay0' or end-start < 16:
        return None
    symbols = _section(image, end, 1)
    relocations = _section(image, symbols[1], 3) if symbols else None
    terminal = _section(image, relocations[1], 11) if relocations else None
    if not terminal or terminal[0] != terminal[1]:
        return None
    return compressed, symbols, relocations, terminal[1]


def _textures(raw, symbols, relocations):
    if len(symbols) % 12 or len(relocations) % 24 or not relocations or len(relocations) > 24 * 128:
        return []
    addresses = [offset for _, offset, _ in _SECTION.iter_unpack(symbols)]
    refs = list(_SECTION.iter_unpack(relocations))
    textures = []
    for (tex_ref, slot, mode), (pal_ref, pal_slot, pal_mode) in zip(refs[::2], refs[1::2]):
        if (tex_ref % 16 != 4 or pal_ref % 16 != 4 or slot % 16 != 8 or pal_slot != slot+4
                or mode != 1 or pal_mode != 1 or not 8 <= slot <= len(raw)-8
                or raw[slot-8:slot+8] != bytes.fromhex('00000110000001000000000000000000')):
            return []
        pi, ci = tex_ref // 16, pal_ref // 16
        if max(pi, ci)+1 >= len(addresses):
            return []
        pixels, pixel_end = addresses[pi:pi+2]
        palette, palette_end = addresses[ci:ci+2]
        if not 0 <= pixels < pixel_end <= palette < palette_end <= slot-8 or palette_end-palette != 512:
            return []
        side = isqrt(pixel_end-pixels)
        if side not in (192, 256) or side*side != pixel_end-pixels:
            return []
        settings = dict(format='ci8', width=side, height=side, offset=pixels,
                        palette_offset=palette, palette_format='rgba5551-be')
        textures.append(dict(preview_settings=settings, frames=1, palettes=1))
    return textures


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    expansion = 0
    for hit in islice(_NAME.finditer(image), 1024):
        check()
        offset = hit.start()
        module = _module(image, offset)
        if module is None:
            continue
        (start, end), symbols, relocations, stop = module
        expanded = struct.unpack_from('>I', image, start+4)[0]
        if not 0 < expanded <= formats.MAX_BYTES or expansion+expanded > _MAX_EXPANDED:
            continue
        expansion += expanded
        try:
            raw, _ = formats.unpack(image[start:end])
        except formats.AssetError:
            continue
        textures = _textures(raw, image[slice(*symbols)], image[slice(*relocations)])
        if not textures:
            continue
        result.append(dict(offset=offset, size=stop-offset, label=hit[1].decode(), kind='image', media='image',
                           layout='uso-ci8-bank', confidence='tentative', textures=textures, frames=1, palettes=1,
                           texture_count=len(textures),
                           reason='USO relocations identify the CI8 texels and RGBA16 palettes. Square dimensions are inferred from the texel extents.',
                           preview_settings={**textures[0]['preview_settings'], 'source':'rom', 'offset':offset}))
    return result


def preview(image, asset, selection):
    module = _module(image, asset['offset'])
    if not module:
        raise formats.AssetError('The texture bank no longer matches the USO sections. Rescan the ROM.')
    compressed, symbols, relocations, _ = module
    raw, _ = formats.unpack(image[slice(*compressed)])
    textures = _textures(raw, image[slice(*symbols)], image[slice(*relocations)])
    if not textures:
        raise formats.AssetError('The USO texture and palette links are no longer valid. Rescan the ROM.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures)-1)
    result = formats.preview(raw, textures[index]['preview_settings'])
    result['details']['note'] = asset['reason']
    result['settings'] = {**asset['preview_settings'], 'texture':index}
    return result

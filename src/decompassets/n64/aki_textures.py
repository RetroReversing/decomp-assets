"""Self-describing indexed textures with an inline RGBA16 palette.

Header layout: https://vpw.ajworld.net/vpwstudio/Manual/appendix_c.html#AkiTexture
"""
import re
import struct

from .. import formats
from . import aki_lzss

LAYOUT = 'aki-indexed-texture'
COMPRESSED = 'aki-compressed-indexed-texture'
_MAGIC = re.compile(b'TEX\x00')


def _read(image, at):
    if at < 0 or at+16 > len(image) or image[at:at+4] != b'TEX\0':
        return None
    width, height, bits, colour_bytes, colours = struct.unpack_from('>HHBBH', image, at+4)
    if (not 1 <= width <= 1024 or not 1 <= height <= 1024 or bits not in (4, 8)
            or colour_bytes != 2 or colours != 1 << bits or image[at+12:at+16] != bytes(4)):
        return None
    if bits == 4 and width % 2:
        return None
    size = 16+2*colours+width*height*bits//8
    if at+size > len(image):
        return None
    return width, height, bits, colours, size


def regions(image, *, check=lambda: None, **kwargs):
    result_list = []
    for match in _MAGIC.finditer(image):
        check()
        at = match.start()
        if not (record := _read(image, at)):
            # A literal first group leaves TEX and its dimensions visible in
            # the bounded LZSS stream; validate the entire decoded record.
            start = at-5
            if start < 0 or image[at-1] != 0xff:
                continue
            expected = int.from_bytes(image[start:start+4], 'big')
            if not 16 <= expected <= formats.MAX_BYTES:
                continue
            result = aki_lzss.unpack(image[start:start+expected*2+16], formats.MAX_BYTES, check)
            if not result or not (record := _read(result[0], 0)) or record[-1] != len(result[0]):
                continue
            width, height, bits, _, _ = record
            found_size = result[1]
            result = dict(offset=start, size=found_size, kind='image', layout=COMPRESSED,
                          label='Compressed indexed TEX texture', confidence='validated', width=width, height=height,
                          reason='A bounded LZSS stream expands to one complete TEX header, palette and pixel array.',
                          preview_settings=dict(format='auto', source='rom', offset=start))
            result_list.append(result)
            continue
        width, height, bits, _, size = record
        result_list.append(dict(offset=at, size=size, kind='image', layout=LAYOUT, label='Indexed TEX texture',
                           confidence='validated', width=width, height=height,
                           reason='A complete TEX header, dimensions, palette and indexed pixels fit the image.',
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result_list


def preview(image, asset, selection):
    at = asset['offset']
    if asset.get('layout') == COMPRESSED:
        result = aki_lzss.unpack(image[at:at+asset['size']], formats.MAX_BYTES)
        if not result or result[1] != asset['size']:
            raise formats.AssetError('The compressed texture changed. Rescan ROM Explorer.')
        image, at = result[0], 0
    if (not (record := _read(image, at))
            or asset.get('layout') == COMPRESSED and record[-1] != len(image)):
        raise formats.AssetError('The indexed texture changed. Rescan ROM Explorer.')
    width, height, bits, colours, _ = record
    out = formats.preview(image, dict(format=f'ci{bits}', width=width, height=height,
                                      offset=at+16+2*colours, palette_offset=at+16,
                                      palette_format='rgba5551-be'))
    out['details']['note'] = ('Indexed pixels and palette from a bounded LZSS stream and validated TEX header; '
                              'runtime use is not established.' if asset.get('layout') == COMPRESSED else
                              'Indexed pixels and palette from the validated TEX header; runtime use is not established.')
    out['settings'] = dict(format='auto', source='rom', offset=asset['offset'])
    return out

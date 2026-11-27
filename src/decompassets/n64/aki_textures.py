"""Self-describing indexed textures with an inline RGBA16 palette.

Header layout: https://vpw.ajworld.net/vpwstudio/Manual/appendix_c.html#AkiTexture
"""
import re
import struct

from .. import formats

LAYOUT = 'aki-indexed-texture'
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
    result = []
    for match in _MAGIC.finditer(image):
        check()
        at = match.start()
        if not (record := _read(image, at)):
            continue
        width, height, bits, _, size = record
        result.append(dict(offset=at, size=size, kind='image', layout=LAYOUT, label='Indexed TEX texture',
                           confidence='validated', width=width, height=height,
                           reason='A complete TEX header, dimensions, palette and indexed pixels fit the image.',
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def preview(image, asset, selection):
    at = asset['offset']
    if not (record := _read(image, at)):
        raise formats.AssetError('The indexed texture changed. Rescan ROM Explorer.')
    width, height, bits, colours, _ = record
    out = formats.preview(image, dict(format=f'ci{bits}', width=width, height=height,
                                      offset=at+16+2*colours, palette_offset=at+16,
                                      palette_format='rgba5551-be'))
    out['settings'] = dict(format='auto', source='rom', offset=at)
    return out

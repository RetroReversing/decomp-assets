"""Adjacent indexed tiles carrying an inline F3DEX texture setup."""
import bisect
import re
import struct

from .. import formats

LAYOUT = 'f3dex-inline-tile'
_SETUP = re.compile(rb'\xfd[\x10\x50]......\xf5.......\xf3.......\xf5.......\xb8\0{7}', re.S)


def regions(image, *, check=lambda: None, **kwargs):
    candidates = {}
    for match in _SETUP.finditer(image):
        at = match.start()-16
        if at < 0 or at % 8 or at+56 > len(image):
            continue
        check()
        width, height, kind, depth, palette, pixels = struct.unpack_from('>4H2I', image, at)
        if kind != 2 or depth not in (0, 1) or not 4 <= width <= 1024 or not 4 <= height <= 1024:
            continue
        if not 0x80000000 <= palette < 0x80800000 or not 0x80000000 <= pixels < 0x80800000:
            continue
        start = at+56
        size = (width*height*(4 << depth)+7)//8
        pal = start+palette-pixels
        palette_size = 32 if depth == 0 else 512
        if (start+size > len(image) or not 0 <= pal <= len(image)-palette_size
                or not any(image[pal:pal+palette_size]) or start <= pal < start+size):
            continue
        candidates[at] = dict(offset=start, size=size, pal=pal, width=width, height=height,
                              format='ci4' if depth == 0 else 'ci8', displacement=pixels-start)
    addresses = sorted(candidates)
    verified = set()
    for at, tile in candidates.items():
        low = tile['offset']+tile['size']
        i = bisect.bisect_left(addresses, low)
        while i < len(addresses) and addresses[i] <= low+1024:
            next_at = addresses[i]
            if candidates[next_at]['displacement'] == tile['displacement']:
                verified.update((at, next_at))
                break
            i += 1
    return [dict(offset=tile['offset'], size=tile['size'], kind='image', media='image', layout=LAYOUT,
                 confidence='validated', label='F3DEX indexed tile',
                 reason='Adjacent descriptors share a loaded-bank mapping and bound the pixels and palette.',
                 preview_settings=dict(source='rom', offset=tile['offset'], format=tile['format'],
                                       width=tile['width'], height=tile['height'], palette_offset=tile['pal'],
                                       palette_format='rgba5551-be'))
            for at in sorted(verified) for tile in (candidates[at],)]


def preview(image, asset, selection):
    result = formats.preview(image, asset['preview_settings'])
    result['settings'] = asset['preview_settings']
    return result

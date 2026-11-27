"""Indexed pictures in big-endian IWAD members with bounded Huffman streams.

The member and image layouts follow the GPL-3.0 HexenN64Tool by Erick194.
"""
import re
import struct

from .. import formats
from . import lzhuf

LAYOUT = 'be-iwad-image'
_LIMIT = 4 * 1024 * 1024


def archives(image, check=lambda: None):
    for match in re.finditer(b'IWAD', image):
        base = match.start()
        if base % 4 or base + 12 > len(image):
            continue
        count, directory = struct.unpack_from('>II', image, base + 4)
        if not 8 <= count <= 8192 or directory < 12 or base + directory + count * 16 > len(image):
            continue
        rows = []
        last_end = 12
        for i in range(count):
            offset, size, rawname = struct.unpack_from('>II8s', image, base + directory + 16 * i)
            name = rawname.split(b'\0', 1)[0]
            if (not name or any(c < 32 or c > 126 for c in name) or size > _LIMIT
                    or (size and (offset < last_end or offset + size > directory))
                    or (not size and offset)):
                break
            rows.append((offset, size, name.decode('ascii')))
            if size:
                last_end = offset + size
        else:
            names = [row[2] for row in rows]
            if all(names.count(name) == 1 for name in ('PLAYPAL', 'S_START', 'S_END')):
                check()
                yield base, rows


def unpack(image, base, row, *, prefix=None, check=lambda: None):
    offset, size, _ = row
    if size < 5 or base + offset + size > len(image):
        return None
    raw = image[base + offset:base + offset + size]
    length = int.from_bytes(raw[:4], 'big')
    if not 0 < length <= _LIMIT:
        return None
    try:
        return lzhuf.unpack(raw[4:], length, prefix=prefix, lsb_variant=True, check=check)
    except formats.AssetError:
        return None


def dimensions(header, length):
    if not header or len(header) < 16:
        return None
    width, height, _, _, _, wshift, hshift, _ = struct.unpack_from('>HHhhHHHh', header)
    if not 0 < width <= 1024 or not 0 < height <= 1024 or 16 + width * height > length:
        return None
    if wshift != (width - 1).bit_length() or hshift != (height - 1).bit_length():
        return None
    return width, height


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, rows in archives(image, check):
        names = {row[2]: i for i, row in enumerate(rows)}
        palette = unpack(image, base, rows[names['PLAYPAL']], check=check)
        if not palette or len(palette) < 768:
            continue
        for index, row in enumerate(rows):
            if index % 32 == 0:
                check()
            offset, size, name = row
            if size < 5:
                continue
            length = int.from_bytes(image[base+offset:base+offset+4], 'big')
            header = unpack(image, base, row, prefix=16, check=check)
            dims = dimensions(header, length)
            if not dims:
                continue
            width, height = dims
            result.append(dict(offset=base+offset, size=size, kind='image', layout=LAYOUT,
                               confidence='inferred', directory=base, index=index,
                               label=f'{name} · {width}×{height} image', width=width, height=height,
                               reason='The archive member has a bounded image header and declared pixel extent; the full stream is decoded for preview.',
                               preview_settings=dict(source='rom', format='auto', offset=base+offset)))
    return result


def preview(image, asset, selection):
    for base, rows in archives(image):
        if base != asset['directory'] or not 0 <= asset['index'] < len(rows):
            continue
        row = rows[asset['index']]
        if base + row[0] != asset['offset']:
            break
        names = {r[2]: i for i, r in enumerate(rows)}
        palettes = {'TITLEBMP': 'TITLEPAL', 'CREDIT1': 'CREDITPA', 'CREDIT2': 'CREDITPA',
                    'CREDIT3': 'CREDITPA', 'LOGOGT': 'PLOGOGT', 'LOGOID': 'PLOGOID',
                    'LOGOSC': 'PLOGOSC', 'LOGORAV': 'PLOGORAV', 'LEGALS': 'PLEGALS'}
        palette_name = palettes.get(row[2], 'PLAYPAL')
        if palette_name not in names:
            raise formats.AssetError('The image palette is not available in this archive.')
        data = unpack(image, base, row)
        palette = unpack(image, base, rows[names[palette_name]])
        dims = dimensions(data, len(data) if data else 0)
        if not dims or not palette or len(palette) < 768:
            break
        width, height = dims
        rgba = b''.join(palette[i:i+3] + bytes([0 if i == 765 and row[2] != 'TITLEBMP' else 255])
                        for i in range(0, 768, 3))
        pixels = data[16:16+width*height]
        result = formats.preview(pixels + rgba, dict(source='rom', offset=0, format='ci8', width=width,
                                 height=height, palette_offset=len(pixels), palette_format='rgba8888'))
        result['details']['note'] = asset['reason']
        result['settings'] = asset['preview_settings']
        return result
    raise formats.AssetError('The image archive changed or could not be decoded. Scan ROM Explorer again.')

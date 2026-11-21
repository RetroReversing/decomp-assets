"""Borg archive entries and texture previews using their stored dimensions."""

import re
import struct

from .. import formats

_HEADER = struct.Struct('>II')
_ROW = struct.Struct('>HHIII')
_FIRST = re.compile(rb'(?=\x00[\x00-\x0e]\x00[\x00-\x02].{8}\x00{4})', re.S)
_TEXTURE = ('rgba5551-be', 'ia16', 'ci8', 'ia8', 'i8', 'ci4', 'ia4', 'i4', 'rgba8888')
_IMAGE = ('rgba8888', *_TEXTURE[:-1])


def entries(image, check=lambda: None):
    """Find an ordered directory that accounts for its entire preceding data extent."""
    for candidate, match in enumerate(_FIRST.finditer(image)):
        if candidate%4096 == 0:
            check()
        start = match.start()-_HEADER.size
        if start < 0 or start%8:
            continue
        count, size = _HEADER.unpack_from(image, start)
        end = start+_HEADER.size+count*_ROW.size
        base = start-size
        if not (32 <= count <= 32768 and 0 <= base < start and end <= len(image) and base%8 == 0):
            continue
        rows = []
        cursor = 0
        for index in range(count):
            if index%256 == 0:
                check()
            kind, compression, stored, expanded, offset = _ROW.unpack_from(image, start+8+index*_ROW.size)
            if (kind > 14 or compression > 2 or not stored or not expanded
                    or compression == 0 and stored != expanded
                    or offset-cursor not in (0, 8) or offset%8 or offset+stored > size):
                break
            rows.append((kind, compression, stored, expanded, base+offset))
            cursor = offset+stored
        if len(rows) == count and cursor == size:
            return rows
    return []


def _texture(data, kind):
    if kind == 1 and len(data) >= 24:
        code, _, width, height, _, _, _, pixels, palette = struct.unpack_from('>HH4BIII', data)
        if not 0 <= code < len(_TEXTURE) or pixels < 24:
            return None
        mode = _TEXTURE[code]
    elif kind == 8 and len(data) >= 16:
        code, width, height, _, palette, pixels = struct.unpack_from('>4HII', data)
        if not 1 <= code <= len(_IMAGE) or pixels < 16:
            return None
        mode = _IMAGE[code-1]
    else:
        return None
    if not 0 < width <= 1024 or not 0 < height <= 1024:
        return None
    size = ((width*formats._bits(mode)+7)//8)*height
    if pixels+size > len(data):
        return None
    settings = dict(format=mode, offset=pixels, width=width, height=height)
    if mode in ('ci4', 'ci8'):
        palette_size = 32 if mode == 'ci4' else 512
        if (not (24 if kind == 1 else 16) <= palette <= len(data)-palette_size
                or palette < pixels+size and pixels < palette+palette_size):
            return None
        settings.update(palette_offset=palette, palette_format='rgba5551-be')
    return settings


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, (kind, compression, stored, _, offset) in enumerate(entries(image, check)):
        if kind not in (1, 8) or compression:
            continue
        check()
        settings = _texture(image[offset:offset+stored], kind)
        if settings:
            result.append(dict(offset=offset, size=stored, kind='image', layout='borg-texture',
                               confidence='validated', label=f'Borg texture {index}', borg_type=kind,
                               preview_settings=dict(format='auto', source='rom', offset=offset, display_format=settings['format']),
                               width=settings['width'], height=settings['height'], frames=1,
                               palettes=int('palette_offset' in settings),
                               levels=[dict(width=settings['width'], height=settings['height'], offset=0)],
                               reason='The Borg directory bounds the image and its header resolves texels and any palette.'))
    return result


def preview(image, asset, selection):
    offset = asset['offset']
    data = image[offset:offset+asset['size']]
    settings = _texture(data, asset['borg_type'])
    if settings is None:
        raise formats.AssetError('The Borg image changed. Rescan ROM Explorer.')
    result = formats.preview(data, settings)
    result['settings'] = asset['preview_settings']
    return result

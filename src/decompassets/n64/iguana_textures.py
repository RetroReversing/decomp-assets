"""Read indexed bitmap sets from Iguana's RNC method-1 resource containers."""

import re
import struct

from .. import formats, rnc

_MAGIC = b'RNC\x81'
_LABEL = b'x_bitmap : index set'
_INDEX = re.compile(re.escape(_LABEL.ljust(32, b'\0') + struct.pack('<III', 999, 34, 0) + b'~~~~'))
_DATA = _LABEL.ljust(32, b'\0') + struct.pack('<II', 0xcdcdcdcd, 34)
_RECORD = struct.Struct('<9H4I')
_MAX_TEXTURES = 256
_REASON = 'Decoded Iguana bitmap set with matching index records, palette sizes and pixel extents.'


def unpack(image, offset, *, check=lambda:None):
    if not 0 <= offset <= len(image)-20 or image[offset:offset+4] != _MAGIC:
        raise rnc.RncError('Missing Iguana RNC resource header.')
    expanded, packed, chunks = struct.unpack_from('>IIH', image, offset+4)
    start = offset+18+2*chunks
    end = start+packed
    if (not 0 < expanded <= rnc.MAX_OUTPUT or not 2 <= packed <= rnc.MAX_OUTPUT
            or end > len(image) or chunks != (expanded+8191)//8192):
        raise rnc.RncError('Invalid Iguana RNC resource extent.')
    output = bytearray()
    for size, in struct.iter_unpack('>H', image[offset+18:start]):
        check()
        if size < 2 or start+size+(size%2) > end:
            raise rnc.RncError('Iguana RNC page exceeds the resource extent.')
        page_size = min(8192, expanded-len(output))
        output += rnc._method1(image[start:start+size], page_size, max_chunks=1)
        start += size+(size%2)
    return bytes(output), end-offset


def _records(data, start, count, base):
    textures = []
    for offset in range(start, start+count*_RECORD.size, _RECORD.size):
        _, _, _, _, frames, width, height, pitch, rows, size, colors, palette, pixels = _RECORD.unpack_from(data, offset)
        mode = {32:'ci4', 512:'ci8'}.get(colors)
        if (not mode or frames != 1 or not width <= pitch <= formats.MAX_DIMENSION
                or not height <= rows <= formats.MAX_DIMENSION
                or not 1 <= width <= formats.MAX_DIMENSION or not 1 <= height <= formats.MAX_DIMENSION
                or width*height > formats.MAX_PIXELS
                or size != ((pitch+1)//2 if mode=='ci4' else pitch)*rows
                or pixels != palette+colors or base+pixels+size > len(data)):
            return []
        settings = dict(format=mode, width=width, height=height, offset=base+pixels,
                        palette_offset=base+palette, palette_format='rgba5551-be')
        stride = (pitch+1)//2 if mode=='ci4' else pitch
        textures.append(dict(preview_settings=settings, frames=1, palettes=1, stride=stride))
    return textures


def layout(data):
    if data[:8] != b'!IgUaNa!':
        return []
    items = []
    for index in _INDEX.finditer(data):
        start = index.end()
        limit = min(len(data), start+_MAX_TEXTURES*_RECORD.size+6+len(_DATA))
        marker = data.find(_DATA, start, limit)
        if marker < 0 or marker+288 > len(data):
            continue
        count, = struct.unpack_from('<I', data, marker+40)
        finish = start+count*_RECORD.size
        if (not 1 <= count <= _MAX_TEXTURES or finish >= marker
                or data[finish:marker] not in (b'~~', b'~~~~', b'~~~~~~')
                or data[marker+272:marker+288] != struct.pack('<III', 999, 1, 0)+b'~~~~'):
            continue
        items.extend(_records(data, start, count, marker+288))
    return items


def regions(image, *, check=lambda:None, progress=lambda _:None):
    assets = []
    expanded = 0
    for hit in re.finditer(re.escape(_MAGIC), image):
        check()
        offset = hit.start()
        if offset%4 or offset+20 > len(image):
            continue
        size = int.from_bytes(image[offset+4:offset+8], 'big')
        if not 0 < size <= rnc.MAX_OUTPUT:
            continue
        if expanded+size > 48*1024*1024:
            break
        expanded += size
        try:
            data, extent = unpack(image, offset, check=check)
        except rnc.RncError:
            continue
        items = layout(data)
        if items:
            first = items[0]['preview_settings']
            display_format = ' / '.join(sorted({item['preview_settings']['format'].upper() for item in items}))
            assets.append(dict(offset=offset, size=extent, kind='image', media='image',
                               label='Iguana indexed bitmap set', confidence='validated', reason=_REASON,
                               layout='iguana-indexed-bitmaps', textures=items, frames=1, palettes=1,
                               preview_settings=dict(format='auto', source='rom', offset=offset,
                                                     display_format=display_format,
                                                     width=first['width'], height=first['height'])))
    return assets


def preview(image, asset, selection):
    try:
        data, _ = unpack(image, asset['offset'])
        items = layout(data)
    except rnc.RncError as exc:
        raise formats.AssetError('The Iguana resource could not be decoded. Rescan ROM Explorer.') from exc
    if not items:
        raise formats.AssetError('The Iguana bitmap layout no longer matches. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items)-1)
    for key in ('frame', 'palette', 'mip'):
        formats.integer(selection.get(key, 0), key.capitalize(), 0, 0)
    settings = dict(items[index]['preview_settings'])
    begin, end = settings['palette_offset'], settings['offset']
    swap = bytearray(data[begin:end])
    swap[::2], swap[1::2] = swap[1::2], swap[::2]
    stride = items[index]['stride']
    width = (settings['width']+1)//2 if settings['format']=='ci4' else settings['width']
    pixels = b''.join(data[at:at+width] for at in range(end,end+stride*settings['height'],stride))
    result = formats.preview(bytes(swap)+pixels, dict(settings, palette_offset=0, offset=len(swap)))
    result['details'].update(texture=index, note=_REASON)
    result['settings'] = dict(asset['preview_settings'], texture=index)
    return result

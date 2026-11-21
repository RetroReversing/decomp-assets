"""Stage texture banks with MPF run-length compressed palette and pixel data."""

import re
import struct

from .. import formats

TEXTURE = 'mpf-stage-textures'
_MARKER = re.compile(rb'\x01\x0a\0\0')
_HEADER = struct.Struct('>6I')
_TEXTURE = struct.Struct('>B3xHH4xII')
_COMPRESSED = struct.Struct('>BBHII')


def _unpack(data, size, bits):
    cursor = 0
    out = bytearray()
    units = size * 8 // bits

    def read(width):
        nonlocal cursor
        if cursor + width > len(data) * 8:
            raise ValueError
        index, shift = divmod(cursor, 8)
        cursor += width
        value = data[index] >> shift
        if shift + width > 8:
            value |= data[index + 1] << (8 - shift)
        return value & ((1 << width) - 1)

    try:
        while True:
            flag = read(8)
            if flag == 255:
                if (cursor + 7) // 8 != len(data):
                    return
                if bits == 8 and len(out) == units:
                    return out
                if bits == 4 and len(out) in (units, units - 1):
                    if len(out) < units:
                        out.append(0)
                    return bytearray(out[i] | out[i + 1] << 4 for i in range(0, units, 2))
                return
            count = (flag & 127) + 1
            if count > units - len(out):
                return
            if flag & 128:
                out.extend(bytes([read(bits)]) * count)
            else:
                out.extend(read(bits) for _ in range(count))
    except ValueError:
        return


def _items(image, offset, end):
    if not 0 <= offset <= end - 60 <= len(image) - 60:
        return []
    version, groups, size, decoded_size, count, table = _HEADER.unpack_from(image, offset)
    if not (version == 0x010a0000 and 0 < groups <= 256 and table == 60 + groups * 12
            and 0 < count <= 256 and table + count * 20 <= size == end - offset <= decoded_size <= 0x800000):
        return []
    source_end, dest_end = table + count * 20, 0
    items = []
    for index in range(count):
        packing, width, height, source, dest = _TEXTURE.unpack_from(image, offset + table + 20 * index)
        if not (packing in (0, 1) and 0 < width <= 512 and 0 < height <= 512
                and source_end <= source <= size - _COMPRESSED.size and dest >= dest_end):
            return []
        palette = 512 if packing else 32
        columns = 8 if packing else 16
        stride = ((width + columns - 1) // columns) * 8
        pixel_bytes = (width + (not packing)) // (1 if packing else 2)
        codec, reserved, header, packed, raw = _COMPRESSED.unpack_from(image, offset + source)
        if not (codec in (16, 20) and reserved == 0 and header == _COMPRESSED.size
                and header < packed <= size - source and raw == palette + stride * height
                and dest + raw <= decoded_size):
            return []
        source_end, dest_end = source + packed, dest + raw
        fmt = 'ci8' if packing else 'ci4'
        items.append(dict(label=f'{fmt.upper()} {width}×{height}', frames=1, palettes=1,
                          levels=[dict(width=width, height=height, offset=0)],
                          preview_settings=dict(format=fmt, width=width, height=height, offset=palette,
                                                palette_offset=0, palette_format='rgba5551-be'),
                          source=source + header, end=source_end, bits=8 if codec == 16 else 4,
                          raw=raw, stride=stride, row_bytes=pixel_bytes))
    return items


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _MARKER.finditer(image):
        check()
        offset = match.start()
        if offset % 4 or offset + 60 > len(image):
            continue
        size = struct.unpack_from('>I', image, offset + 8)[0]
        items = _items(image, offset, offset + size)
        if items:
            result.append(dict(offset=offset, size=size, kind='image', layout=TEXTURE, confidence='validated',
                               label=f'{len(items)} stage textures', textures=items, texture_count=len(items),
                               frames=1, palettes=1, levels=items[0]['levels'],
                               reason='Stage descriptors and compressed sizes agree with every palette and row stride.',
                               preview_settings=dict(source='rom', format='auto', offset=offset)))
    return result


def preview(image, asset, selection):
    offset = asset['offset']
    items = _items(image, offset, offset + asset['size'])
    if not items:
        raise formats.AssetError('The stage texture bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    item = items[index]
    data = _unpack(image[offset + item['source']:offset + item['end']], item['raw'], item['bits'])
    if data is None:
        raise formats.AssetError('The stage texture has invalid run lengths.')
    options = item['preview_settings']
    palette = options['offset']
    stride = item['stride']
    pixels = b''.join(data[start:start + item['row_bytes']] for start in range(palette, len(data), stride))
    result = formats.preview(data[:palette] + pixels, options)
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
    return result

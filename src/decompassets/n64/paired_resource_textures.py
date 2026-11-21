"""Textures referenced by local RDP commands in paired cartridge resources."""

import re
import struct

from .. import formats
from . import paired_resources

LAYOUT = 'paired-resource-textures'
_COMMAND = struct.Struct('>2I')
_LOAD = re.compile(rb'\xfd.{7}\xf5.{7}\xe6.{7}\xf3.{7}\xe7.{7}\xf5.{7}\xf2.{7}', re.DOTALL)
_PALETTE = re.compile(rb'\xfd\x10\0\0....\xe8\0{7}\xf5\0\x01\0....\xe6\0{7}\xf0.{7}', re.DOTALL)
_FORMATS = {
    (0, 2): 'rgba5551-be', (0, 3): 'rgba8888',
    (2, 0): 'ci4', (2, 1): 'ci8',
    (3, 0): 'ia4', (3, 1): 'ia8', (3, 2): 'ia16',
    (4, 0): 'i4', (4, 1): 'i8',
}


def _offset(pointer, size, limit):
    segment, offset = divmod(pointer, 0x1000000)
    if segment == 6 and offset % 8 == 0 and offset + size <= limit:
        return offset
    return None


def _palette(data, start, stop, kind, palette_index):
    # Some lists load a full TLUT even for a CI4 tile. The render tile then
    # selects one 16-entry palette from that load with its palette field.
    command = _PALETTE.match(data, start)
    if not command:
        return None
    _, pointer = _COMMAND.unpack_from(data, start)
    _, value = _COMMAND.unpack_from(data, start + 32)
    count = ((value >> 14) & 1023) + 1
    entries = 16 if kind == 'ci4' else 256
    first_entry = palette_index * 16 if kind == 'ci4' else 0
    if first_entry + entries > count:
        return None
    return _offset(pointer + first_entry * 2, entries * 2, stop)


def textures(data):
    found = {}
    for match in _LOAD.finditer(data):
        start, end = match.span()
        if start % 8:
            continue
        source, load, sync, block, pipe, tile, bounds = _COMMAND.iter_unpack(match[0])
        if sync != (0xe6000000, 0) or pipe != (0xe7000000, 0) or bounds[0] != 0xf2000000:
            continue
        kind, size = (tile[0] >> 21) & 7, (tile[0] >> 19) & 3
        fmt = _FORMATS.get((kind, size))
        if not fmt or bounds[1] & 0x003003 or (tile[1] >> 24) != (bounds[1] >> 24):
            continue
        width, height = ((bounds[1] >> 14) & 1023) + 1, ((bounds[1] >> 2) & 1023) + 1
        stride = (width * (4 << size) + 7) // 8
        pitch = (tile[0] >> 9) & 511
        if pitch * 8 != (stride // 2 if size == 3 else stride):
            continue
        byte_count = stride * height
        load_size = (block[1] >> 12 & 0xfff) + 1
        load_bits = 4 << (load[0] >> 19 & 3)
        if load_size * load_bits < byte_count * 8:
            continue
        offset = _offset(source[1], byte_count, start)
        if offset is None:
            continue
        settings = dict(format=fmt, width=width, height=height, offset=offset)
        palette = None
        if kind == 2:
            palette = _palette(data, end, start, fmt, (tile[1] >> 20) & 15)
            if palette is None:
                continue
            settings.update(palette_offset=palette, palette_format='rgba5551-be')
        key = offset, width, height, fmt, palette
        found[key] = dict(label=f'{fmt.upper()} {width}×{height} · 0x{offset:X}', size=byte_count,
                          frames=1, palettes=int(palette is not None),
                          levels=[dict(width=width, height=height, offset=0)], preview_settings=settings)
    return list(found.values())


def asset(offset, size, directory, index, items):
    first = items[0]
    return dict(offset=offset, size=size, kind='image', layout=LAYOUT, confidence='validated',
                directory=directory, label=f'Resource {index} · {len(items)} textures',
                textures=items, texture_count=len(items), frames=1, palettes=first['palettes'],
                levels=first['levels'],
                preview_settings=dict(first['preview_settings'], offset=offset, source='rom'),
                reason='Local RDP commands give the format, row pitch, dimensions and palette.')


def preview(image, asset, selection):
    offset = asset['offset']
    decoded = paired_resources.unpack(image, offset, asset['size'])
    if not decoded or not (items := textures(decoded)):
        raise formats.AssetError('The compressed texture resource changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    result = formats.preview(decoded, items[index]['preview_settings'])
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(source='rom', format='auto', offset=offset, texture=index, frame=0, palette=0, mip=0)
    return result

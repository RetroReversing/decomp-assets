"""Named texture tables in Iain resources."""

import re
import struct

from .. import formats
from . import iain

LAYOUT = 'iain-texture-bank'
_NAME = re.compile(rb'[ -~]{1,64}\0')
_FORMATS = {2: ('i8', 1), 3: ('ia8', 1), 4: ('rgba5551-be', 2), 5: ('rgba8888', 4)}


def textures(data):
    count = int.from_bytes(data[:4], 'big')
    if not 0 < count <= 200:
        return []
    position = 4
    items = []
    for _ in range(count):
        name = _NAME.match(data, position)
        if not name or name.end() + 6 > len(data):
            return []
        width, height, mode = struct.unpack_from('>3H', data, name.end())
        if (mode >> 5 or (mode & 7) not in _FORMATS
                or not 0 < width <= 2048 or not 0 < height <= 2048):
            return []
        fmt, stride = _FORMATS[mode & 7]
        offset = name.end() + 6
        size = width * height * stride
        position = offset + size
        if position > len(data):
            return []
        items.append(dict(label=name[0][:-1].decode('ascii'), size=size, frames=1, palettes=0,
                          levels=[dict(width=width, height=height, offset=0)],
                          preview_settings=dict(format=fmt, width=width, height=height, offset=offset)))
    return items if position == len(data) else []


def asset(offset, size, data):
    if not (items := textures(data)):
        return None
    first = items[0]
    label = first['label'] if len(items) == 1 else f"{first['label']} · {len(items)} textures"
    settings = dict(first['preview_settings'], offset=offset, source='rom')
    return dict(offset=offset, size=size, kind='image', layout=LAYOUT, confidence='validated',
                label=label, textures=items, texture_count=len(items), frames=1, palettes=0,
                levels=first['levels'], preview_settings=settings,
                reason='The archive expands to a complete table of named textures with exact pixel spans.')


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    decoded = iain.unpack(image, offset, offset + size)
    if not decoded or decoded[1] != size or not (items := textures(decoded[0])):
        raise formats.AssetError('The archived texture table changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    result = formats.preview(decoded[0], items[index]['preview_settings'])
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(source='rom', format='auto', offset=offset, texture=index, frame=0, palette=0, mip=0)
    return result

"""Locally addressed display lists in bounded MIO0 graphics resources."""

import re
import struct

from .. import formats
from . import display_meshes

MODEL = 'mio0-local-models'
IMAGE = 'mio0-local-images'
_SEGMENTS = {8: 0, 9: 0}


def meshes(data):
    result, end = [], 0
    for at in range(0, len(data)-8, 8):
        if at < end or data[at] not in (1, 4):
            continue
        parsed = display_meshes.geometry(data, at, len(data), _SEGMENTS)
        if parsed and len(parsed[2]) >= 3:
            end, vertices, faces = parsed
            result.append(dict(name=f'Mesh {len(result)+1}', offset=at, size=end-at,
                               vertices=len(vertices), triangles=len(faces)))
    return result


def textures(data):
    result = {}
    for at in range(0, len(data)-8, 8):
        word, value = struct.unpack_from('>2I', data, at)
        if word >> 24 != 0xfd or value >> 24 not in _SEGMENTS or (word >> 21) & 7 or (word >> 19) & 3 != 2:
            continue
        offset = value & 0xffffff
        loaded = tile = False
        for pos in range(at+8, min(at+160, len(data)-7), 8):
            command, arg = struct.unpack_from('>2I', data, pos)
            operation = command >> 24
            if operation in (0xfd, 0xdf, 0xb8):
                break
            if operation == 0xf5 and not (command >> 21) & 7 and (command >> 19) & 3 == 2:
                tile = True
            if operation == 0xf3:
                loaded = True
            if operation == 0xf2 and loaded and tile:
                width, height = ((arg >> 14) & 1023) + 1, ((arg >> 2) & 1023) + 1
                if 2 <= width <= 256 and 2 <= height <= 256 and offset + width*height*2 <= len(data):
                    result[offset] = dict(offset=offset, width=width, height=height)
                break
    return list(result.values())


def regions(image, *, images=None, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'MIO0', image):
        at = match.start()
        if at % 4 or at+16 > len(image) or not 4096 <= int.from_bytes(image[at+4:at+8], 'big') <= formats.MAX_BYTES:
            continue
        try:
            data, _, size = formats.unpack_extent(image[at:])
        except formats.AssetError:
            continue
        items = meshes(data)
        if not items:
            continue
        pictures = textures(data)
        if images is not None and pictures:
            images.append(dict(offset=at, size=size, kind='image', layout=IMAGE, frames=len(pictures),
                               width=pictures[0]['width'], height=pictures[0]['height'], confidence='validated',
                               label=f'Compressed texture resource ({len(pictures)} images)',
                               reason='Bounded local display lists load these direct-color textures.',
                               preview_settings=dict(format='auto', source='rom', offset=at, frame=0)))
        result.append(dict(offset=at, size=size, kind='3d model', media='model', layout=MODEL,
                           label=f'Compressed model resource ({len(items)} meshes)', confidence='validated',
                           meshes=items, nodes=len(items), triangles=sum(item['triangles'] for item in items),
                           reason='Closed display lists resolve vertex loads inside the compressed resource.',
                           preview_settings=dict(format='auto', source='rom', offset=at, mesh=0)))
        check()
    return result


def _data(image, asset):
    try:
        data, _, size = formats.unpack_extent(image[asset['offset']:asset['offset']+asset['size']])
    except formats.AssetError:
        raise formats.AssetError('The compressed resource changed. Rescan ROM Explorer.') from None
    if size != asset['size']:
        raise formats.AssetError('The compressed resource changed. Rescan ROM Explorer.')
    return data


def preview(image, asset, selection):
    data = _data(image, asset)
    items = meshes(data)
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(items)-1)
    local = dict(items[index], address_maps=list(_SEGMENTS.items()), label=asset['label'],
                 preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(data, local, selection)


def preview_image(image, asset, selection):
    data = _data(image, asset)
    items = textures(data)
    index = formats.integer(selection.get('frame', 0), 'Frame', 0, len(items)-1)
    item = items[index]
    result = formats.preview(data, dict(format='rgba5551-be', **item))
    result['settings'] = dict(asset['preview_settings'], frame=index)
    result['details']['note'] = asset['reason']
    return result

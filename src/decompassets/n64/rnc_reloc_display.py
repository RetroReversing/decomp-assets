"""Relocatable display lists stored in bounded RNC resources."""
import re
import struct

from .. import formats, rnc
from . import display_meshes

LAYOUT = 'rnc-reloc-display'


def mesh(data):
    if len(data) < 32:
        return None
    start, count = struct.unpack_from('>II', data)
    if not 2 <= count <= 512 or start % 8 or not 8+count*4 <= start < len(data):
        return None
    relocations = struct.unpack_from(f'>{count}I', data, 8)
    if (relocations[0] != start+4 or any(a >= b for a, b in zip(relocations, relocations[1:]))
            or any(p % 8 != 4 or p+4 > len(data) for p in relocations)
            or any(data[p-4] not in (0x04, 0xfd) or int.from_bytes(data[p:p+4], 'big') >= start
                   for p in relocations)):
        return None
    parsed = display_meshes.geometry(data, start, len(data), {0: 0}, vertex_end=start)
    if parsed is None or parsed[0] != len(data):
        return None
    return parsed


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'RNC\x01', image):
        check()
        at = match.start()
        try:
            data, size = rnc.unpack_at(image, at)
        except rnc.RncError:
            continue
        row = mesh(data)
        if row is None:
            continue
        _, vertices, faces = row
        result.append(dict(offset=at, size=size, kind='3d model', media='model', layout=LAYOUT,
                           label='RNC display-list mesh', confidence='validated', nodes=1,
                           meshes=[dict(name='Geometry', vertices=len(vertices), triangles=len(faces))],
                           vertices=len(vertices), triangles=len(faces),
                           reason='The relocation table and closed display list bound its vertices and triangles; placement and materials are separate.',
                           preview_settings=dict(format='auto', source='rom', offset=at, mesh=0)))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    try:
        data, _ = rnc.unpack_at(image, asset['offset'])
    except rnc.RncError as error:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.') from error
    row = mesh(data)
    if row is None:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.')
    start = int.from_bytes(data[:4], 'big')
    record = dict(offset=start, size=len(data)-start, address_maps={0: 0}, vertex_end=start,
                  label=asset['label'], preview_settings=asset['preview_settings'])
    return display_meshes.preview(data, record, selection)

IMAGE = 'rnc-reloc-indexed-image'


def tile(data):
    if mesh(data) is None:
        return None
    start = int.from_bytes(data[:4], 'big')
    if start+104 > len(data):
        return None
    commands = [struct.unpack_from('>II', data, start+i*8) for i in range(13)]
    if [word >> 24 for word, _ in commands[:12]] != [0xfd, 0xf5, 0xe6, 0xf3, 0xe7, 0xf5, 0xf2, 0xfd, 0xe8, 0xf5, 0xe6, 0xf0]:
        return None
    pixels, palette = commands[0][1], commands[7][1]
    bounds = commands[6][1]
    width, height = ((bounds >> 12) & 0xfff)//4+1, (bounds & 0xfff)//4+1
    size = (width*height+1)//2
    if (commands[0][0] != 0xfd100000 or commands[7][0] != 0xfd100000
            or commands[11][1] != 0x0703c000 or not 4 <= width <= 256 or not 4 <= height <= 256
            or palette+32 > start or pixels+size > start or palette+32 > pixels
            or pixels < 8+int.from_bytes(data[4:8], 'big')*4):
        return None
    return dict(offset=pixels, width=width, height=height, palette_offset=palette,
                format='ci4', palette_format='rgba5551-be', source='rom')


def image_regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'RNC\x01', image):
        check()
        at = match.start()
        try:
            data, size = rnc.unpack_at(image, at)
        except rnc.RncError:
            continue
        settings = tile(data)
        if settings is None:
            continue
        result.append(dict(offset=at, size=size, kind='image', media='image', layout=IMAGE,
                           label='RNC indexed texture', confidence='inferred',
                           reason='The display list loads a 16-color palette and bounded pixel data; colors are inferred as RGBA5551.',
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def image_preview(image, asset, selection):
    try:
        data, _ = rnc.unpack_at(image, asset['offset'])
    except rnc.RncError as error:
        raise formats.AssetError('The compressed texture changed. Rescan ROM Explorer.') from error
    settings = tile(data)
    if settings is None:
        raise formats.AssetError('The compressed texture changed. Rescan ROM Explorer.')
    result = formats.preview(data, settings)
    result['settings'] = asset['preview_settings']
    result['note'] = asset['reason']
    return result

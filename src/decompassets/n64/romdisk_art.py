"""Textures and local display-list meshes in chunked ROM disk members."""
import struct

from .. import formats
from . import display_meshes, romdisk

IMAGE = 'romdisk-chunk-images'
MODEL = 'romdisk-chunk-models'


def chunks(data):
    if len(data) < 8:
        return {}
    at, count = struct.unpack_from('>II', data)
    if not 1 <= count <= 32 or at < 8 or at+count*12 != len(data):
        return {}
    rows = {}
    for i in range(count):
        tag, offset, size = struct.unpack_from('>4sII', data, at+i*12)
        if tag in rows or offset < 8 or offset > at:
            return {}
        rows[tag] = (offset, size)
    return rows


def textures(data, sections):
    if b'TEXR' not in sections or b'TXHD' not in sections:
        return []
    tex, size = sections[b'TEXR']
    headers, count = sections[b'TXHD']
    if not 1 <= count <= 1024 or tex+size > len(data) or headers+count*24 > len(data):
        return []
    result = []
    offsets = [struct.unpack_from('>I', data, headers+i*24)[0] for i in range(count)]
    if offsets != sorted(set(offsets)) or offsets[-1] >= size:
        return []
    for i, offset in enumerate(offsets):
        at = headers+i*24
        kind = data[at+11]
        width, height = struct.unpack_from('>HH', data, at+12)
        end = offsets[i+1] if i+1 < count else size
        if not 1 <= width <= 1024 or not 1 <= height <= 1024:
            return []
        if kind == 5 and width*height*4 <= end-offset:
            settings = dict(format='rgba8888', offset=tex+offset, width=width, height=height)
        elif kind == 4 and width*height+512 <= end-offset:
            settings = dict(format='ci8', offset=tex+offset, width=width, height=height,
                            palette_offset=tex+offset+width*height, palette_format='rgba5551-be')
        else:
            continue
        result.append(settings)
    return result


def meshes(data, sections):
    if any(tag not in sections for tag in (b'OBHD', b'OBJS', b'TXLD')):
        return []
    headers, count = sections[b'OBHD']
    obj, size = sections[b'OBJS']
    materials, material_size = sections[b'TXLD']
    if (not 1 <= count <= 4096 or headers+count*56 > len(data) or obj+size > len(data)
            or materials+material_size > len(data)):
        return []
    def material(w0, w1):
        return w0 >> 24 == 0xde and materials <= w1 < materials+material_size and not (w1-materials)%16
    result, seen = [], set()
    for i in range(count):
        dl, vertex = struct.unpack_from('>II', data, headers+i*56+12)
        if (dl, vertex) in seen or not obj <= vertex < dl < obj+size:
            continue
        seen.add((dl, vertex))
        parsed = display_meshes.geometry(data, dl, obj+size, {14: vertex}, extra_state=material,
                                         vertex_end=dl, vertex_flag_mask=0x8000)
        if parsed:
            end, points, faces = parsed
            result.append(dict(name=f'Mesh {i+1}', offset=dl, size=end-dl, vertex=vertex,
                               vertices=len(points), triangles=len(faces)))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for group in romdisk.members(image, check):
        for member in group:
            check()
            if not member['name'].lower().endswith('/objects.wad') or member['decoded_size'] > formats.MAX_BYTES:
                continue
            try:
                data = romdisk.unpack(image, member)
            except formats.AssetError:
                continue
            sections = chunks(data)
            if not sections:
                continue
            items = textures(data, sections)
            if items:
                listed = [dict(label=f'Texture {i+1}', width=x['width'], height=x['height'], frames=1, palettes=1 if x['format'] == 'ci8' else 0,
                               palette_entries=[256] if x['format'] == 'ci8' else [],
                               levels=[dict(width=x['width'], height=x['height'], offset=0)], preview_settings=x)
                          for i, x in enumerate(items)]
                found.append(dict(**member, kind='image', media='image', layout=IMAGE, confidence='validated',
                                  label=member['name']+' textures', textures=listed, texture_count=len(listed), frames=1,
                                  reason='Chunk and texture headers bound pixel data and any palette.',
                                  preview_settings=dict(format='auto', source='rom', offset=member['offset'], texture=0)))
            items = meshes(data, sections)
            if items:
                found.append(dict(**member, kind='3d model', media='model', layout=MODEL, confidence='validated',
                                  label=member['name']+' models', meshes=items, nodes=len(items),
                                  triangles=sum(x['triangles'] for x in items),
                                  reason='Chunk headers bound display lists whose vertex loads and triangle indices resolve. Placement and materials are separate.',
                                  preview_settings=dict(format='auto', source='rom', offset=member['offset'], mesh=0)))
    return found


def preview(image, asset, selection):
    data = romdisk.unpack(image, asset)
    sections = chunks(data)
    if asset['layout'] == IMAGE:
        formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
        formats.integer(selection.get('palette', 0), 'Palette', 0, 0)
        rows = textures(data, sections)
        if not rows:
            raise formats.AssetError('The texture bank changed. Rescan ROM Explorer.')
        index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(rows)-1)
        result = formats.preview(data, rows[index])
        result['settings'] = dict(asset['preview_settings'], texture=index)
        result['details']['note'] = asset['reason']
        return result
    rows = meshes(data, sections)
    if not rows:
        raise formats.AssetError('The model bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(rows)-1)
    record = rows[index]
    start, size = sections[b'TXLD']
    material = lambda w0, w1: w0 >> 24 == 0xde and start <= w1 < start+size and not (w1-start)%16
    record = dict(record, label=asset['label'], address_maps={14: record['vertex']}, vertex_end=record['offset'],
                  preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(data, record, selection, extra_state=material, vertex_flag_mask=0x8000)

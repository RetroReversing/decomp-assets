"""Actor and object display lists in relative resource tables."""

import struct

from .. import formats
from . import display_meshes, relative_directory, relative_models, relative_textures

LAYOUT = 'relative-directory-object-models'


def meshes(data, table):
    if len(data) < 0x50:
        return []
    if table == 4:
        start, stop = struct.unpack_from('>I', data, 0x40)[0], struct.unpack_from('>I', data, 0x48)[0]
        vertex_start, vertex_end = stop, struct.unpack_from('>I', data, 0x4c)[0]
    elif table == 5:
        base, pointer = struct.unpack_from('>II', data)
        stop = 0x28 + pointer - base
        if not 0 <= stop <= len(data) - 4:
            return []
        start = 0x28 + struct.unpack_from('>I', data, stop)[0] - base
        vertex_start, vertex_end = 0x28, start
    else:
        return []
    if not (0 <= start < stop <= len(data) and 0 <= vertex_start < vertex_end <= len(data)
            and start % 8 == 0 and vertex_start % 8 == 0):
        return []
    result, previous_end = [], start
    for pos in range(start, stop - 7, 8):
        if pos < previous_end:
            continue
        w0, w1 = struct.unpack_from('>II', data, pos)
        if w0 >> 24 != 1 or (segment := w1 >> 24) > 15:
            continue
        found = display_meshes.geometry(data, pos, stop, {segment: vertex_start}, vertex_end=vertex_end,
                                        extra_state=relative_models._cull, vertex_flag_mask=0xffff)
        if found:
            end, vertices, faces = found
            result.append(dict(label=f'Local mesh {len(result) + 1}', model_offset=pos, model_size=end-pos,
                               vertices=len(vertices), triangles=len(faces), segment=segment,
                               vertex_start=vertex_start, vertex_end=vertex_end))
            previous_end = end
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, tables in relative_directory.tables(image, check=check):
        for table in (4, 5):
            for index in range(len(tables[table]) - 1):
                if index % 16 == 0:
                    check()
                member = relative_textures._member(image, base, tables[table], index)
                if not member or not (entries := meshes(member[2], table)):
                    continue
                start, end, _ = member
                result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                                   directory=base, table=table, index=index, confidence='validated', meshes=entries,
                                   nodes=len(entries), label=f'{len(entries)} local object meshes',
                                   reason='The model header bounds its vertex array and each closed list resolves its triangles.',
                                   preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    for base, tables in relative_directory.tables(image):
        if base != asset['directory']:
            continue
        member = relative_textures._member(image, base, tables[asset['table']], asset['index'])
        if member and member[:2] == (asset['offset'], asset['offset'] + asset['size']):
            entries = meshes(member[2], asset['table'])
            if not entries:
                break
            index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(entries)-1)
            entry = entries[index]
            local = dict(offset=entry['model_offset'], size=entry['model_size'],
                         address_maps={entry['segment']: entry['vertex_start']}, vertex_end=entry['vertex_end'],
                         label=entry['label'], preview_settings=dict(asset['preview_settings'], mesh=index))
            return display_meshes.preview(member[2], local, selection, extra_state=relative_models._cull, vertex_flag_mask=0xffff)
    raise formats.AssetError('The compressed object model changed. Scan ROM Explorer again.')

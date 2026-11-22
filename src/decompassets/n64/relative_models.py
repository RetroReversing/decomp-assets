"""Local display-list geometry in compressed relative-table resources."""

import struct

from .. import formats
from . import display_meshes, relative_directory, relative_textures

LAYOUT = 'relative-directory-models'


def _cull(w0, w1):
    # F3DEX2 cull commands affect visibility, not local vertex coordinates.
    return w0 >> 24 == 3 and not (w0 & 0xff0000 or w1 & 0xffff0000)


def meshes(data):
    if len(data) < 0x74:
        return []
    lists, vertices = struct.unpack_from('>II', data, 0x34)
    end = struct.unpack_from('>I', data, 0x40)[0]
    if not (0x74 <= lists < vertices <= end <= len(data) and lists % 8 == vertices % 8 == 0):
        return []
    chunk_start, chunk_end, expansion = struct.unpack_from('>3I', data, 0x68)
    if not (0 <= chunk_start <= chunk_end <= len(data) and (chunk_end-chunk_start) % 52 == 0):
        return []
    chunks = []
    for at in range(chunk_start, chunk_end, 52):
        row = struct.unpack_from('>10I', data, at + 12)
        vertex_offset, vertex_size = row[-2:]
        if vertex_offset + vertex_size > end - vertices:
            return []
        for start, size in zip(row[0:8:2], row[1:8:2]):
            if size:
                if start + size > vertices-lists:
                    return []
                chunks.append((lists+start, lists+start+size, vertices+vertex_offset, vertices+vertex_offset+vertex_size))
    expansions = set()
    if expansion and expansion + 4 <= len(data):
        count = struct.unpack_from('>I', data, expansion)[0]
        if count <= 1024 and expansion + 4 + count * 16 <= len(data):
            expansions = {lists + struct.unpack_from('>I', data, expansion+4+i*16+8)[0] for i in range(count)}
    result, previous_end = [], lists
    for pos in range(lists, vertices - 7, 8):
        if pos < previous_end:
            continue
        w0, w1 = struct.unpack_from('>II', data, pos)
        if w0 >> 24 != 1 or (space := w1 >> 24) > 15:
            continue
        owners = {(start, stop) for lo, hi, start, stop in chunks if lo <= pos < hi}
        if len(owners) > 1:
            continue
        if owners:
            vertex_start, vertex_end = next(iter(owners))
        elif not chunks or any(at <= pos < at + 8 for at in expansions):
            vertex_start, vertex_end = vertices, end
        else:
            continue
        geometry = display_meshes.geometry(data, pos, vertices, {space: vertex_start}, vertex_end=vertex_end,
                                          extra_state=_cull, vertex_flag_mask=0xffff)
        if geometry:
            stop, points, faces = geometry
            result.append(dict(label=f'Local mesh {len(result) + 1}', model_offset=pos,
                               model_size=stop-pos, vertices=len(points), triangles=len(faces),
                               segment=space, vertex_start=vertex_start, vertex_end=vertex_end))
            previous_end = stop
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, tables in relative_directory.tables(image, check=check):
        for index in range(len(tables[1]) - 1):
            if index % 16 == 0:
                check()
            member = relative_textures._member(image, base, tables[1], index)
            if not member or not (entries := meshes(member[2])):
                continue
            start, end, _ = member
            result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                               directory=base, index=index, confidence='validated', meshes=entries,
                               nodes=len(entries), label=f'{len(entries)} local display-list meshes',
                               reason='The resource header bounds its vertex array and each closed list resolves its triangles.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    for base, tables in relative_directory.tables(image):
        if base != asset['directory']:
            continue
        member = relative_textures._member(image, base, tables[1], asset['index'])
        if member and member[:2] == (asset['offset'], asset['offset'] + asset['size']):
            entries = meshes(member[2])
            if not entries:
                break
            index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(entries)-1)
            entry = entries[index]
            local = dict(offset=entry['model_offset'], size=entry['model_size'],
                         address_maps={entry['segment']: entry['vertex_start']}, vertex_end=entry['vertex_end'],
                         label=entry['label'], preview_settings=dict(asset['preview_settings'], mesh=index))
            return display_meshes.preview(member[2], local, selection, extra_state=_cull, vertex_flag_mask=0xffff)
    raise formats.AssetError('The compressed model resource changed. Scan ROM Explorer again.')

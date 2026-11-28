"""Closed display-list meshes in output-sized LZSS sectioned resources."""

import struct

from .. import formats
from . import display_meshes, lz_indexed_images

LAYOUT = 'lz-section-meshes'
_SIGNATURE = bytes.fromhex('edf005')
_LIMIT = formats.MAX_BYTES


def meshes(data, check=lambda: None):
    """Read local lists only when the five-section directory bounds their vertices."""
    if len(data) < 48 or int.from_bytes(data[:4], 'big') != 5:
        return []
    sections = [struct.unpack_from('>II', data, 4 + 8*i) for i in range(5)]
    if (sections[0][0] != 48 or any((start | size) % 8 for start, size in sections)
            or any(a[0]+a[1] != b[0] for a, b in zip(sections, sections[1:]))
            or sum(sections[-1]) != len(data)):
        return []
    first, length = sections[0]
    vertex, vertex_size = sections[1]
    if not length or not vertex_size:
        return []
    result, cursor, end = [], first, first+length
    while cursor < end and len(result) < 512:
        check()
        parsed = display_meshes.geometry(data, cursor, end, {2: vertex}, vertex_end=vertex+vertex_size,
                                         vertex_flag_mask=0xffff)
        if parsed:
            stop, vertices, faces = parsed
            result.append(dict(label=f'Mesh {len(result)+1}', start=cursor, size=stop-cursor,
                               vertices=len(vertices), triangles=len(faces)))
            cursor = stop
            continue
        # An unsupported list may include external calls or matrices. Only
        # restart after its explicit terminator, never halfway through a list.
        while cursor < end and data[cursor:cursor+8] != b'\xdf\0\0\0\0\0\0\0':
            cursor += 8
        cursor += 8
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result, cursor, attempts, expanded = [], 0, 0, 0
    while (hit := image.find(_SIGNATURE, cursor)) >= 0:
        cursor = hit + 1
        start = hit-5
        if start < 0 or start % 4 or image[hit-1] & 3 != 2:
            continue
        check()
        attempts += 1
        if attempts > 4096:
            break
        decoded = lz_indexed_images.unpack(memoryview(image)[start:start+_LIMIT])
        if not decoded:
            continue
        data, used = decoded
        expanded += len(data)
        if expanded > 128 * 1024 * 1024:
            break
        found = meshes(data, check)
        if not found:
            continue
        result.append(dict(offset=start, size=used, kind='3d model', media='model', layout=LAYOUT,
                           confidence='validated', label=f'{len(found)} compressed display-list meshes',
                           meshes=found, vertices=sum(row['vertices'] for row in found),
                           triangles=sum(row['triangles'] for row in found),
                           preview_settings=dict(format='auto', source='rom', offset=start, mesh=0),
                           reason='A bounded section directory places local vertices used by closed display lists.'))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    if not 0 <= start < start+size <= len(image):
        raise formats.AssetError('The compressed model changed. Scan ROM Explorer again.')
    decoded = lz_indexed_images.unpack(image[start:start+size])
    if not decoded or decoded[1] != size:
        raise formats.AssetError('The compressed model changed. Scan ROM Explorer again.')
    data = decoded[0]
    rows = meshes(data)
    if rows != asset['meshes']:
        raise formats.AssetError('The model sections changed. Scan ROM Explorer again.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(rows)-1)
    row = rows[index]
    vertex, vertex_size = struct.unpack_from('>II', data, 12)
    local = dict(offset=row['start'], size=row['size'], address_maps=[(2, vertex)],
                 vertex_end=vertex+vertex_size, label=asset['label'], preview_settings=asset['preview_settings'])
    result = display_meshes.preview(data, local, selection, vertex_flag_mask=0xffff)
    result['note'] = ('Local geometry from one closed display list. Scene transforms, materials, external lists '
                      'and animation are separate.')
    result['settings'] = dict(asset['preview_settings'], mesh=index)
    return result

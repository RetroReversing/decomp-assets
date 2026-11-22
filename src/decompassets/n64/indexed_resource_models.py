"""Compact vertex, UV and face groups in indexed cartridge resources."""

import struct

from .. import formats
from . import rle_font_atlas

LAYOUT = 'indexed-resource-models'
_GROUP = 128


def geometry(data):
    if len(data) < 8:
        return None
    last_vertex, last_uv, count = struct.unpack_from('>BBH', data)
    vertex_count, uv_count = last_vertex + 1, last_uv + 1
    start = 8 + 6 * vertex_count + 4 * uv_count
    if not count or start + count * 6 != len(data):
        return None
    vertices = list(struct.iter_unpack('>3h', data[8:8 + 6 * vertex_count]))
    faces, cursor, record = [], start, 0
    while record < count:
        header = data[cursor:cursor + 6]
        face_count = header[4] if cursor % 4 == 0 else header[0]
        cursor += 6
        record += 1
        if not face_count or face_count > count - record:
            return None
        for _ in range(face_count):
            face = data[cursor:cursor + 6]
            if any(index >= vertex_count for index in face[:3]) or any(index >= uv_count for index in face[3:]):
                return None
            faces.append(tuple(face[:3]))
            cursor += 6
            record += 1
    return (vertices, faces) if faces else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, rows in rle_font_atlas._directories(image, check):
        meshes = []
        for index, (word, packed) in enumerate(rows):
            if index % 128 == 0:
                check()
            if word >> 24 not in (0x10, 0x20):
                continue
            size, offset = word & 0xffffff, base + (packed & 0xffffff)
            if size < 8 or offset + size > len(image):
                continue
            parsed = geometry(image[offset:offset + size])
            if not parsed:
                continue
            vertices, faces = parsed
            meshes.append(dict(offset=offset, size=size, vertices=len(vertices), triangles=len(faces),
                               label=f'Model · {len(vertices)} vertices'))
        meshes.sort(key=lambda mesh: mesh['offset'])
        for pos in range(0, len(meshes), _GROUP):
            group = meshes[pos:pos + _GROUP]
            start = group[0]['offset']
            end = max(mesh['offset'] + mesh['size'] for mesh in group)
            result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                               confidence='validated', label=f'{len(group)} indexed models', meshes=group,
                               nodes=len(group), preview_settings=dict(source='rom', format='auto', offset=start),
                               reason='The resource table and every vertex, UV and grouped triangle index are checked.'))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(asset['meshes']) - 1)
    mesh = asset['meshes'][index]
    start, end = mesh['offset'], mesh['offset'] + mesh['size']
    if not 0 <= start < end <= len(image) or not (parsed := geometry(image[start:end])):
        raise formats.AssetError('The model changed. Rescan ROM Explorer.')
    vertices, faces = parsed
    if len(vertices) != mesh['vertices'] or len(faces) != mesh['triangles']:
        raise formats.AssetError('The model changed. Rescan ROM Explorer.')
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                materials=[], details=dict(format=mesh['label'], vertices=len(vertices), triangles=len(faces)),
                note='Local geometry; material textures and scene transforms are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

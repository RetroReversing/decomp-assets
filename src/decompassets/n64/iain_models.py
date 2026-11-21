"""Named local meshes from the Iain scene-object loader."""

import math
import re
import struct

from .. import formats
from . import iain

LAYOUT = 'iain-scene-meshes'
_NAME = re.compile(rb'[ -~]{1,64}\0')
_HEADER_SIZE = 52
_VERTEX = struct.Struct('>5fx3B')
_FACE = struct.Struct('>3H8x')


def meshes(data):
    if len(data) < 6:
        return []
    materials = int.from_bytes(data[:2], 'big')
    if materials > 2048:
        return []
    position = 2
    for _ in range(materials):
        if not (name := _NAME.match(data, position)):
            return []
        position = name.end()
    if position + 4 > len(data):
        return []
    count, = struct.unpack_from('>I', data, position)
    position += 4
    if not 0 < count <= 2048:
        return []
    result = []
    for _ in range(count):
        if position + _HEADER_SIZE >= len(data):
            return []
        vertex_count, face_count = struct.unpack_from('>2H', data, position + 4)
        name = _NAME.match(data, position + _HEADER_SIZE)
        if not name:
            return []
        vertex_offset = name.end()
        face_offset = vertex_offset + _VERTEX.size * vertex_count
        position = face_offset + _FACE.size * face_count
        if position > len(data) or face_count and not vertex_count:
            return []
        if not face_count:
            continue
        if any(max(indices) >= vertex_count
               for indices in _FACE.iter_unpack(memoryview(data)[face_offset:position])):
            return []
        if any(not all(math.isfinite(value) for value in row[:3])
               for row in _VERTEX.iter_unpack(memoryview(data)[vertex_offset:face_offset])):
            return []
        result.append(dict(label=name[0][:-1].decode('ascii'), vertices=vertex_count, triangles=face_count,
                           vertex_offset=vertex_offset, face_offset=face_offset))
    return result if position == len(data) else []


def asset(offset, size, data):
    if not (items := meshes(data)):
        return None
    label = items[0]['label'] if len(items) == 1 else f"{items[0]['label']} · {len(items)} meshes"
    return dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                label=label, confidence='validated', meshes=items, nodes=len(items),
                reason='The scene records identify named meshes with validated vertex ranges and triangle indices.',
                preview_settings=dict(format='auto', source='rom', offset=offset))


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    decoded = iain.unpack(image, offset, offset + size)
    if not decoded or decoded[1] != size or not (items := meshes(decoded[0])):
        raise formats.AssetError('The archived scene changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(items) - 1)
    item = items[index]
    start, end = item['vertex_offset'], item['face_offset']
    data = memoryview(decoded[0])
    rows = list(_VERTEX.iter_unpack(data[start:end]))
    faces = list(_FACE.iter_unpack(data[end:end + item['triangles'] * _FACE.size]))
    vertices = [row[:3] for row in rows]
    colors = [(*row[5:], 255) for row in rows]
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({point for face in faces for point in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[colors[i] for i in face], material=0)
                          for face in faces],
                materials=[], details=dict(format='Iain scene mesh', label=item['label'],
                                            vertices=len(vertices), triangles=len(faces)),
                note='Local triangle geometry and vertex colors.',
                settings=dict(asset['preview_settings'], mesh=index))

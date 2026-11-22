"""Mesh batches and their N64 vertices in EXS resource streams."""

import re
import struct

from .. import formats
from . import exs_images

LAYOUT = 'exs-mesh-bank'


def meshes(data):
    if not data or len(data) < 36 or data[:8] != b'_MGNEVR1':
        return []
    start, groups, triangles, vertices = struct.unpack_from('>4I', data, 8)
    if (not 36 <= start < groups < triangles < vertices < len(data)
            or (groups-start) % 44 or (triangles-groups) % 12 or (len(data)-vertices) % 16):
        return []
    result = []
    for at in range(start, groups, 44):
        group, tri, vertex, group_count, tri_count, vertex_count = struct.unpack_from('>6H', data, at)
        if not group_count or not tri_count or not vertex_count:
            continue
        group_at = groups - 4 + group * 12
        tri_at = triangles + tri * 4
        vertex_at = vertices + vertex * 16
        if (group_at < groups-4 or group_at + group_count*12 > triangles
                or tri_at + tri_count*4 > vertices or vertex_at + vertex_count*16 > len(data)):
            continue
        face_base = vertex_base = 0
        faces = []
        valid = True
        for i in range(group_count):
            face_count, point_count = data[group_at+i*12+8:group_at+i*12+10]
            if face_base + face_count > tri_count or vertex_base + point_count > vertex_count:
                valid = False
                break
            for j in range(face_count):
                face = tuple(data[tri_at+(face_base+j)*4:tri_at+(face_base+j)*4+3])
                if len(face) != 3 or any(index >= point_count for index in face):
                    valid = False
                    break
                faces.append(tuple(vertex_base + index for index in face))
            face_base += face_count
            vertex_base += point_count
        if not valid or face_base != tri_count or vertex_base != vertex_count:
            continue
        points = [struct.unpack_from('>3h', data, vertex_at + i*16) for i in range(vertex_count)]
        result.append((at, points, faces))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'EXS\x01', image):
        at = match.start()
        if at + 8 > len(image):
            continue
        size = int.from_bytes(image[at+4:at+8], 'little')
        decoded = exs_images.unpack(image, at+8, size)
        if decoded is None:
            continue
        data, end = decoded
        rows = meshes(data)
        if rows:
            items = [dict(name=f'Mesh {i+1}', vertices=len(points), triangles=len(faces))
                     for i, (_, points, faces) in enumerate(rows)]
            result.append(dict(offset=at, size=end-at, kind='3d model', media='model', layout=LAYOUT,
                               label=f'Compressed geometry ({len(items)} meshes)', confidence='validated',
                               nodes=len(items), meshes=items, triangles=sum(item['triangles'] for item in items),
                               reason='The stream contains bounded mesh batches, triangle indices and N64 vertices.',
                               preview_settings=dict(format='auto', source='rom', offset=at, mesh=0)))
        check()
    return result


def preview(image, asset, selection):
    at = asset['offset']
    size = int.from_bytes(image[at+4:at+8], 'little')
    decoded = exs_images.unpack(image, at+8, size)
    rows = meshes(decoded[0]) if decoded else []
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(rows)-1)
    _, vertices, faces = rows[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({point for face in faces for point in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Compressed geometry', vertices=len(vertices), triangles=len(faces)),
                note='Local mesh geometry; placement and materials are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

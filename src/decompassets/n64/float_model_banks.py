"""Bounded model banks containing float vertices and indexed triangle records."""

import math
import struct

from .. import formats

LAYOUT = 'float-model-bank'


def _read(image, base):
    if base < 0 or base + 12 > len(image):
        return None
    count = struct.unpack_from('>I', image, base)[0]
    if not 2 <= count <= 64 or base + 4 + 4 * count > len(image):
        return None
    starts = struct.unpack_from(f'>{count}I', image, base + 4)
    if starts[0] != 4 + 4 * count:
        return None
    entries = []
    end = starts[0]
    for start in starts:
        if start != end or base + start + 32 > len(image):
            return None
        vertices, triangles, vertex_at, face_at = struct.unpack_from('>HHII', image, base + start + 20)
        if not (3 <= vertices <= 255 and 1 <= triangles <= 5000
                and vertex_at == start + 32 and face_at == vertex_at + vertices * 24):
            return None
        end = face_at + triangles * 32
        if base + end > len(image):
            return None
        points = [struct.unpack_from('>3f', image, base + vertex_at + i * 24) for i in range(vertices)]
        if any(not math.isfinite(value) or abs(value) > 1e7 for point in points for value in point):
            return None
        faces = [tuple(image[base + face_at + i * 32 + 4:base + face_at + i * 32 + 7])
                 for i in range(triangles)]
        if any(max(face) >= vertices or len(set(face)) != 3 for face in faces):
            return None
        entries.append((points, faces))
    return end, entries


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for base in range(0, len(image) - 80, 4):
        if not base % 0x10000:
            check()
        count = int.from_bytes(image[base:base + 4], 'big')
        if not 2 <= count <= 64 or int.from_bytes(image[base + 4:base + 8], 'big') != 4 + 4 * count:
            continue
        parsed = _read(image, base)
        if not parsed:
            continue
        end, entries = parsed
        meshes = [dict(label=f'Local mesh {i + 1}', vertices=len(points), triangles=len(faces))
                  for i, (points, faces) in enumerate(entries)]
        found.append(dict(offset=base, size=end, kind='3d model', media='model', layout=LAYOUT,
                          confidence='validated', meshes=meshes, nodes=len(meshes),
                          label=f'{len(meshes)} local float meshes',
                          reason='The bank bounds consecutive float vertices and triangle indices for every mesh.',
                          preview_settings=dict(format='auto', source='rom', offset=base)))
    return found


def preview(image, asset, selection):
    base = asset['offset']
    parsed = _read(image, base)
    if not parsed or parsed[0] != asset['size']:
        raise formats.AssetError('The model bank changed. Scan ROM Explorer again.')
    entries = parsed[1]
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(entries) - 1)
    vertices, faces = entries[index]
    edges = sorted({tuple(sorted((face[i], face[(i + 1) % 3]))) for face in faces for i in range(3)})
    surfaces = [dict(indices=face, uv=[[0, 0]] * 3, colors=[[255, 255, 255, 255]] * 3, material=0)
                for face in faces]
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=edges,
                points=sorted({index for face in faces for index in face}), surfaces=surfaces, materials=[],
                details=dict(format='Float model bank', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry; textures, placement and animation are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

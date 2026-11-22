"""Compact indexed polygon groups in consecutive EDL components."""

import struct

from .. import formats
from . import edl


def _mesh(data, start, image_size):
    if start + 2 > len(data):
        return None
    vertices = struct.unpack_from('>H', data, start)[0]
    if not 8 <= vertices <= 256:
        return None
    group = start + 2 + vertices * 6
    if group + 2 > len(data):
        return None
    count = struct.unpack_from('>H', data, group)[0]
    if not 3 <= count <= 2048:
        return None
    pos, total, faces = group + 2, 0, []
    while total < count:
        if pos + 10 > len(data):
            return None
        offset, width, height, _, children = struct.unpack_from('>5H', data, pos)
        pos += 10
        if not (1 <= width <= 256 and 1 <= height <= 256 and 1 <= children <= count - total
                and offset * 8 + (width * height + 1) // 2 <= image_size
                and pos + children * 9 <= len(data)):
            return None
        for _ in range(children):
            if pos + 4 > len(data):
                return None
            flag = struct.unpack_from('>I', data, pos)[0]
            pos += 4
            size = 4 if flag & 1 else 3
            width = 1 if flag & 2 else 2
            if pos + size * width + 2 > len(data):
                return None
            indices = struct.unpack_from('>' + ('B' if width == 1 else 'H') * size, data, pos)
            pos += size * width + 2
            if max(indices) >= vertices or len(set(indices)) < 3:
                return None
            faces.append(indices[:3])
            if size == 4:
                faces.append((indices[0], indices[2], indices[3]))
        total += children
    return pos, vertices, faces


def _meshes(data, image_size, check):
    meshes, pos, checks = [], 0, 0
    while pos + 2 < len(data) and len(meshes) < 10000:
        checks += 1
        if checks % 2048 == 0:
            check()
        chain, cursor = [], pos
        while len(meshes) + len(chain) < 10000 and (parsed := _mesh(data, cursor, image_size)):
            end, vertices, faces = parsed
            chain.append(dict(name=f'Mesh {len(meshes) + len(chain) + 1}', descriptor=cursor,
                              vertices=vertices, triangles=len(faces)))
            cursor = (end + 1) & ~1
        if len(chain) >= 3:
            meshes.extend(chain)
            pos = cursor
        else:
            pos += 2
    return meshes


def regions(image, blocks, check):
    assets = []
    for offset, (_, stored, decoded) in blocks.items():
        other = (offset + stored + 15) & ~15
        if other not in blocks or decoded > 1024 * 1024:
            continue
        tail = (other + blocks[other][1] + 15) & ~15
        if tail not in blocks:
            continue
        try:
            data = edl.unpack(image, offset)
            edl.unpack(image, other)
            edl.unpack(image, tail)
        except formats.AssetError:
            continue
        meshes = _meshes(data, blocks[other][2], check)
        if not meshes:
            continue
        assets.append(dict(offset=offset, size=stored, label='EDL indexed polygon models',
                           layout='eurocom-edl-models', kind='3d model', media='model',
                           confidence='validated', reason='Consecutive polygon groups reference bounded vertices.',
                           image_size=blocks[other][2], nodes=0, meshes=meshes,
                           vertices=sum(m['vertices'] for m in meshes),
                           triangles=sum(m['triangles'] for m in meshes),
                           preview_settings=dict(source='rom', format='auto', offset=offset)))
    return assets


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    start = asset['meshes'][index]['descriptor']
    data = edl.unpack(image, asset['offset'])
    parsed = _mesh(data, start, asset['image_size'])
    if not parsed:
        raise formats.AssetError('The polygon group changed. Rescan ROM Explorer.')
    _, count, faces = parsed
    vertices = list(struct.iter_unpack('>3h', data[start + 2:start + 2 + count * 6]))
    edges = {tuple(sorted((face[i], face[(i + 1) % 3]))) for face in faces for i in range(3)}
    surfaces = [dict(indices=face, uv=[[0, 0]] * 3, colors=[[255, 255, 255, 255]] * 3, material=0)
                for face in faces]
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(count)), surfaces=surfaces, materials=[],
                details=dict(format='EDL polygon group', vertices=count, triangles=len(faces)),
                note='Local polygon geometry; runtime placement and material modes are separate.',
                settings=dict(format='auto', source='rom', offset=asset['offset'], mesh=index))

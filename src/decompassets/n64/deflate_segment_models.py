"""Local F3DEX2 meshes in bounded compressed segmented resources."""

import struct

from .. import formats
from . import display_meshes, graphbin

LAYOUT = 'deflate-segment-meshes'


def _meshes(data, check=lambda: None):
    if len(data) < 32:
        return []
    pointers = struct.unpack_from('>4I', data)
    segment = pointers[0] >> 24
    if (not 1 <= segment <= 15 or any(value >> 24 != segment or not 0 < (value & 0xffffff) < len(data)
                                     for value in pointers) or list(pointers) != sorted(set(pointers))):
        return []
    meshes = []
    accepted_end = 0
    for offset in range(0, len(data) - 8, 8):
        if offset % 65536 == 0:
            check()
        if offset < accepted_end or data[offset] != 1 or data[offset + 4] != segment:
            continue
        geometry = display_meshes.geometry(data, offset, len(data), {segment: 0})
        if not geometry:
            continue
        end, vertices, faces = geometry
        accepted_end = end
        # Planar display lists are sprites; only classify geometry with depth as models.
        if len({vertex[2] for vertex in vertices}) > 1:
            meshes.append((offset, vertices, faces))
    return meshes


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for start, end in graphbin.pairs(image, check):
        check()
        data = graphbin._unpack(image, start, end)
        if not data or not (meshes := _meshes(data, check)):
            continue
        summary = [dict(name=f'Mesh {i + 1}', vertices=len(vertices), triangles=len(faces))
                   for i, (_, vertices, faces) in enumerate(meshes)]
        result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                           confidence='inferred', label=f'Compressed display meshes ({len(meshes)})',
                           meshes=summary, vertices=sum(m['vertices'] for m in summary),
                           triangles=sum(m['triangles'] for m in summary),
                           reason='Segment pointers and bounded F3DEX2 vertex loads and triangle indices agree.',
                           preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = graphbin._unpack(image, start, start + size)
    meshes = _meshes(data) if data else []
    if not meshes:
        raise formats.AssetError('The compressed model resource changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(meshes)-1)
    _, vertices, faces = meshes[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({index for face in faces for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='F3DEX2', vertices=len(vertices), triangles=len(faces)),
                note='Local mesh geometry; scene transforms, animation and materials are separate.',
                settings=asset['preview_settings'])

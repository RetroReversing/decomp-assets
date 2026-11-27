"""Bounded local polygon models in named sequential archives."""
import struct

from .. import formats
from . import named_tim_archives

LAYOUT = 'named-archive-prm'


def mesh(data):
    if len(data) < 0x90 or b'\0' not in data[:16]:
        return None
    name = bytes(data[:16]).split(b'\0', 1)[0]
    if not name or any(c < 32 or c >= 127 for c in name):
        return None
    count = int.from_bytes(data[16:18], 'big')
    primitives = int.from_bytes(data[32:34], 'big')
    at = 0x90
    if not 3 <= count <= 4096 or not 1 <= primitives <= 16384 or at+8*count > len(data):
        return None
    vertices = []
    for i in range(count):
        x, y, z, pad = struct.unpack_from('>hhhH', data, at+8*i)
        if pad:
            return None
        vertices.append((x, y, z))
    if len(set(vertices)) < 3:
        return None
    at += 8*count
    faces = []
    for _ in range(primitives):
        if at+4 > len(data):
            return None
        kind, flags = struct.unpack_from('>HH', data, at)
        size, indices = {1:(16,3), 2:(28,3), 4:(32,4), 5:(24,3), 7:(28,4)}.get(kind, (0,0))
        if not size or flags != 1 or at+size > len(data):
            return None
        ids = struct.unpack_from('>'+'H'*indices, data, at+4)
        if max(ids) >= count or len(set(ids)) < 3:
            return None
        faces.append(ids[:3])
        if indices == 4:
            faces.append((ids[1], ids[3], ids[2]))
        at += size
    return (vertices, faces) if at == len(data) else None


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for start, rows in named_tim_archives.archives(image, check):
        for name, offset, size in rows:
            if not name.lower().endswith('.prm') or not (result := mesh(image[offset:offset+size])):
                continue
            vertices, faces = result
            found.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                              label=name, confidence='validated', archive=start, nodes=1,
                              meshes=[dict(name=name, vertices=len(vertices), triangles=len(faces))],
                              triangles=len(faces),
                              reason='The named archive bounds a complete local indexed polygon model. '
                                     'Quad triangulation is inferred; placement, textures and animation are separate.',
                              preview_settings=dict(format='auto', source='rom', offset=offset, mesh=0)))
    return found


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    rows = named_tim_archives.members(image, asset['archive'])
    if not any(offset == asset['offset'] and size == asset['size'] for _, offset, size in rows):
        raise formats.AssetError('The named model archive changed. Rescan ROM Explorer.')
    result = mesh(image[asset['offset']:asset['offset']+asset['size']])
    if not result:
        raise formats.AssetError('The model changed. Rescan ROM Explorer.')
    vertices, faces = result
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Named local polygon model', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=asset['preview_settings'])

"""Object-bank geometry in FLA2 streams.

The object and geometry records are described by the MIT-licensed format at
https://github.com/naclomi/libgarib/blob/main/formats/glover.objbank.ksy.
"""
import math
import re
import struct

from .. import formats
from . import fla2

LAYOUT = 'fla2-object-models'


def meshes(data, check=lambda: None):
    entries = []
    for at in range(0, min(len(data)-7, 4096*8), 8):
        key, root = struct.unpack_from('>II', data, at)
        if not key:
            if root:
                return []
            break
        if root % 4 or root+28 > len(data) or int.from_bytes(data[root:root+4], 'big') != key:
            return []
        entries.append(root)
    else:
        return []
    if len(entries) < 2:
        return []
    result, visited = [], set()
    pending = [int.from_bytes(data[root+12:root+16], 'big') for root in entries]
    while pending:
        check()
        at = pending.pop()
        if not at or at in visited:
            continue
        if len(visited) >= 4096 or at % 4 or at+64 > len(data):
            return []
        visited.add(at)
        geometry = int.from_bytes(data[at+20:at+24], 'big')
        child, sibling = struct.unpack_from('>II', data, at+52)
        pending.extend((child, sibling))
        if not geometry:
            continue
        if geometry % 4 or geometry+36 > len(data):
            return []
        faces, vertices, vp, fp = struct.unpack_from('>HHII', data, geometry)
        if not faces and not vertices:
            continue
        if (not 3 <= vertices <= 8192 or not 1 <= faces <= 16384 or vp % 4 or fp % 2
                or vp+vertices*12 > len(data) or fp+faces*6 > len(data)):
            return []
        points = [struct.unpack_from('>3f', data, vp+i*12) for i in range(vertices)]
        triangles = [struct.unpack_from('>3H', data, fp+i*6) for i in range(faces)]
        if (any(not math.isfinite(x) or abs(x) > 1000000 for point in points for x in point)
                or any(max(face) >= vertices or len(set(face)) < 3 for face in triangles)
                or len(set(points)) < 3):
            return []
        name = data[at+4:at+12].split(b'\0', 1)[0].decode('ascii', errors='replace')
        result.append((name or f'Mesh {len(result)+1}', points, triangles))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for hit in re.finditer(b'FLA2', image):
        check()
        at = hit.start()
        try:
            data, used = fla2._unpack(image[at:])
        except formats.AssetError:
            continue
        rows = meshes(data, check)
        if not rows:
            continue
        items = [dict(name=name, vertices=len(points), triangles=len(faces)) for name, points, faces in rows]
        result.append(dict(offset=at, size=used, kind='3d model', media='model', layout=LAYOUT,
                           label=f'FLA2 object bank ({len(items)} meshes)', confidence='validated', nodes=len(items),
                           meshes=items, triangles=sum(x['triangles'] for x in items),
                           reason='The object directory and mesh hierarchy bound finite vertices and face indices. Transforms, animation and materials are separate.',
                           preview_settings=dict(source='rom', format='auto', offset=at, mesh=0)))
    return result


def preview(image, asset, selection):
    try:
        data, used = fla2._unpack(image[asset['offset']:asset['offset']+asset['size']])
    except formats.AssetError as error:
        raise formats.AssetError('The compressed object bank changed. Rescan ROM Explorer.') from error
    rows = meshes(data)
    if not rows or used != asset['size']:
        raise formats.AssetError('The compressed object bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(rows)-1)
    name, vertices, faces = rows[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=f, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for f in faces],
                materials=[], details=dict(format='FLA2 object mesh', name=name, vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings'], mesh=index))

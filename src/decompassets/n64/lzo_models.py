"""Indexed model parts in consecutive LZO1X resource streams."""
import re
import struct

from .. import formats, lzo1x

LAYOUT = 'lzo-indexed-parts'


def meshes(data):
    if len(data) < 56:
        return []
    parts = int.from_bytes(data[2:4], 'big')
    count, polygons = struct.unpack_from('>II', data, 4)
    vertices_at, faces_at, faces_end = struct.unpack_from('>3I', data, 32)
    if (not 1 <= parts <= 64 or not 3 <= count <= 8192 or not 1 <= polygons <= 8192
            or vertices_at != 56+parts*64 or faces_at != (vertices_at+count*6+7)&~7
            or faces_end != faces_at+polygons*44 or faces_end > len(data)):
        return []
    points = [struct.unpack_from('>3h', data, vertices_at+i*6) for i in range(count)]
    rows = []
    current = faces_at
    for part in range(parts):
        header = 56+part*64
        declared, size, start = struct.unpack_from('>HHI', data, header+4)
        if not 3 <= declared <= count or not 1 <= size <= polygons or start != current:
            return []
        faces = []
        for j in range(size):
            at = start+j*44
            flags = int.from_bytes(data[at:at+2], 'big')
            corners = 4-(flags & 3)
            if corners not in (3, 4):
                return []
            indices = struct.unpack_from(f'>{corners}H', data, at+8)
            if max(indices) >= count or len(set(indices)) != corners:
                return []
            faces.append(indices[:3])
            if corners == 4:
                faces.append((indices[0], indices[2], indices[3]))
        current += size*44
        used = sorted({i for face in faces for i in face})
        if len(used) < 3:
            return []
        remap = {old: new for new, old in enumerate(used)}
        rows.append(([points[i] for i in used], [tuple(remap[i] for i in face) for face in faces]))
    return rows if current == faces_end else []


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for hit in re.finditer(b'\x11\0\0\x19', image):
        at = hit.start()+3
        check()
        if at+9 > len(image):
            continue
        parts = int.from_bytes(image[at+3:at+5], 'big')
        count = int.from_bytes(image[at+5:at+9], 'big')
        if not 1 <= parts <= 64 or not 3 <= count <= 8192:
            continue
        try:
            data, size = lzo1x.unpack(memoryview(image)[at:])
        except (ValueError, IndexError):
            continue
        rows = meshes(data)
        if not rows:
            continue
        items = [dict(name=f'Part {i+1}', vertices=len(points), triangles=len(faces))
                 for i, (points, faces) in enumerate(rows)]
        result.append(dict(offset=at, size=size, kind='3d model', media='model', layout=LAYOUT,
                           label=f'LZO model ({len(items)} parts)', confidence='validated', nodes=len(items),
                           meshes=items, triangles=sum(x['triangles'] for x in items),
                           reason='Each bounded part references signed vertices and triangle or quad records. Placement, animation and materials are separate.',
                           preview_settings=dict(source='rom', format='auto', offset=at, mesh=0)))
    return result


def preview(image, asset, selection):
    try:
        data, size = lzo1x.unpack(memoryview(image)[asset['offset']:asset['offset']+asset['size']])
    except (ValueError, IndexError) as error:
        raise formats.AssetError('The compressed model changed. Rescan ROM Explorer.') from error
    rows = meshes(data)
    if not rows or size != asset['size']:
        raise formats.AssetError('The compressed model changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Part', 0, len(rows)-1)
    vertices, faces = rows[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=f, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for f in faces],
                materials=[], details=dict(format='LZO model parts', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings'], mesh=index))

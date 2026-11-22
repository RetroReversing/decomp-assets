"""Little-endian vertex and quad batches in bounded RNC resources."""
import re
import struct

from .. import formats, rnc

LAYOUT = 'rnc-quad-batches'


def meshes(data):
    rows = []
    at = count = 0
    while at < len(data):
        if at+20 > len(data) or count >= 4096:
            return []
        kind, header, vertices, face_offset, faces = struct.unpack_from('<5I', data, at)
        end = at+20+vertices*8+faces*12
        if (kind or header != 16 or not 3 <= vertices <= 4096 or not 1 <= faces <= 8192
                or face_offset != 16+vertices*8 or end > len(data)):
            return []
        count += 1
        vertex_at = at+20
        face_at = vertex_at+vertices*8
        points = [struct.unpack_from('<3h', data, vertex_at+i*8) for i in range(vertices)]
        triangles = []
        valid = True
        for i in range(faces):
            indices = struct.unpack_from('<4H', data, face_at+i*12)
            if any(value % 4 or value//4 >= vertices for value in indices):
                valid = False
                break
            a, b, c, d = (value//4 for value in indices)
            for triangle in ((a, b, c), (a, c, d)):
                if len(set(triangle)) == 3:
                    triangles.append(triangle)
        if valid and triangles and len(set(points)) >= 3:
            rows.append((points, triangles))
        at = end
    return rows if count >= 2 and len(rows) >= 2 else []


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'RNC\x01', image):
        at = match.start()
        check()
        try:
            data, size = rnc.unpack_at(image, at)
        except rnc.RncError:
            continue
        rows = meshes(data)
        if not rows:
            continue
        items = [dict(name=f'Mesh {i+1}', vertices=len(points), triangles=len(faces))
                 for i, (points, faces) in enumerate(rows)]
        result.append(dict(offset=at, size=size, kind='3d model', media='model', layout=LAYOUT,
                           label=f'RNC geometry ({len(items)} meshes)', confidence='validated',
                           nodes=len(items), meshes=items, triangles=sum(i['triangles'] for i in items),
                           reason='Bounded records pair signed vertices with quad indices; placement and materials are separate.',
                           preview_settings=dict(format='auto', source='rom', offset=at, mesh=0)))
    return result


def preview(image, asset, selection):
    try:
        data, _ = rnc.unpack_at(image, asset['offset'])
    except rnc.RncError as error:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.') from error
    rows = meshes(data)
    if not rows:
        raise formats.AssetError('The geometry changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(rows)-1)
    vertices, faces = rows[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({point for face in faces for point in face}),
                surfaces=[dict(indices=f, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for f in faces],
                materials=[], details=dict(format='RNC quad geometry', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings'], mesh=index))

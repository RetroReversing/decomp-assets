"""Bounded mesh batches in RefPack geometry containers."""
import struct

from .. import formats, refpack

LAYOUT = 'refpack-mesh-batches'
_TAGS = (b'@HEADER\0', b'@VERTICES\0', b'@MESHES\0')


def meshes(data):
    if len(data) < 64 or data[:4] != b'\0\0\0\x05' or not 64 <= int.from_bytes(data[4:8], 'big') <= len(data):
        return []
    rows = []
    pos = 0
    while (pos := data.find(_TAGS[2], pos)) >= 0:
        at = pos
        pos += 8
        if at < 64 or data[at-64:at-56] != _TAGS[0] or data[at-32:at-22] != _TAGS[1]:
            continue
        node = at+24
        if node+48 > len(data):
            continue
        kind, size = struct.unpack_from('>II', data, node)
        count = int.from_bytes(data[node+14:node+16], 'big')
        end = node+size
        tail = node+48+count*16
        if kind != 3 or not 3 <= count <= 32768 or not tail < end <= len(data):
            continue
        faces = []
        vertex = 0
        previous = 0
        valid = True
        while tail+10 <= end and any(data[tail:tail+10]):
            mode, marker, _, first, amount = struct.unpack_from('>5H', data, tail)
            if mode not in (0x00b5, 0x01b5) or marker != 0xffff or not amount or first != previous:
                valid = False
                break
            corners = 3 if mode == 0x00b5 else 4
            if vertex+amount*corners > count:
                valid = False
                break
            for _ in range(amount):
                faces.append((vertex, vertex+1, vertex+2))
                if corners == 4:
                    faces.append((vertex, vertex+2, vertex+3))
                vertex += corners
            previous += amount
            tail += 10
        if not valid or vertex != count or any(data[tail:end]):
            continue
        points = [struct.unpack_from('>3h', data, node+48+16*i) for i in range(count)]
        if len(set(points)) < 3:
            continue
        rows.append((points, faces))
    return rows


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    at = 0
    while (at := image.find(b'\x10\xfb', at)) >= 0:
        start = at
        at += 2
        check()
        try:
            data, consumed = refpack.unpack(memoryview(image)[start:])
        except ValueError:
            continue
        rows = meshes(data)
        if not rows:
            continue
        items = [dict(name=f'Mesh {i+1}', vertices=len(points), triangles=len(faces))
                 for i, (points, faces) in enumerate(rows)]
        found.append(dict(offset=start, size=consumed, kind='3d model', media='model', layout=LAYOUT,
                          label=f'Compressed geometry ({len(items)} meshes)', confidence='inferred',
                          nodes=len(items), meshes=items, triangles=sum(x['triangles'] for x in items),
                          reason='The geometry container bounds vertices and triangle or quad batches; object placement and materials are separate.',
                          preview_settings=dict(format='auto', source='rom', offset=start, mesh=0)))
    return found


def preview(image, asset, selection):
    try:
        data, _ = refpack.unpack(memoryview(image)[asset['offset']:])
    except ValueError as error:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.') from error
    rows = meshes(data)
    if not rows:
        raise formats.AssetError('The geometry changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(rows)-1)
    vertices, faces = rows[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=f, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for f in faces],
                materials=[], details=dict(format='Compressed mesh batches', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings'], mesh=index))

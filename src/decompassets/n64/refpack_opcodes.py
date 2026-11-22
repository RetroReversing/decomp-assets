"""Bounded mesh batches in RefPack geometry containers."""
import struct

from .. import formats, refpack

LAYOUT = 'refpack-opcode-meshes'
_TAGS = (b'@HEADER\0', b'@VERTICES\0', b'@MESHES\0')


def meshes(data):
    """Read complete small vertex-cache batches; larger cache reloads need more evidence."""
    if len(data) < 64 or data[:4] != b'\0\0\0\x04' or not 64 <= int.from_bytes(data[4:8], 'big') <= len(data):
        return []
    limit = int.from_bytes(data[4:8], 'big')
    rows = []
    pos = 0
    while (pos := data.find(b'@OPCODES\0', pos)) >= 0:
        at = pos
        pos += 8
        if at < 64 or data[at-64:at-56] != b'@HEADER\0' or data[at-32:at-22] != b'@VERTICES\0':
            continue
        node = at + 24
        if node + 48 > len(data):
            continue
        kind, size = struct.unpack_from('>II', data, node)
        count = int.from_bytes(data[node+14:node+16], 'big')
        end = node + size
        cursor = node + 48 + count * 16
        if kind != 3 or not 3 <= count <= 16 or not cursor < end <= limit:
            continue
        points = [struct.unpack_from('>3h', data, node+48+16*i) for i in range(count)]
        faces = []
        loaded = False
        valid = True
        while cursor + 2 <= end:
            op, arg = data[cursor:cursor+2]
            if op == 0x70 and arg == 0:
                cursor += 2
                break
            if op == 0x00:
                cursor += 2
            elif op == 0x10 and arg == count and not loaded:
                loaded = True
                cursor += 2
            elif op == 0x30:
                cursor += 2
            elif op in (0x40, 0x50):
                cursor += 6
            elif op == 0x60:
                cursor += 2 + arg
            elif op >> 4 == 2 and loaded:
                face = (op & 15, arg >> 4, arg & 15)
                if max(face) >= count:
                    valid = False
                    break
                faces.append(face)
                cursor += 2
            else:
                valid = False
                break
        else:
            valid = False
        if valid and cursor <= end and faces and len(set(points)) >= 3 and not any(data[cursor:end]):
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
                          reason='The geometry container bounds indexed triangle commands; larger cache batches, object placement and materials are omitted.',
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
                materials=[], details=dict(format='Compressed indexed meshes', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings'], mesh=index))

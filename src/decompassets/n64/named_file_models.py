"""Local meshes in compressed named-file world resources.

Record and command layouts follow the MIT-licensed hwtr-decomp project.
"""
import struct

from .. import formats
from . import named_file_textures

LAYOUT = 'named-file-model'


def unpack(data, expected, check=lambda: None):
    if len(data) < 8:
        return None
    size, window, extra = struct.unpack_from('>IHH', data)
    length = extra & 255
    if size != expected or not 0 < size <= formats.MAX_BYTES or not 1 <= window <= 15 or not 1 <= length <= 8:
        return None
    prefix = (1 << window) + 1
    if 8 + prefix > len(data) or prefix > size:
        return None
    out = bytearray(data[8:8+prefix])
    bit = (8+prefix)*8

    def bits(n):
        nonlocal bit
        if bit+n > len(data)*8:
            raise ValueError
        value = 0
        for i in range(n):
            value |= ((data[bit//8] >> (bit%8)) & 1) << i
            bit += 1
        return value

    try:
        while len(out) < size:
            if len(out) % 4096 < 32:
                check()
            if bits(1):
                value = bits(window+length)
                distance, count = (value >> length)+1, (value & ((1 << length)-1))+1
                if distance > len(out) or len(out)+count > size:
                    return None
                for _ in range(count):
                    out.append(out[-distance])
            else:
                out.append(bits(8))
    except ValueError:
        return None
    return bytes(out)


def mesh(data, at):
    if at+52 > len(data) or data[at:at+2] != b'\xa4\x92':
        return None
    commands, count = struct.unpack_from('>H2xH', data, at+2)
    if not 0 < commands <= 12000 or not 0 < count <= 12000:
        return None
    cmd, pos, uv, col, indices, chunks = (at+v for v in struct.unpack_from('>6I', data, at+24))
    if not (at <= chunks < pos <= uv <= col <= indices <= cmd < len(data)):
        return None
    if indices + count*3 > cmd:
        return None
    vertices, base = [], 0
    while base < count:
        if chunks+8 > pos:
            return None
        end, po, _, _ = struct.unpack_from('>4H', data, chunks)
        if not base < end <= count:
            return None
        for i in range(base, end):
            p = pos + (data[indices+i*3]+po)*6
            if p+6 > uv:
                return None
            vertices.append(struct.unpack_from('>3h', data, p))
        base = end
        chunks += 8
    faces = []
    current = [0, 0, 0]
    load_start = load_count = 0
    for _ in range(commands):
        if cmd >= len(data):
            return None
        op = data[cmd] >> 4
        widths = (4,2,1,2,3,1,1,4,2,2,1,4,1)
        if op >= len(widths) or cmd+widths[op] > len(data):
            return None
        if op == 0:
            current = list(data[cmd+1:cmd+4])
        elif op == 1:
            current = [data[cmd]&15, data[cmd+1]>>4, data[cmd+1]&15]
        elif op == 2:
            current[1] += ((data[cmd] >> 2)&3)+1
            current[2] += (data[cmd]&3)+1
        elif op == 11:
            load_count = data[cmd+1]+1
            load_start = data[cmd+2] + (data[cmd+3]<<8)
            if load_start+load_count > count:
                return None
        if op <= 2:
            if any(v >= load_count for v in current):
                return None
            faces.append(tuple(load_start+v for v in current))
        cmd += widths[op]
    return (vertices, faces) if faces else None


def geometry(data):
    if len(data) < 0x54:
        return None
    nodes, meshes, tex = struct.unpack_from('>3H', data)
    node_at, mesh_at, tex_at = struct.unpack_from('>3I', data, 0x2c)
    if not (0 < nodes <= 1024 and 0 < meshes <= 256 and 0 < tex <= 1024
            and node_at+nodes*84 <= len(data) and mesh_at+meshes*52 <= len(data) and tex_at+tex*8 <= len(data)):
        return None
    vertices, faces = [], []
    for i in range(meshes):
        model = mesh(data, mesh_at+i*52)
        if not model:
            continue
        points, triangles = model
        base = len(vertices)
        vertices.extend(points)
        faces.extend(tuple(base+j for j in tri) for tri in triangles)
    return (vertices, faces) if faces else None


def _model(image, row, check=lambda: None):
    name, kind, packed, size, _, start, _ = row
    if kind != 0x1000000 or not name.endswith(('.CAR', '.OBJ')):
        return None
    raw = unpack(image[start:start+packed], size, check)
    return geometry(raw) if raw else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for table, rows in named_file_textures.tables(image, check):
        for row in rows:
            check()
            model = _model(image, row, check)
            if not model:
                continue
            vertices, faces = model
            found.append(dict(offset=row[5], size=row[2], kind='3d model', media='model', layout=LAYOUT,
                              confidence='validated', table=table, name=row[0], vertices=len(vertices),
                              triangles=len(faces), label=f'{row[0]} · local meshes',
                              reason='The file table, bounded decompression, mesh records and triangle commands agree.',
                              preview_settings=dict(source='rom', format='auto', offset=row[5])))
    return found


def preview(image, asset, selection):
    for table, rows in named_file_textures.tables(image):
        if table != asset['table']:
            continue
        row = next((row for row in rows if row[0] == asset['name'] and row[5] == asset['offset']), None)
        model = _model(image, row) if row else None
        if model:
            vertices, faces = model
            edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
            return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges), points=[],
                        surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                        materials=[], details=dict(format='Named-file local meshes', vertices=len(vertices),
                        triangles=len(faces)), note='Local meshes; node transforms, materials and animation are separate.',
                        settings=asset['preview_settings'])
    raise formats.AssetError('The model file changed. Scan ROM Explorer again.')

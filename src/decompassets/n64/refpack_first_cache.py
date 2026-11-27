"""The first bounded vertex-cache batch of a tagged RefPack geometry resource."""
import struct

from .. import formats, refpack

LAYOUT = 'refpack-first-cache'


def mesh(data):
    """Keep only a first cache batch; later reload opcodes are not yet understood."""
    if (len(data) < 160 or data[:4] != b'\0\0\0\x02' or data[8:12] != b'\xbe\xef\0\0'
            or int.from_bytes(data[4:8], 'big') != len(data)-64 or data[24:28] != b'\0\0\0\x03'
            or data[-56:-48] != b'@HEADER\0' or data[-24:-15] != b'@SEGMENTS'):
        return None
    node = 24
    node_end = node+int.from_bytes(data[node+4:node+8], 'big')
    count = int.from_bytes(data[node+14:node+16], 'big')
    tag = data.find(b'@OPCODES\0')
    if (not 16 <= count <= 4096 or tag < 72 or tag+9 > len(data)
            or data[tag-64:tag-56] != b'@HEADER\0' or data[tag-32:tag-22] != b'@VERTICES\0'):
        return None
    vertex_bytes, vertex_offset = struct.unpack_from('>II', data, tag-40)
    op_bytes, op_offset = struct.unpack_from('>II', data, tag-8)
    start = node+vertex_offset
    op = node+op_offset
    end = op+op_bytes
    if (vertex_offset != 48 or vertex_bytes != count*16 or op != start+vertex_bytes
            or not start < op < end <= node_end <= tag-72 or data[op:op+4] != b'\0\x02\x10\0'):
        return None
    vertices = [struct.unpack_from('>hhh', data, start+16*i) for i in range(16)]
    if len(set(vertices)) < 3:
        return None
    cursor = op+4
    loaded = set()
    faces = []
    while cursor+2 <= end:
        code, arg = data[cursor:cursor+2]
        if code == 0x40:
            if arg >= 16 or cursor+6 > end:
                return None
            loaded.add(arg)
            cursor += 6
        elif code == 0x30:
            cursor += 2
        elif code >> 4 == 2:
            face = (code & 15, arg >> 4, arg & 15)
            if not set(face) <= loaded:
                return None
            faces.append(face)
            cursor += 2
        else:
            break
    # The following cache reload exists but is intentionally not interpreted.
    if len(faces) < 2 or cursor+4 > end or data[cursor] != 0 or data[cursor+2] >> 4 != 1:
        return None
    return vertices, faces


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    at = 0
    while (at := image.find(b'\x10\xfb', at)) >= 0:
        start = at
        at += 2
        check()
        try:
            data, used = refpack.unpack(memoryview(image)[start:])
        except (ValueError, IndexError):
            continue
        result = mesh(data)
        if not result:
            continue
        vertices, faces = result
        found.append(dict(offset=start, size=used, kind='3d model', media='model', layout=LAYOUT,
                          label='Compressed geometry (first cache batch)', confidence='inferred', nodes=1,
                          meshes=[dict(name='First cache batch', vertices=len(vertices), triangles=len(faces))],
                          triangles=len(faces),
                          reason='A tagged geometry resource bounds its vertices and first indexed cache batch. '
                                 'Later cache reloads, placement, materials and animation are not decoded.',
                          preview_settings=dict(format='auto', source='rom', offset=start, mesh=0)))
    return found


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    try:
        data, used = refpack.unpack(memoryview(image)[asset['offset']:])
    except (ValueError, IndexError) as exc:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.') from exc
    result = mesh(data)
    if not result or used != asset['size']:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.')
    vertices, faces = result
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Compressed first cache batch', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings']))

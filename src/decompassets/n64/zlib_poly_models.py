"""Local polygon meshes in bounded compressed object records."""
import re
import struct
import zlib

from .. import formats

LAYOUT = 'zlib-polygon-model'
_MARKER = re.compile(rb'\x78[\x01\x5e\x9c\xda]')
_LIMIT = 4 * 1024 * 1024


def model(image, offset):
    if not _MARKER.match(image, offset):
        return None
    try:
        head = zlib.decompressobj().decompress(image[offset:offset+128], 8)
        if len(head) != 8 or head[:4] != b'\0\1\0\0':
            return None
        source = image[offset:offset+_LIMIT+0x10000]
        reader = zlib.decompressobj()
        data = reader.decompress(source, _LIMIT+1)
        if not reader.eof or len(data) > _LIMIT or len(data) < 64:
            return None
        def word(at):
            if at < 0 or at+4 > len(data) or at % 4:
                raise ValueError
            return struct.unpack_from('>I', data, at)[0]
        vertices_at = word(4)
        root = word(0x18)
        node = word(word(root+8))
        table = word(node+0x20)
        polygons_at, count = word(table+8), word(table+12)
        if not (0 < polygons_at < vertices_at < len(data) and 1 <= count <= 4096
                and (len(data)-vertices_at) % 8 == 0):
            return None
        vertex_count = (len(data)-vertices_at)//8
        if not 3 <= vertex_count <= 8192:
            return None
        vertices = []
        for at in range(vertices_at, len(data), 8):
            x, y, z, flag = struct.unpack_from('>3hH', data, at)
            if flag:
                return None
            vertices.append((x, y, z))
        faces = []
        at = polygons_at
        for _ in range(count):
            size, tag = word(at), word(at+4)
            if (size, tag) == (36, 0x090c5146):
                n, stride = 3, 36
            elif (size, tag) == (44, 0x0a0c5146):
                n, stride = 4, 40
            else:
                return None
            if at+stride > vertices_at:
                return None
            indices = struct.unpack_from(f'>{n}H', data, at+12)
            if any(index >= vertex_count for index in indices):
                return None
            faces.append(indices[:3])
            if n == 4:
                faces.append((indices[0], indices[2], indices[3]))
            at += stride
        if at != vertices_at:
            return None
        return len(source)-len(reader.unused_data), vertices, faces
    except (zlib.error, struct.error, ValueError):
        return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, match in enumerate(_MARKER.finditer(image)):
        if index % 128 == 0:
            check()
        offset = match.start()
        if offset % 4 or not (found := model(image, offset)):
            continue
        size, vertices, faces = found
        result.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                           confidence='validated', label='Compressed local polygon mesh',
                           vertices=len(vertices), triangles=len(faces),
                           reason='The compressed object bounds, vertex array and all polygon indices agree.',
                           preview_settings=dict(source='rom', format='auto', offset=offset)))
    return result


def preview(image, asset, selection):
    found = model(image, asset['offset'])
    if not found or found[0] != asset['size']:
        raise formats.AssetError('The compressed model changed. Scan ROM Explorer again.')
    _, vertices, faces = found
    edges = sorted({tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)})
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=edges,
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Compressed polygon mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry only; materials, object placement and animation are separate.',
                settings=asset['preview_settings'])

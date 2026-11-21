"""Local geometry from the vertex-cache groups in native zlib resources."""

import re
import struct

from ..formats import AssetError
from . import deflate_catalog

MODEL = 'deflate-catalog-model'
_HEADER = struct.Struct('>2I10H')
_GROUP = struct.Struct('>4H')
_FACE = struct.Struct('>3H')
_VERTEX = struct.Struct('>3h10x')
_ZLIB = re.compile(rb'\x78[\x01\x5e\x9c\xda]')


def geometry(data):
    if len(data) < _HEADER.size:
        return None
    length, kind, part_start, part_count, material_start, material_count, group_start, groups, face_start, faces,         vertex_start, vertices = _HEADER.unpack_from(data)
    if length != len(data) or kind != 1 or part_start != _HEADER.size or not all((part_count, material_count, groups, faces, vertices)):
        return None
    # The tables reserve one record apiece, and the vertex array starts on an
    # eight-byte boundary. The end of the vertex array is the decoded extent.
    if (material_start != part_start + 4 * (part_count + 1)
            or group_start != material_start + 16 * (material_count + 1)
            or face_start != group_start + _GROUP.size * (groups + 1)
            or vertex_start != (face_start + 20 * (faces + 1) + 7) & ~7
            or len(data) != vertex_start + _VERTEX.size * vertices):
        return None
    batches = list(_GROUP.iter_unpack(data[group_start:group_start + _GROUP.size * groups]))
    if batches[0][0] or batches[0][1]:
        return None
    cache = [None] * 32
    triangles = []
    stops = [group[0] for group in batches[1:]] + [faces]
    for (first, start, count, slot), stop in zip(batches, stops):
        if not (first < stop <= faces and 0 < count <= 32 - slot and start + count <= vertices):
            return None
        # A partial vertex load only replaces the slots it covers. The next
        # triangle may still use vertices loaded by the preceding group.
        cache[slot:slot + count] = range(start, start + count)
        for face in range(first, stop):
            slots = _FACE.unpack_from(data, face_start + 20 * face)
            if any(index >= len(cache) or cache[index] is None for index in slots):
                return None
            triangles.append(tuple(cache[index] for index in slots))
    return list(_VERTEX.iter_unpack(data[vertex_start:])), triangles


def regions(image, *, check=lambda: None, progress=lambda _: None):
    base = min(deflate_catalog.bases(image, check), default=None)
    if base is None:
        return []
    result = []
    for index, marker in enumerate(_ZLIB.finditer(image, base + 8)):
        if index % 128 == 0:
            check()
        offset = marker.start() - 8
        if offset % 4 or not (member := deflate_catalog.unpack(image, offset)):
            continue
        size, data = member
        if parsed := geometry(data):
            vertices, faces = parsed
            result.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=MODEL,
                               confidence='validated', label=f'Catalog mesh · {len(vertices)} vertices',
                               vertices=len(vertices), triangles=len(faces),
                               reason='The decompressed vertex groups and every triangle resolve within the local mesh.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    member = deflate_catalog.unpack(image, asset['offset'])
    if not member or member[0] != asset['size'] or not (parsed := geometry(member[1])):
        raise AssetError('The compressed catalog mesh changed. Rescan ROM Explorer.')
    vertices, faces = parsed
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({index for face in faces for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                materials=[], details=dict(format=asset['label'], vertices=len(vertices), triangles=len(faces)),
                note='Local mesh geometry. Material bindings and animation transforms are separate.',
                settings=asset['preview_settings'])

"""Decode indexed geometry with transposed vertices and packed cache commands.

Format reference: https://github.com/mgrz18/turok2-decomp/blob/main/docs/assets/MODELS.md
All offsets, cache reads and vertex counts are checked before exposing a mesh.
"""

import struct

from . import textures


class GeometryError(ValueError):
    pass


def _blocks(data, span, count=None):
    blocks = textures._blocks(data, *span, empty=True)
    if blocks is None or count is not None and len(blocks) != count:
        raise GeometryError('Invalid packed geometry table.')
    return blocks


def _vertices(data, span):
    start, end = span
    if end-start < 8:
        raise GeometryError('Missing vertex header.')
    stride, count = struct.unpack_from('>II', data, start)
    if stride != 16 or not 1 <= count <= 4096 or end-start != 8+stride*count:
        raise GeometryError('Invalid vertex extent.')
    return [
        [int.from_bytes(bytes((data[start+8+2*axis*count+i],
                              data[start+8+(2*axis+1)*count+i])), 'big', signed=True)
         for axis in range(3)]
        for i in range(count)
    ]


def _commands(commands, cache, loaded, count, bones):
    faces = []
    at = 0
    while at < len(commands):
        command = commands[at]
        if not command:
            if len(commands)-at > 8 or any(commands[at:]):
                break
            return faces, loaded
        width = 5 if command & 0xe0 == 0x60 else 2
        if at+width > len(commands):
            break
        if command & 0x80:
            word = (command << 8) | commands[at+1]
            triangle = [cache[word >> shift & 31] for shift in (10, 5, 0)]
            if None in triangle:
                raise GeometryError('Triangle references a vertex outside the cache.')
            if len(set(triangle)) == 3:
                faces.append(triangle)
        elif command & 0xe0 == 0x20:
            slot = ((command << 8) | commands[at+1]) >> 5 & 31
            length = commands[at+1] & 31 or 32
            if slot+length > len(cache) or loaded+length > count:
                raise GeometryError('Vertex load exceeds its list or cache.')
            cache[slot:slot+length] = range(loaded, loaded+length)
            loaded += length
        elif command == 0x40:
            if commands[at+1] >= bones:
                raise GeometryError('Matrix command references an unknown bone.')
        elif command & 0xe0 != 0x60 or cache[command & 31] is None:
            raise GeometryError('Invalid packed geometry command.')
        at += width
    raise GeometryError('Missing packed geometry terminator.')


def geometry(data):
    root = _blocks(data, (0, len(data)))
    if len(root) not in (3, 6):
        raise GeometryError('Invalid packed geometry root.')
    vertex_lists = _blocks(data, root[0])
    lods = _blocks(data, root[2], len(vertex_lists))
    bones = len(_blocks(data, root[3])) if len(root) == 6 else 0
    if not 1 <= len(lods) <= 64:
        raise GeometryError('Invalid packed geometry LOD count.')
    meshes = []
    for vertex_span, lod in zip(vertex_lists, lods):
        vertices = _vertices(data, vertex_span)
        cache = [None]*32
        loaded = 0
        faces = []
        parts = _blocks(data, lod)
        if not 1 <= len(parts) <= 512:
            raise GeometryError('Invalid packed geometry part count.')
        for part in parts:
            material, commands = _blocks(data, part, 2)
            if material[1]-material[0] != 24:
                raise GeometryError('Invalid packed geometry material.')
            part_faces, loaded = _commands(data[slice(*commands)], cache, loaded, len(vertices), bones)
            faces.extend(part_faces)
        if loaded != len(vertices) or not faces:
            raise GeometryError('Incomplete packed geometry LOD.')
        meshes.append((vertices, faces))
    return meshes


LAYOUT = 'packed-indexed-model'


def asset(data, offset, extent):
    try:
        geometry_lods = geometry(data)
    except GeometryError:
        return None
    meshes = [dict(name=f'LOD {i}', vertices=len(vertices), triangles=len(faces))
              for i, (vertices, faces) in enumerate(geometry_lods)]
    return dict(offset=offset, size=extent, kind='3d model', media='model', layout=LAYOUT,
                label='Packed indexed geometry', confidence='validated', meshes=meshes,
                vertices=sum(m['vertices'] for m in meshes), triangles=sum(m['triangles'] for m in meshes),
                reason='Both RNC checksums, nested tables, vertex extents and packed cache commands agree.',
                preview_settings=dict(format='auto', source='decoded', offset=0, block_offset=offset))


def preview(data, asset, selection):
    from ..formats import AssetError, integer

    try:
        meshes = geometry(data)
    except GeometryError as exc:
        raise AssetError(str(exc)+' Rescan ROM Explorer.') from None
    mesh = integer(selection.get('mesh', 0), 'Mesh', 0, len(meshes)-1)
    vertices, faces = meshes[mesh]
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, edges=sorted(edges), triangles=len(faces),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0)
                          for face in faces], materials=[],
                note='Positions are shown in local coordinates. Animated meshes require bone poses.',
                settings=dict(format='auto', source='decoded', offset=0,
                              block_offset=asset['offset'], mesh=mesh))

"""Read QMesh geometry from Iguana resource directories and vertex-cache commands."""

import re
import struct

from .. import formats, rnc

_DIRECTORY = struct.Struct('<32s6I')
_VERTEX = struct.Struct('<3h8x')
_PAIR = re.compile(re.escape(b'qvert'.ljust(32,b'\0')+bytes([205])*4))
_COMMAND_BYTES = (1, 1, 3, 5, 5, 0, 4, 7, 6, 5)
_REASON = 'QMesh directory extents and vertex-cache commands resolve to bounded triangles.'


def _triangles(data, vertices):
    cache = [None]*256
    faces = []
    cursor = 0
    while cursor < len(data):
        command = data[cursor]
        width = _COMMAND_BYTES[command] if command < len(_COMMAND_BYTES) else 0
        if not width or cursor+width>len(data):
            return []
        args = data[cursor+1:cursor+width]
        cursor += width
        if command == 1:
            return faces if cursor == len(data) else []
        if command == 4:
            first = int.from_bytes(args[:2], 'big')
            count, slot = args[2:]
            if not count or first+count>vertices or slot+count>len(cache):
                return []
            cache[slot:slot+count] = range(first, first+count)
        elif command in (6, 7):
            indices = [cache[slot] for slot in args]
            if None in indices:
                return []
            faces.extend(tuple(indices[i:i+3]) for i in range(0, len(indices), 3))
        elif command == 8 and cache[args[0]] is None:
            return []
    return []


def _mesh(data, entry):
    if entry+2*_DIRECTORY.size>len(data):
        return None
    name, marker, stride, vertices, _, _, start = _DIRECTORY.unpack_from(data, entry)
    cmd_name, cmd_marker, unit, length, _, _, commands = _DIRECTORY.unpack_from(data, entry+_DIRECTORY.size)
    end = start+vertices*_VERTEX.size
    if (name != b'qvert'.ljust(32,b'\0') or cmd_name != b'qcmd'.ljust(32,b'\0')
            or marker != 0xcdcdcdcd or cmd_marker != marker or stride != _VERTEX.size or unit != 1
            or not 3<=vertices<=16384 or not 1<=length<=65536
            or not 52<=start<end<=commands<commands+length<=entry):
        return None
    faces = _triangles(data[commands:commands+length], vertices)
    if not faces or len(faces)>32768:
        return None
    return start, end, faces


def asset(image, data, offset, extent, *, check=lambda:None):
    if data[:8] != b'!IgUaNa!':
        return None
    meshes = []
    first_vertex = len(data)
    for match in _PAIR.finditer(data):
        check()
        entry = match.start()
        geometry = _mesh(data, entry)
        if geometry is None:
            continue
        start, end, faces = geometry
        first_vertex = min(start, first_vertex)
        meshes.append(dict(descriptor=entry, name=f'Mesh {len(meshes)+1}',
                           vertices=(end-start)//_VERTEX.size, triangles=len(faces)))
    if not meshes:
        return None
    chunks = int.from_bytes(image[offset+12:offset+14], 'big')
    sizes = struct.unpack_from(f'>{chunks}H', image, offset+18)
    page = first_vertex//8192
    start = offset+18+2*chunks+sum(size+(size%2) for size in sizes[:page])
    return dict(offset=start, size=sizes[page], container_offset=offset, container_size=extent,
                label='Iguana QMesh models', kind='3d model', media='model', layout='iguana-qmesh',
                confidence='validated', meshes=meshes, reason=_REASON,
                vertices=sum(mesh['vertices'] for mesh in meshes), triangles=sum(mesh['triangles'] for mesh in meshes),
                preview_settings=dict(format='auto', source='rom', offset=start))


def preview(image, asset, selection):
    from .iguana_textures import unpack

    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    try:
        data, _ = unpack(image, asset['container_offset'])
    except rnc.RncError as exc:
        raise formats.AssetError('The Iguana resource could not be decoded. Rescan ROM Explorer.') from exc
    geometry = _mesh(data, asset['meshes'][index]['descriptor'])
    if geometry is None:
        raise formats.AssetError('The QMesh geometry no longer matches. Rescan ROM Explorer.')
    start, end, faces = geometry
    vertices = list(_VERTEX.iter_unpack(data[start:end]))
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))), details=dict(format='Iguana QMesh', vertices=len(vertices),
                triangles=len(faces)), note='Local geometry preview.', settings={**asset['preview_settings'], 'mesh':index})

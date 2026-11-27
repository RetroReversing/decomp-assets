"""Local geometry from checked Iguana N64 mesh resources in sized archives."""
import math
import re
import struct

from .. import formats, rnc
from . import iguana_textures, sized_archive_audio

_LAYOUT = 'iguana-skin-geometry'
_DIR = struct.Struct('<32s6I')
_MESH = struct.Struct('<16sHIHIH')
_SUBMESH = struct.Struct('<7HI')
_VERTEX = struct.Struct('<3h8x')
_NAMES = (b'geom_n64', b'byte', b'geom_n64_mesh', b'geom_n64_submesh', b'geom_n64_vertex')
_WIDTHS = {1: 3, 2: 5, 3: 4, 4: 7, 5: 6}


def _directory(data):
    marker = _NAMES[0].ljust(32, b'\0') + b'\xcd' * 4
    matches = list(re.finditer(re.escape(marker), data))
    result = []
    for match in matches:
        at = match.start()
        if at + len(_NAMES)*_DIR.size > len(data):
            continue
        rows = [_DIR.unpack_from(data, at + i*_DIR.size) for i in range(len(_NAMES))]
        if any(row[0].rstrip(b'\0') != name or row[1] != 0xcdcdcdcd for row, name in zip(rows, _NAMES)):
            continue
        # One geometry header followed by its byte, mesh, submesh and vertex arrays.
        if [row[2] for row in rows] != [66, 1, _MESH.size, _SUBMESH.size, _VERTEX.size] or rows[0][3] != 1:
            continue
        if any(row[6] < 52 or row[3] * row[2] > at - row[6] for row in rows):
            continue
        if any(left[6] + left[2]*left[3] > right[6] for left, right in zip(rows, rows[1:])):
            continue
        result.append(rows)
    return result[0] if len(result) == 1 else None


def _skeleton(data):
    arrays = []
    for name, stride in ((b'skingroup_rbone', 50), (b'skingroup_vbone', 3)):
        marker = name.ljust(32, b'\0') + b'\xcd'*4
        matches = list(re.finditer(re.escape(marker), data))
        if len(matches) != 1 or matches[0].start() + _DIR.size > len(data):
            return None
        row = _DIR.unpack_from(data, matches[0].start())
        if row[2] != stride or not 0 <= row[3] <= 256 or row[6] < 52 or row[6] + stride*row[3] > matches[0].start():
            return None
        arrays.append(row)
    bones, virtual = arrays
    positions = []
    for i in range(bones[3]):
        p = bones[6] + i*bones[2]
        position = struct.unpack_from('<3f', data, p+20)
        bone, parent = struct.unpack_from('<2H', data, p+44)
        if bone != i or parent != 0xffff and parent >= i or any(not math.isfinite(v) or abs(v) > 100000 for v in position):
            return None
        positions.append(position)
    blends = []
    for i in range(virtual[3]):
        a, b, weight = data[virtual[6] + i*3:virtual[6] + i*3 + 3]
        if a >= len(positions) or b >= len(positions) or weight > 100:
            return None
        blends.append(tuple((positions[a][j]*weight + positions[b][j]*(100-weight))/100 for j in range(3)))
    return positions, blends


def _geometry(data):
    if data[:8] != b'!IgUaNa!' or not (rows := _directory(data)):
        return []
    head, byte, mesh, submesh, vertex = rows
    h = head[6]
    names, nmesh, nsub, nvert, ncmd = struct.unpack_from('<HHHII', data, h + 0x26)
    if (not 0 < names <= 256 or not 0 < nmesh <= 256 or not 0 < nsub <= 4096 or not 3 <= nvert <= 65536
            or not 0 < ncmd <= 2*1024*1024 or (mesh[3], submesh[3], vertex[3]) != (nmesh, nsub, nvert)
            or byte[3] != names*9 + ncmd):
        return []
    sub = [_SUBMESH.unpack_from(data, submesh[6] + i*_SUBMESH.size) for i in range(nsub)]
    offsets = [entry[-1] for entry in sub]
    if offsets[0] != 0 or offsets != sorted(set(offsets)) or offsets[-1] >= ncmd:
        return []
    commands = data[byte[6] + names*9:byte[6] + byte[3]]
    scale, = struct.unpack_from('<f', data, h + 0x34)
    skeleton = _skeleton(data)
    if skeleton and (not math.isfinite(scale) or not 0 < scale <= 100000):
        return []
    output = []
    expected_vertex = expected_submesh = 0
    for index in range(nmesh):
        name, _, base, first, count, nsubs = _MESH.unpack_from(data, mesh[6] + index*_MESH.size)
        if (not 3 <= count <= nvert or base != expected_vertex or first != expected_submesh
                or base + count > nvert or not 0 < nsubs <= nsub or first + nsubs > nsub):
            return []
        expected_vertex, expected_submesh = base + count, first + nsubs
        faces = []
        bones = [None]*count
        for i in range(first, first + nsubs):
            cache = [None]*64
            current_bone = None
            cursor, end = offsets[i], offsets[i+1] if i+1 < nsub else ncmd
            start_faces = len(faces)
            while cursor < end:
                opcode = commands[cursor]
                if opcode == 0:
                    cursor += 1
                    break
                width = _WIDTHS.get(opcode, 0)
                if not width or cursor + width > end:
                    return []
                args = commands[cursor+1:cursor+width]
                if opcode == 1:
                    current_bone = tuple(args)
                    if skeleton and (current_bone[0] not in (0, 16)
                                     or current_bone[1] >= len(skeleton[current_bone[0] == 16])):
                        return []
                elif opcode == 2:
                    start = int.from_bytes(args[:2], 'big')
                    length, slot = args[2:]
                    if not length or start + length > count or slot + length > len(cache):
                        return []
                    cache[slot:slot+length] = range(start, start+length)
                    for vertex_index in range(start, start+length):
                        if bones[vertex_index] is not None and bones[vertex_index] != current_bone:
                            return []
                        bones[vertex_index] = current_bone
                elif opcode in (3, 4):
                    if any(slot >= len(cache) or cache[slot] is None for slot in args):
                        return []
                    faces.extend(tuple(cache[slot] for slot in args[j:j+3]) for j in range(0, len(args), 3))
                elif opcode == 5 and (args[0] >= len(cache) or cache[args[0]] is None):
                    return []
                cursor += width
            if cursor != end or len(faces) - start_faces != sub[i][4]:
                return []
        if not faces:
            return []
        label = name.split(b'\0', 1)[0].decode('ascii', 'replace') or f'Mesh {index+1}'
        verts = list(_VERTEX.iter_unpack(data[vertex[6] + base*_VERTEX.size:vertex[6] + (base+count)*_VERTEX.size]))
        if skeleton:
            if any(bone is None for bone in bones):
                return []
            verts = [tuple(point[j] + scale*skeleton[bone[0] == 16][bone[1]][j] for j in range(3))
                     for point, bone in zip(verts, bones)]
        output.append((label, verts, faces))
    return output if expected_vertex == nvert and expected_submesh == nsub else []


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets, expanded = [], 0
    for directory in sized_archive_audio.directories(image, check=check):
        for name, (offset, end) in directory.items():
            check()
            if image[offset:offset+4] != b'RNC\x81' or offset + 18 > end:
                continue
            size = int.from_bytes(image[offset+4:offset+8], 'big')
            if not 0 < size <= rnc.MAX_OUTPUT or expanded + size > 48*1024*1024:
                continue
            expanded += size
            try:
                data, extent = iguana_textures.unpack(image, offset, check=check)
            except rnc.RncError:
                continue
            if not 0 <= end - offset - extent <= 3 or any(image[offset + extent:end]) or not (meshes := _geometry(data)):
                continue
            chunks = int.from_bytes(image[offset+12:offset+14], 'big')
            first = offset + 18 + 2*chunks
            page_size = int.from_bytes(image[offset+18:offset+20], 'big')
            filename = name.rsplit(b'/', 1)[-1].decode('ascii', 'replace')
            assets.append(dict(offset=first, size=page_size, container_offset=offset, container_size=extent,
                               kind='3d model', media='model', layout=_LAYOUT, confidence='validated',
                               label=f'Iguana geometry · {filename}', rest_pose=_skeleton(data) is not None,
                               meshes=[dict(name=n, vertices=len(v), triangles=len(f)) for n, v, f in meshes],
                               vertices=sum(len(v) for _, v, _ in meshes), triangles=sum(len(f) for _, _, f in meshes),
                               reason='The named archive member, typed geometry arrays, vertex-cache commands and triangle counts agree.',
                               preview_settings=dict(format='auto', source='rom', offset=first)))
    return assets


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    try:
        data, extent = iguana_textures.unpack(image, asset['container_offset'])
    except rnc.RncError as exc:
        raise formats.AssetError('The model resource changed. Rescan ROM Explorer.') from exc
    meshes = _geometry(data)
    if extent != asset['container_size'] or index >= len(meshes):
        raise formats.AssetError('The model geometry changed. Rescan ROM Explorer.')
    name, vertices, faces = meshes[index]
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    note = ('Rest-pose geometry; materials and animation are not applied.' if asset.get('rest_pose') else
            'Local geometry before skeleton transforms; materials and animation are not applied.')
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges), points=list(range(len(vertices))),
                details=dict(format='Iguana skinned geometry', name=name, vertices=len(vertices), triangles=len(faces)),
                note=note,
                settings={**asset['preview_settings'], 'mesh':index})

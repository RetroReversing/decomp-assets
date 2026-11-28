"""Bounded local meshes in hierarchical archive geometry records.

Token compression and record layouts are documented by LibLR1:
https://github.com/DustStormPettigrew/LibLR1
"""
import math
import re
import struct

from .. import formats
from . import ljam_textures

LAYOUT = 'ljam-geometry'


def _tokens(data):
    pos, out, definitions = 0, [], {}

    def take(n):
        nonlocal pos
        if n < 0 or pos+n > len(data):
            raise ValueError('truncated')
        result = data[pos:pos+n]
        pos += n
        return result

    def token():
        value = take(1)[0]
        return int.from_bytes(take(2), 'little') if value == 19 else value

    def emit(kind, depth=0):
        nonlocal pos
        if depth > 16 or len(out) > 200000:
            raise ValueError('too many tokens')
        if kind == 2:
            end = data.find(b'\0', pos, min(len(data), pos+1025))
            if end < 0:
                raise ValueError('unterminated string')
            out.append((kind, data[pos:end])); pos = end+1
        elif kind in (3, 4):
            value, = struct.unpack('<f' if kind == 3 else '<i', take(4))
            out.append((kind, value))
        elif kind in (11, 12):
            out.append((kind, int.from_bytes(take(1), 'little', signed=kind == 11)))
        elif kind in (13, 14):
            out.append((kind, int.from_bytes(take(2), 'little', signed=kind == 13)))
        elif kind in (15, 16, 17):
            value = int.from_bytes(take(2), 'little', signed=True)
            out.append((3, value/(4096 if kind == 15 else 32 if kind == 16 else 1)))
        elif kind == 18:
            out.append((3, take(1)[0]/127))
        elif kind == 20:
            count = int.from_bytes(take(2), 'little'); member = token()
            if count > 50000:
                raise ValueError('array too large')
            for _ in range(count):
                emit(member, depth+1)
        elif kind == 21:
            out.extend(((7, None), (4, int.from_bytes(take(4), 'little', signed=True)), (8, None), (8, None)))
        elif kind == 22:
            name, count = token(), take(1)[0]
            if name in definitions or count > 64:
                raise ValueError('bad structure')
            definitions[name] = [token() for _ in range(count)]
        elif kind in definitions:
            for member in definitions[kind]:
                emit(member, depth+1)
        else:
            out.append((kind, None))
    while pos < len(data):
        emit(token())
    return out


def _mesh(data):
    if not 1 <= len(data) <= 4*1024*1024:
        return None
    try:
        tokens = _tokens(data)
        at, vertices, faces, metadata = 0, None, None, None
        def read(expected):
            nonlocal at
            if at >= len(tokens) or tokens[at][0] != expected:
                raise ValueError('unexpected token')
            value = tokens[at][1]; at += 1
            return value
        def array_start():
            read(7); count = read(4); read(8); read(5)
            if not 0 <= count <= 20000:
                raise ValueError('bad count')
            return count
        while at < len(tokens):
            kind = tokens[at][0]; at += 1
            if kind == 0x33:
                scale = read(3)
                if not math.isfinite(scale):
                    raise ValueError('bad scale')
            elif kind == 0x27:
                for _ in range(array_start()): read(2)
                read(6)
            elif kind in (0x28, 0x29, 0x2a, 0x34):
                if vertices is not None:
                    raise ValueError('multiple vertex arrays')
                count = array_start(); vertices = []
                for _ in range(count):
                    point = [read(3) for _ in range(3)]
                    if not all(math.isfinite(x) and abs(x) < 1e7 for x in point):
                        raise ValueError('bad vertex')
                    vertices.append(point)
                    for _ in range({0x28:2,0x29:5,0x2a:2,0x34:0}[kind]): read(3)
                    if kind == 0x2a:
                        for _ in range(4): read(12)
                read(6)
            elif kind == 0x2d:
                if faces is not None: raise ValueError('multiple index arrays')
                faces = [[read(12) for _ in range(3)] for _ in range(array_start())]
                read(6)
            elif kind == 0x2e:
                if metadata is not None: raise ValueError('multiple metadata arrays')
                metadata = []
                for _ in range(array_start()):
                    k = tokens[at][0]; at += 1
                    if k in (0x27,0x32): metadata.append((k,read(14)))
                    elif k == 0x31: metadata.append((k,read(12),read(14),read(14)))
                    elif k == 0x2d: metadata.append((k,read(14),read(14)))
                    else: raise ValueError('unsupported metadata')
                read(6)
            else:
                raise ValueError('unsupported record')
        if not vertices or not faces or not metadata:
            return None
        resolved, seen, active, cache = [None]*len(faces), set(), False, [None]*256
        for item in metadata:
            if item[0] == 0x31:
                slot, offset, length = item[1:]
                if active or not 0 < length <= len(vertices)-offset or slot+length > len(cache):
                    return None
                cache[slot:slot+length] = range(offset, offset+length)
                active = True
            elif item[0] == 0x2d:
                first, count = item[1:]
                if not active or not 0 < count <= len(faces)-first:
                    return None
                for index in range(first, first+count):
                    if index in seen or any(cache[vertex] is None for vertex in faces[index]):
                        return None
                    seen.add(index)
                    resolved[index] = [cache[vertex] for vertex in faces[index]]
                active = False
        if active or len(seen) != len(faces):
            return None
        return vertices, resolved
    except (ValueError, IndexError, struct.error, OverflowError):
        return None


def regions(image, *, check=lambda: None, **kwargs):
    found = {}
    for match in re.finditer(b'LJAM', image):
        for name, start, size in ljam_textures._files(image, match.start()):
            if not name.upper().endswith(b'.GDB') or (start,size) in found:
                continue
            check()
            parsed = _mesh(image[start:start+size])
            if not parsed:
                continue
            vertices, faces = parsed
            found[(start,size)] = dict(offset=start,size=size,kind='3d model',media='model',layout=LAYOUT,
                label='Archive geometry',confidence='validated',nodes=1,vertices=len(vertices),triangles=len(faces),
                meshes=[dict(name='Mesh 1',vertices=len(vertices),triangles=len(faces))],
                reason='Bounded archive geometry groups resolve every local triangle index.',
                preview_settings=dict(source='rom',format='auto',offset=start,mesh=0))
    return list(found.values())


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    decoded = _mesh(image[start:start+size]) if 0 < size <= len(image) and 0 <= start <= len(image)-size else None
    if not decoded:
        raise formats.AssetError('The archive geometry changed. Scan ROM Explorer again.')
    points, faces = decoded
    edges = {tuple(sorted((face[i-1],face[i]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=points,triangles=len(faces),edges=sorted(edges),
        points=sorted({i for face in faces for i in face}),
        surfaces=[dict(indices=f,uv=[[0,0]]*3,colors=[[255]*4]*3,material=0) for f in faces],materials=[],
        details=dict(format='Archive geometry',vertices=len(points),triangles=len(faces)),
        note='Local geometry; scale, scene placement, materials and animation are separate.',settings=asset['preview_settings'])

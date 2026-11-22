"""Geometry built from bounded, compressed level drawing bytecode.

Opcode and container evidence: https://github.com/Tatsh/dade, xg1_level.py.
"""

import struct

from .. import formats
from . import lzhuf

LAYOUT = 'huffman-level-meshes'
_LIMIT = 4 * 1024 * 1024
_OPERANDS = {2: 1, 3: 3, 6: 0, 7: 0, 9: 2, 10: 0, 11: 0, 12: 1, 13: 1, 14: 0, 15: 0}


def _header(image, base):
    if not 0x2000 <= base <= len(image) - 68 or base % 16:
        return None
    words = struct.unpack_from('>17I', image, base)
    objects, count, stream, length = words[0], words[1], words[15], words[16]
    if (not 1 <= count <= 4096 or not 68 <= objects < stream or not 0 < length <= _LIMIT
            or base + objects + count * 40 > len(image) or base + stream >= len(image)):
        return None
    return words


def levels(image):
    # The startup table points to several independently checked containers.
    for start in range(0x1000, min(0x2000, len(image) - 20), 4):
        first = struct.unpack_from('>I', image, start)[0]
        if _header(image, first) is None:
            continue
        offsets = []
        at = start
        while at + 4 <= min(0x2000, len(image)):
            base = struct.unpack_from('>I', image, at)[0]
            if _header(image, base) is None:
                break
            offsets.append(base)
            at += 4
        if len(set(offsets)) >= 4:
            return sorted(set(offsets))
    return []


def meshes(image, base, limit):
    header = _header(image, base)
    if header is None:
        return []
    try:
        code = lzhuf.unpack(image[base + header[15]:limit], header[16], fill=0)
    except (formats.AssetError, IndexError):
        return []
    at = 0
    result = []
    for obj in range(header[1]):
        origin = struct.unpack_from('>3i', image, base + header[0] + obj * 40)
        slots = [None] * 32
        points, faces = [], []
        while at < len(code):
            opcode = code[at]
            at += 1
            if opcode == 0:
                break
            if opcode == 1:
                if at >= len(code):
                    return []
                count = code[at]
                at += 1
                if count > 32 or at + count * 10 > len(code):
                    return []
                for slot in range(count):
                    position = struct.unpack_from('>3h', code, at + slot * 10)
                    slots[slot] = len(points)
                    points.append(tuple(origin[i] + position[i] for i in range(3)))
                at += count * 10
            elif opcode in (4, 5):
                count = 1 if opcode == 4 else 2
                if at + count * 2 > len(code):
                    return []
                for _ in range(count):
                    value = struct.unpack_from('>H', code, at)[0]
                    at += 2
                    face = tuple(slots[(value >> shift) & 31] for shift in (10, 5, 0))
                    if all(index is not None for index in face) and len(set(face)) == 3:
                        faces.append(face)
            elif opcode == 8:
                if at >= len(code):
                    return []
                at += 1 + code[at] * 6
            elif opcode in _OPERANDS:
                at += _OPERANDS[opcode]
            else:
                return []
            if at > len(code):
                return []
        if faces:
            result.append((obj, points, faces))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    bases = levels(image)
    result = []
    for i, base in enumerate(bases):
        limit = bases[i + 1] if i + 1 < len(bases) else len(image)
        found = meshes(image, base, limit)
        if not found:
            continue
        rows = [dict(name=f'Object {index}', vertices=len(points), triangles=len(faces))
                for index, points, faces in found]
        result.append(dict(offset=base, size=68, limit=limit, kind='3d model', media='model', layout=LAYOUT,
                           label=f'Compressed level geometry ({len(rows)} objects)', confidence='validated',
                           meshes=rows, nodes=len(rows), triangles=sum(row['triangles'] for row in rows),
                           reason='A bounded level container expands to vertex and triangle commands.',
                           preview_settings=dict(format='auto', source='rom', offset=base, mesh=0)))
        check()
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    rows = meshes(image, asset['offset'], asset['limit'])
    if index >= len(rows):
        raise formats.AssetError('The level geometry changed. Rescan ROM Explorer.')
    _, vertices, faces = rows[index]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({index for face in faces for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Level geometry', vertices=len(vertices), triangles=len(faces)),
                note='Geometry uses level object origins; textures and scene placement are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

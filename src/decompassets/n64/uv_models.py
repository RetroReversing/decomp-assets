"""Read UVMD geometry with shared or per-material vertex arrays."""

import math
import re
import struct
from itertools import islice

from .. import formats
from .uv_textures import comm

_HEADER = struct.Struct('>HBBB')
_VERTEX = struct.Struct('>3hH2h4B')
_PART = struct.Struct('>4B6f')
_MATERIAL = struct.Struct('>4H12xH')
_WORD = struct.Struct('>H')


def _geometry(data):
    """Validate every vertex load and triangle against the stored vertex array."""
    try:
        count, transforms, _, _ = _HEADER.unpack_from(data)
        cursor = _HEADER.size+count*_VERTEX.size
        if not count or not transforms or cursor+2 > len(data):
            return None
        parts = data[cursor]
        cursor += 2
        if not 0 < parts <= 64:
            return None
        faces = []
        for _ in range(parts):
            materials, *fields = _PART.unpack_from(data, cursor)
            cursor += _PART.size
            if not all(map(math.isfinite, fields[3:])):
                return None
            for _ in range(materials):
                _, _, _, expected, commands = _MATERIAL.unpack_from(data, cursor)
                cursor += _MATERIAL.size
                cache = [None]*16
                triangles = 0
                for _ in range(commands):
                    opcode, = _WORD.unpack_from(data, cursor)
                    cursor += 2
                    if 0x4000 <= opcode <= 0x4fff:
                        face = tuple(cache[(opcode >> shift) & 15] for shift in (8, 4, 0))
                        if None in face:
                            return None
                        faces.append(face)
                        triangles += 1
                        if len(faces) > 32768:
                            return None
                    elif opcode < 0x4000:
                        load = data[cursor]
                        cursor += 1
                        start, length = load & 15, (load >> 4)+1
                        if start+length > len(cache) or opcode+length > count:
                            return None
                        cache[start:start+length] = range(opcode, opcode+length)
                    else:
                        return None
                if triangles != expected:
                    return None
        distance, = struct.unpack_from('>f', data, cursor)
        if not math.isfinite(distance) or distance < 0 or len(data)-cursor-4 < transforms*64:
            return None
    except (struct.error, IndexError):
        return None
    return (count, faces) if faces else None


_LOCAL_HEADER = struct.Struct('>4B3H3f')
_LOCAL_LOD = struct.Struct('>BBf')
_LOCAL_PART = struct.Struct('>3B6f3B')
_LOCAL_MATERIAL = struct.Struct('>4I6H')


def _local_commands(data, cursor, commands, base, count):
    """Resolve five-bit cache indices using this material's vertex block."""
    cache = [None]*32
    faces = []
    for _ in range(commands):
        word, = _WORD.unpack_from(data, cursor)
        cursor += 2
        if word & 0x8000:
            face = tuple(cache[(word >> shift) & 31] for shift in (10, 5, 0))
            if None in face:
                return None
            faces.append(face)
        else:
            load = data[cursor]
            cursor += 1
            slot = load & 31
            length = ((word & 0x6000) >> 10) + (load >> 5) + 1
            first = word & 0x1fff
            if slot + length > len(cache) or first + length > count:
                return None
            cache[slot:slot+length] = range(base+first, base+first+length)
    return cursor, faces


def _local_geometry(data):
    """Validate every LOD and return the first one with drawable geometry."""
    try:
        levels, transforms, flags, reserved, count, _, _, *scale = _LOCAL_HEADER.unpack_from(data)
        if not 0 < levels <= 32 or not count or reserved or not all(map(math.isfinite, scale)):
            return None
        # The high flag adds ten words, three halfwords and a byte.
        cursor = _LOCAL_HEADER.size + (47 if flags & 0x80 else 0)
        total = 0
        drawable = None
        for _ in range(levels):
            vertices, faces = [], []
            level_start = total
            parts, _, distance = _LOCAL_LOD.unpack_from(data, cursor)
            cursor += _LOCAL_LOD.size
            if not math.isfinite(distance) or distance < 0:
                return None
            for _ in range(parts):
                _, _, _, *part = _LOCAL_PART.unpack_from(data, cursor)
                cursor += _LOCAL_PART.size
                if not all(map(math.isfinite, part[:6])):
                    return None
                for _ in range(part[-1]):
                    material = _LOCAL_MATERIAL.unpack_from(data, cursor)
                    stored, commands = material[4], material[8]
                    cursor += _LOCAL_MATERIAL.size
                    end = cursor + stored*_VERTEX.size
                    if end > len(data) or total + stored > count:
                        return None
                    if drawable is None:
                        vertices.extend(_VERTEX.iter_unpack(data[cursor:end]))
                    decoded = _local_commands(data, end, commands, total-level_start, stored)
                    if decoded is None:
                        return None
                    cursor, triangles = decoded
                    if drawable is None:
                        faces.extend(triangles)
                        if len(faces) > 32768:
                            return None
                    total += stored
            if drawable is None and faces:
                drawable = vertices, faces
        tail = cursor + transforms*64
        if total != count or not 0 <= len(data)-tail < 8 or any(data[tail:]):
            return None
    except (struct.error, IndexError):
        return None
    return drawable


def _records(data):
    if geometry := _geometry(data):
        count, faces = geometry
        return list(_VERTEX.iter_unpack(data[_HEADER.size:_HEADER.size+count*_VERTEX.size])), faces
    return _local_geometry(data) or _paired_geometry(data)


def _read(image, offset):
    chunk = comm(image, offset, b'UVMD')
    return _records(chunk[0]) if chunk else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    for match in islice(re.finditer(rb'FORM.{4}UVMD', image, re.S), 4096):
        offset = match.start()
        if offset % 2:
            continue
        check()
        if geometry := _read(image, offset):
            records, faces = geometry
            size = 8+int.from_bytes(image[offset+4:offset+8], 'big')
            results.append(dict(offset=offset, size=size, label=f'UV model {len(results)+1}', kind='3d model',
                                media='model', layout='uv-model', confidence='validated', vertices=len(records),
                                triangles=len(faces), reason='The model resolves packed triangles through bounded vertex-cache loads.',
                                preview_settings=dict(format='auto', source='rom', offset=offset)))
    return results


def preview(image, asset, selection):
    chunk = comm(image, asset['offset'], b'UVMD')
    geometry = _records(chunk[0]) if chunk else None
    if geometry is None:
        raise formats.AssetError('The UV model geometry no longer matches. Rescan ROM Explorer.')
    records, faces = geometry
    surfaces, edges, points = [], set(), set()
    for face in faces:
        points.update(face)
        edges.update(tuple(sorted((face[i], face[(i+1)%3]))) for i in range(3))
        surfaces.append(dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0))
    return dict(media='model', vertices=[row[:3] for row in records], triangles=len(faces), edges=sorted(edges),
                points=sorted(points), surfaces=surfaces, materials=[],
                details=dict(format='UV model', vertices=len(records), triangles=len(faces)),
                note='First drawable level of detail in local coordinates. Material textures and part transforms are separate.',
                settings=asset['preview_settings'])


def _paired_commands(data, cursor, expected, base, count):
    cache = [None]*32
    faces = []
    for _ in range(65536):
        if len(faces) == expected:
            return cursor, faces
        word, = _WORD.unpack_from(data, cursor)
        cursor += 2
        if word & 0x8000:
            indices = tuple((word >> shift) & 31 for shift in (10, 5, 0))
            face = tuple(cache[index] for index in indices)
            if None in face:
                return None
            faces.append(face)
        elif word & 0x4000:
            low, = _WORD.unpack_from(data, cursor)
            cursor += 2
            pair = (word << 16) | low
            for shifts in ((25, 20, 15), (10, 5, 0)):
                face = tuple(cache[(pair >> shift) & 31] for shift in shifts)
                if None in face:
                    return None
                faces.append(face)
        else:
            load = data[cursor]
            cursor += 1
            slot = load & 31
            length = ((word & 0x3000) >> 9) + (load >> 5) + 1
            first = word & 0x0fff
            if slot+length > len(cache) or first+length > count:
                return None
            cache[slot:slot+length] = range(base+first, base+first+length)
        if len(faces) > expected:
            return None
    return None


def _paired_geometry(data):
    try:
        levels, transforms, flags, reserved, count, _, _, *scale = _LOCAL_HEADER.unpack_from(data)
        if not 0 < levels <= 32 or not count or reserved or not all(map(math.isfinite, scale)):
            return None
        cursor = _LOCAL_HEADER.size + (47 if flags & 0x80 else 0)
        total = 0
        drawable = None
        for _ in range(levels):
            vertices, faces = [], []
            level_start = total
            parts, _, distance = _LOCAL_LOD.unpack_from(data, cursor)
            cursor += _LOCAL_LOD.size
            if not math.isfinite(distance) or distance < 0:
                return None
            for _ in range(parts):
                _, _, _, *part = _LOCAL_PART.unpack_from(data, cursor)
                cursor += _LOCAL_PART.size
                if not all(map(math.isfinite, part[:6])):
                    return None
                for _ in range(part[-1]):
                    material = struct.unpack_from('>4I4H', data, cursor)
                    stored, expected = material[4:6]
                    cursor += 24
                    end = cursor + stored*_VERTEX.size
                    if end > len(data) or total + stored > count or expected > 32768:
                        return None
                    if drawable is None:
                        vertices.extend(_VERTEX.iter_unpack(data[cursor:end]))
                    decoded = _paired_commands(data, end, expected, total-level_start, stored)
                    if decoded is None:
                        return None
                    cursor, triangles = decoded
                    if drawable is None:
                        faces.extend(triangles)
                    total += stored
            if drawable is None and faces:
                drawable = vertices, faces
        tail = cursor + transforms*64
        if total != count or not 0 <= len(data)-tail < 8 or any(data[tail:]):
            return None
    except (struct.error, IndexError):
        return None
    return drawable

"""Read the first LOD of UVMD files with a shared vertex array and packed triangle commands."""

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


def _read(image, offset):
    chunk = comm(image, offset, b'UVMD')
    return _geometry(chunk[0]) if chunk else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    for match in islice(re.finditer(rb'FORM.{4}UVMD', image, re.S), 4096):
        offset = match.start()
        if offset % 4:
            continue
        check()
        if geometry := _read(image, offset):
            count, faces = geometry
            size = 8+int.from_bytes(image[offset+4:offset+8], 'big')
            results.append(dict(offset=offset, size=size, label=f'UV model {len(results)+1}', kind='3d model',
                                media='model', layout='uv-model', confidence='validated', vertices=count,
                                triangles=len(faces), reason='The first LOD resolves packed triangles through bounded vertex-cache loads.',
                                preview_settings=dict(format='auto', source='rom', offset=offset)))
    return results


def preview(image, asset, selection):
    chunk = comm(image, asset['offset'], b'UVMD')
    geometry = _geometry(chunk[0]) if chunk else None
    if geometry is None:
        raise formats.AssetError('The UV model geometry no longer matches. Rescan ROM Explorer.')
    count, faces = geometry
    records = list(_VERTEX.iter_unpack(chunk[0][_HEADER.size:_HEADER.size+count*_VERTEX.size]))
    surfaces, edges, points = [], set(), set()
    for face in faces:
        points.update(face)
        edges.update(tuple(sorted((face[i], face[(i+1)%3]))) for i in range(3))
        surfaces.append(dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0))
    return dict(media='model', vertices=[row[:3] for row in records], triangles=len(faces), edges=sorted(edges),
                points=sorted(points), surfaces=surfaces, materials=[],
                details=dict(format='UV model', vertices=count, triangles=len(faces)),
                note='First level of detail in local coordinates. Material textures and part transforms are separate.',
                settings=asset['preview_settings'])

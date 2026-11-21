"""Resolve Borg2 model geometry from its local F3DEX2 display lists."""

import struct

from .. import formats
from . import borg

_VERTEX = struct.Struct('>3hH2h4B')
_PAIR = struct.Struct('>II')
_WORD = struct.Struct('>I')
_MAX_TRIANGLES = 32768


def geometry(data):
    if len(data) < 80:
        return None
    lists, = _WORD.unpack_from(data, 4)
    table, bounds, vertices, count, _, materials = struct.unpack_from('>6I', data, 44)
    if not (1 <= lists <= 128 and 1 <= count <= 16384
            and 80 <= bounds <= vertices-8*16
            and 80 <= vertices <= len(data)-count*16
            and 80 <= table <= len(data)-lists*4
            and 80 <= materials <= len(data)-lists*20):
        return None
    points = list(_VERTEX.iter_unpack(data[vertices:vertices+count*16]))
    faces = []
    for i in range(lists):
        start, = _WORD.unpack_from(data, table+4*i)
        if start%8 or not 80 <= start < table:
            return None
        flags, = _WORD.unpack_from(data, materials+20*i)
        if not _list(data, start, table, count, (vertices-bounds)//16, flags, faces):
            return None
    return (points, faces) if faces else None


def _list(data, start, end, count, boxes, flags, faces):
    cache = [None]*32
    colors = {}
    for at in range(start, end-7, 8):
        w0, w1 = _PAIR.unpack_from(data, at)
        op = w0 >> 24
        if w0 == 0xdf000000 and w1 == 0:
            return True
        if op == 1:
            amount, stop = (w0 >> 12)&255, (w0 >> 1)&127
            first, segment = (w1 & 0xffffff)//16, w1 >> 24
            if not (0 < amount <= stop <= 32 and not (w0 & 1 or w1 & 15)):
                return False
            if segment == 10 and first+amount <= count:
                cache[stop-amount:stop] = range(first, first+amount)
            elif segment == 14 and first+amount <= boxes:
                cache[stop-amount:stop] = [None]*amount
            else:
                return False
            for slot in range(stop-amount, stop):
                colors.pop(slot, None)
        elif op in (5, 6):
            for word in (w0,) if op == 5 else (w0, w1):
                slots = [(word >> shift)&255 for shift in (16, 8, 0)]
                if any(slot%2 or slot//2 >= 32 or cache[slot//2] is None for slot in slots):
                    return False
                faces.append((tuple(cache[s//2] for s in slots), bool(flags & 8),
                              tuple(colors.get(s//2) for s in slots)))
                if len(faces) > _MAX_TRIANGLES:
                    return False
        elif op == 2:
            slot, field = (w0 & 0xffff)//2, (w0 >> 16)&255
            if w0 & 1 or slot >= 32 or cache[slot] is None or field not in (0x10, 0x14):
                return False
            if field == 0x10:
                colors[slot] = tuple(w1.to_bytes(4, 'big'))
        elif op != 3:
            return False
    return False


def regions(image, rows, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, (kind, compression, stored, expanded, offset) in enumerate(rows):
        if kind != 2:
            continue
        check()
        try:
            data = borg.member(image, offset, stored, expanded, compression)
        except formats.AssetError:
            continue
        if mesh := geometry(data):
            points, faces = mesh
            result.append(dict(offset=offset, size=stored, kind='3d model', media='model', layout='borg-model',
                               confidence='validated', label=f'Borg mesh {index}', compression=compression,
                               expanded_size=expanded, vertices=len(points), triangles=len(faces),
                               reason='The Borg member bounds the vertex records and every triangle resolves to a loaded vertex.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    data = borg.member(image, asset['offset'], asset['size'], asset['expanded_size'], asset['compression'])
    mesh = geometry(data)
    if mesh is None:
        raise formats.AssetError('The Borg mesh changed. Rescan ROM Explorer.')
    records, faces = mesh
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face, _, _ in faces for i in range(3)}
    surfaces = []
    for face, colored, overrides in faces:
        colors = [override or (records[i][6:] if colored else (255,255,255,records[i][9]))
                  for i, override in zip(face, overrides)]
        surfaces.append(dict(indices=face, uv=[[0,0]]*3, colors=colors, material=0))
    return dict(media='model', vertices=[row[:3] for row in records], triangles=len(faces),
                edges=sorted(edges), points=sorted({point for face, _, _ in faces for point in face}),
                surfaces=surfaces, materials=[], settings=asset['preview_settings'],
                details=dict(format='Borg2 mesh', vertices=len(records), triangles=len(faces)),
                note='Local mesh coordinates. Scene assembly and material textures are separate.')

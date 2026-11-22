"""Packed vertex and triangle scripts in loader-referenced model banks."""

import struct

from .. import formats
from . import rle_texture_tables

LAYOUT = 'packed-model-table'
_ROW = struct.Struct('>IIHHI')


def _rows(image, start):
    rows = []
    for index in range(2048):
        at = start+index*_ROW.size
        if at < 0 or at+_ROW.size > len(image):
            break
        commands, vertices, flags, reserved, runtime = _ROW.unpack_from(image, at)
        count = flags & 0x3ff
        if (runtime or reserved or not 3 <= count <= 1023 or commands != vertices+8*count
                or rows and vertices <= rows[-1][1]):
            break
        rows.append((commands, vertices, flags))
    return rows


def _signed12(value):
    return (value ^ 0x800)-0x800


def _mesh(image, base, row, limit):
    commands, vertex, flags = row
    count = flags & 0x3ff
    begin, script = base+vertex, base+commands
    if not 0 <= begin < script < limit <= len(image) or script-begin != count*8:
        return None
    scale = 4 if flags & 0x4000 else 1
    vertices = [(scale*_signed12((left >> 12) & 0xfff), scale*_signed12(left & 0xfff),
                 scale*_signed12((right >> 20) & 0xfff))
                for left, right in struct.iter_unpack('>2I', image[begin:script])]
    cache = [None]*16
    slot = 0
    faces = []
    for at in range(script, min(limit, script+65536)-1, 2):
        word, = struct.unpack_from('>H', image, at)
        if word == 0xffff:
            return (at+2, vertices, faces) if faces else None
        kind = word & 0xc000
        if kind == 0x4000:
            first, length = (word & 0x3ff0) >> 4, (word & 15)+1
            if slot+length > 16 or first+length > count:
                return None
            cache[slot:slot+length] = range(first, first+length)
            slot += length
        elif kind == 0x8000:
            face = tuple(cache[(word >> shift) & 15] for shift in (8, 4, 0))
            if None in face:
                return None
            faces.append(face)
            if len(faces) > 32768:
                return None
            slot = 0
    return None


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    if not context:
        return []
    tables, banks = rle_texture_tables._references(image, context, check)
    result, seen = [], set()
    for table in tables:
        rows = _rows(image, table)
        if len(rows) < 4:
            continue
        matches = []
        for base, end in banks:
            check()
            found = []
            for left, right in zip(rows, rows[1:]):
                limit = base+right[1]
                if limit <= end and (mesh := _mesh(image, base, left, limit)):
                    found.append((left, limit, mesh))
            # A few accidental scripts can fit unrelated banks; most entries
            # must agree on one bank before any of them are classified.
            if len(found) >= 3 and len(found)*5 >= (len(rows)-1)*4:
                matches.append((base, found))
        if len(matches) != 1:
            continue
        base, found = matches[0]
        for row, limit, (end, vertices, faces) in found:
            start = base+row[1]
            if start in seen:
                continue
            seen.add(start)
            result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                               confidence='inferred', label='Packed model mesh', vertices=len(vertices),
                               triangles=len(faces), bank=base, row=list(row), limit=limit,
                               reason='A code-referenced model table uniquely fits this bank; packed vertex loads and triangles resolve.',
                               preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    mesh = _mesh(image, asset['bank'], asset['row'], asset['limit'])
    if not mesh or mesh[0] != asset['offset']+asset['size']:
        raise formats.AssetError('The packed model changed. Rescan ROM Explorer.')
    _, vertices, faces = mesh
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({index for face in faces for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Packed model', vertices=len(vertices), triangles=len(faces)),
                note='Local model geometry; materials, animation and scene transforms are separate.',
                settings=asset['preview_settings'])

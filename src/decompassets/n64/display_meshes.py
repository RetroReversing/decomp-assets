"""Local meshes from closed F3DEX lists with corroborated ROM address mappings."""

import struct

from .. import formats

_VERTEX = struct.Struct('>3hH2h4B')
_COMMAND = struct.Struct('>II')
_MAX_COMMANDS = 4096
_STATE = frozenset((0xb6, 0xb7, 0xb9, 0xba, 0xbb, 0xbc)) | frozenset(range(0xe6, 0x100))


def geometry(image, offset, end, displacements):
    from .display_lists import _space

    if not 0 <= offset < end or offset % 8:
        return None

    cache, vertices, lookup, faces = [None]*32, [], {}, []
    for at in range(offset, min(end, offset+_MAX_COMMANDS*8), 8):
        if at+8 > len(image):
            return None
        w0, w1 = _COMMAND.unpack_from(image, at)
        cmd = w0 >> 24
        if cmd == 0xb8 and not (w0 & 0xffffff or w1):
            return (at+8, vertices, faces) if faces else None
        if cmd == 4:
            count, dest = (w0 >> 10)&63, (w0 >> 17)&127
            mapping = displacements.get(_space(w1))
            if mapping is None or not count or count+dest > len(cache) or w0 & 0x10000 or (w0 & 1023) != count*16-1:
                return None
            start = mapping+(w1 & 0xffffff)
            if start < 0 or start%8 or start+count*_VERTEX.size > len(image):
                return None
            for slot, pointer in enumerate(range(start, start+count*_VERTEX.size, _VERTEX.size), dest):
                if pointer not in lookup:
                    x, y, z, flag, *_ = _VERTEX.unpack_from(image, pointer)
                    if flag:
                        return None
                    lookup[pointer] = len(vertices)
                    vertices.append((x, y, z))
                cache[slot] = lookup[pointer]
        elif cmd in (0xbf, 0xb1):
            if w1 >> 24 or cmd == 0xbf and w0 & 0xffffff:
                return None
            for word in (w1,) if cmd == 0xbf else (w0, w1):
                slots = tuple((word >> shift)&255 for shift in (16, 8, 0))
                if any(slot%2 or slot//2 >= len(cache) or cache[slot//2] is None for slot in slots):
                    return None
                faces.append(tuple(cache[slot//2] for slot in slots))
        elif cmd not in _STATE:
            return None
    return None


def regions(image, group, displacements, pointers, check):
    # The first display-list marker can be preceded by setup commands.
    # Start only where a stored pointer independently corroborates the mapping.
    starts = sorted({address+delta for space, delta in displacements.items()
                     for address in pointers.get(space, ())
                     if group['start']-128 <= address+delta < group['end'] and (address+delta)%8 == 0})
    result, accepted_end = [], 0
    for offset in starts:
        if offset < accepted_end:
            continue
        check()
        parsed = geometry(image, offset, group['end']+64, displacements)
        if parsed is None:
            continue
        end, vertices, faces = parsed
        accepted_end = end
        result.append(dict(offset=offset, size=end-offset, label='F3DEX display-list mesh', kind='3d model',
                           confidence='inferred', media='model', layout='f3dex-mesh', vertices=len(vertices),
                           triangles=len(faces), address_maps=sorted(displacements.items()),
                           reason='Stored list pointers corroborate the ROM mapping. Vertex loads and triangle slots resolve before the list ends.',
                           preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    offset = asset['offset']
    parsed = geometry(image, offset, offset+asset['size'], dict(asset['address_maps']))
    if parsed is None:
        raise formats.AssetError('The F3DEX list changed. Rescan ROM Explorer.')
    _, vertices, faces = parsed
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0)
                          for face in faces],
                materials=[], details=dict(format='F3DEX display-list mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry from one display list. Scene transforms and materials are separate.',
                settings=asset['preview_settings'])

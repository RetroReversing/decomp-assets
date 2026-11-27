"""Local meshes from closed Fast3D, F3DEX and F3DEX2 lists with corroborated mappings."""

import struct

from .. import formats

_VERTEX = struct.Struct('>3hH2h4B')
_COMMAND = struct.Struct('>II')
_MAX_COMMANDS = 4096
_STATE = frozenset((0xb6, 0xb7, 0xb9, 0xba, 0xbb, 0xbc, 0xd7, 0xd9, 0xe2, 0xe3)) | frozenset(range(0xe6, 0x100))


def geometry(image, offset, end, displacements, *, extra_state=None, vertex_end=None, vertex_flag_mask=0, allow_padded_load=False):
    from .display_lists import _space, _vertex_count

    if not 0 <= offset < end or offset % 8:
        return None

    vertex_end = len(image) if vertex_end is None else min(vertex_end,len(image))
    cache, vertices, lookup, faces = [None]*64, [], {}, []
    dialect = None
    legacy = False
    for at in range(offset, min(end, offset+_MAX_COMMANDS*8), 8):
        if at+8 > len(image):
            return None
        w0, w1 = _COMMAND.unpack_from(image, at)
        cmd = w0 >> 24
        if cmd == (0xdf if dialect == 2 else 0xb8) and not (w0 & 0xffffff or w1):
            return (at+8, vertices, faces) if faces else None
        if extra_state and extra_state(w0, w1):
            continue
        # F3DEX lists can load viewport/lights and pop a matrix around
        # their geometry. The preview uses the local vertex coordinates.
        legacy_move = (w0 & 0xff01ffff == 0x03000010 and 0x80 <= (w0 >> 16) & 0xff <= 0x9e
                       and _space(w1) is not None)
        if legacy_move or (w0, w1) == (0xbd000000, 0):
            if dialect == 2:
                return None
            legacy = True
            continue
        if cmd in (1, 4):
            fast_count = ((w0 >> 20) & 15) + 1
            fast = cmd == 4 and (w0 & 0xffff) == fast_count * 16
            variant = 2 if cmd == 1 else 3 if fast else 1
            if legacy and variant == 2 or dialect is not None and dialect != variant:
                return None
            dialect = variant
            if dialect == 2:
                count = _vertex_count(w0)
                dest = ((w0 >> 1)&127)-count
                length = count * _VERTEX.size
            elif dialect == 3:
                count, dest = fast_count, (w0 >> 16) & 15
                length = count * 16
            else:
                count, dest = (w0 >> 10)&63, (w0 >> 17)&127
                length = (w0 & 1023) + 1
                if w0 & 0x10000 or (length != count * 16 and not (allow_padded_load and length == (count + 1) * 16)):
                    return None
            limit = 64 if dialect == 2 else 16 if dialect == 3 else 32
            space = _space(w1)
            if space is None and not w1 >> 24 and 0 in displacements:
                space = 0  # a recogniser explicitly established file-relative addresses
            mapping = displacements.get(space)
            if mapping is None or not count or not 0 <= dest < dest+count <= limit:
                return None
            start = mapping+(w1 & 0xffffff)
            if start < 0 or start%8 or start + length > vertex_end:
                return None
            for slot, pointer in enumerate(range(start, start+count*_VERTEX.size, _VERTEX.size), dest):
                if pointer not in lookup:
                    x, y, z, flag, *_ = _VERTEX.unpack_from(image, pointer)
                    if flag & ~vertex_flag_mask:
                        return None
                    lookup[pointer] = len(vertices)
                    vertices.append((x, y, z))
                cache[slot] = lookup[pointer]
        elif cmd in (0xbf, 0xb1, 5, 6, 7):
            modern = cmd in (5, 6, 7)
            if (dialect != (2 if modern else 1) and not (dialect == 3 and cmd == 0xbf)
                    or w1 >> 24 or cmd == 0xbf and w0 & 0xffffff or cmd == 5 and w1):
                return None
            words = (w0,) if cmd == 5 else (w1,) if cmd == 0xbf else (w0, w1)
            for word in words:
                slots = tuple((word >> shift)&255 for shift in (16, 8, 0))
                divisor = 10 if dialect == 3 else 2
                if any(slot % divisor or slot//divisor >= len(cache) or cache[slot//divisor] is None for slot in slots):
                    return None
                faces.append(tuple(cache[slot//divisor] for slot in slots))
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
        if image[end-8] == 0xdf:
            format_name = 'F3DEX2'
        else:
            vertex = next((_COMMAND.unpack_from(image, at)[0] for at in range(offset, end, 8) if image[at] == 4), 0)
            count = ((vertex >> 20) & 15) + 1
            format_name = 'Fast3D' if (vertex & 0xffff) == count*16 else 'F3DEX'
        result.append(dict(offset=offset, size=end-offset, label=f'{format_name} display-list mesh', kind='3d model',
                           confidence='inferred', media='model', layout='f3dex-mesh', vertices=len(vertices),
                           triangles=len(faces), address_maps=sorted(displacements.items()),
                           reason='Stored list pointers corroborate the ROM mapping. Vertex loads and triangle slots resolve before the list ends.',
                           preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection, *, extra_state=None, vertex_flag_mask=0, allow_padded_load=False):
    offset = asset['offset']
    parsed = geometry(image, offset, offset+asset['size'], dict(asset['address_maps']),
                      vertex_end=asset.get('vertex_end'), extra_state=extra_state, vertex_flag_mask=vertex_flag_mask,
                      allow_padded_load=allow_padded_load)
    if parsed is None:
        raise formats.AssetError('The display list changed. Rescan ROM Explorer.')
    _, vertices, faces = parsed
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0)
                          for face in faces],
                materials=[], details=dict(format=asset['label'], vertices=len(vertices), triangles=len(faces)),
                note='Local geometry from one display list. Scene transforms and materials are separate.',
                settings=asset['preview_settings'])

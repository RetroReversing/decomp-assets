"""Model files with a segmented display list and a separate vertex block."""

import re
import struct

from .. import formats
from . import display_meshes, packed_anim

LAYOUT = 'segmented-model-resource'
_MARKER = re.compile(b'\0\0\x08\x0b\x09\x04\x0a\0')
_LIMIT = 4 * 1024 * 1024
_DIRECTORY = re.compile(rb'\0\0\0\x02....\0\0\0\x03....(?:\xff{4}){5}', re.S)


def _model(image, offset):
    if offset < 0 or offset + 28 > len(image):
        return None
    commands, vertex_bytes, tail = struct.unpack_from('<3I', image, offset)
    start = offset + 12
    vertices = start + commands
    end = vertices + vertex_bytes
    if (not 24 <= commands <= _LIMIT or not 8 <= vertex_bytes <= _LIMIT or tail > _LIMIT
            or end + tail > len(image) or struct.unpack_from('>I', image, start)[0] != commands - 16
            or image[start+4:start+12] != _MARKER.pattern):
        return None
    count = struct.unpack_from('>H', image, vertices)[0]
    if not 3 <= count <= 4096 or vertex_bytes != 8 + 16 * count:
        return None
    parsed = display_meshes.geometry(image, start + 16, vertices, {9: vertices + 8}, vertex_end=end,
                                     extra_state=lambda w0,w1: w0 == 0xda380003 and w1 >> 24 == 10)
    if not parsed or parsed[0] != vertices:
        return None
    return parsed[1], parsed[2], end + tail - offset


def _prefix(source):
    """Read only the file header before deciding whether to expand a member."""
    ring = bytearray(b' ' * 0xfee + bytes(18))
    written = bytearray(b'\1' * 0xfee + bytes(18))
    destination, cursor, output = 0xfee, 0, bytearray()
    try:
        while len(output) < 24:
            flags = source[cursor]
            cursor += 1
            for bit in range(8):
                if flags & (1 << bit):
                    values = [source[cursor]]
                    cursor += 1
                    for value in values:
                        output.append(value)
                        ring[destination] = value
                        written[destination] = 1
                        destination = (destination + 1) & 4095
                else:
                    low, high = source[cursor:cursor + 2]
                    cursor += 2
                    first = low | ((high & 0xf0) << 4)
                    for i in range((high & 15) + 3):
                        pointer = (first + i) & 4095
                        if not written[pointer]:
                            return None
                        value = ring[pointer]
                        output.append(value)
                        ring[destination] = value
                        written[destination] = 1
                        destination = (destination + 1) & 4095
                if len(output) >= 24:
                    return output[:24]
    except (IndexError, ValueError):
        return None
    return None


def _compressed(image, check):
    for hit in _DIRECTORY.finditer(image):
        base = hit.start()
        count, length = struct.unpack_from('>I4xI', image, base + 4)
        if not 8 <= count <= 8192 or base + length > len(image) or 36 + 16 * count > length:
            continue
        rows = list(struct.iter_unpack('>4I', image[base + 36:base + 36 + 16 * count]))
        if any((flag not in (0, 1, 17) or flag == 0 and (offset or size or expanded)
                or flag and (not size or not expanded or offset < 36 + 16 * count
                             or offset + size > length or expanded > _LIMIT))
               for flag,offset,size,expanded in rows):
            continue
        for flag,offset,size,expanded in rows:
            if flag != 17:
                continue
            check()
            source = image[base + offset:base + offset + size]
            head = _prefix(source)
            if not head or head[16:24] != _MARKER.pattern:
                continue
            decoded = packed_anim._unpack(source, expanded, check)
            if decoded is None:
                continue
            data = bytes(4) + decoded
            found = _model(data, 4)
            if found:
                yield base + offset, size, expanded, found


def _asset(offset, size, found, **extra):
    vertices, faces, _ = found
    mesh = dict(name='Mesh 1', vertices=len(vertices), triangles=len(faces))
    return dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                label='Segmented display-list model', confidence='validated',
                reason='Section lengths, vertex records and display-list indices agree.',
                nodes=0, meshes=[mesh], vertices=len(vertices), triangles=len(faces),
                preview_settings=dict(source='rom', format='auto', offset=offset), **extra)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for hit in _MARKER.finditer(image):
        check()
        offset = hit.start() - 16
        found = _model(image, offset)
        if not found:
            continue
        result.append(_asset(offset, found[2], found))
    for offset,size,expanded,found in _compressed(image, check):
        result.append(_asset(offset, size, found, expanded_size=expanded))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    if 'expanded_size' in asset:
        source = image[asset['offset']:asset['offset'] + asset['size']]
        decoded = packed_anim._unpack(source, asset['expanded_size'], lambda: None)
        found = _model(bytes(4) + decoded, 4) if decoded is not None else None
    else:
        found = _model(image, asset['offset'])
    if not found:
        raise formats.AssetError('The model data changed. Rescan ROM Explorer.')
    vertices, faces, _ = found
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0)
                          for face in faces], materials=[],
                details=dict(format='Segmented display-list model', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry; runtime matrices and materials are separate.',
                settings=dict(format='auto', source='rom', offset=asset['offset'], mesh=0))

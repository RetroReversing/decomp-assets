"""Meshes with packed vertex-cache commands inside zlib members."""

import re
import struct
import zlib

from ..formats import AssetError

LAYOUT = 'zlib-packet-mesh'
_MARKER = re.compile(rb'\x78[\x01\x5e\x9c\xda]')
_LIMIT = 1024 * 1024
_PACKETS = {1: 2, 3: 6, 4: 3, 5: 5, 6: 8, 255: 1}


def _bounds(header):
    if len(header) < 0x24 or header[:2] != b'\x01\x03':
        return None
    count, start, commands = struct.unpack_from('>I20xII', header, 4)
    if 0 < count <= 16384 and 0x48 <= start < commands < _LIMIT and start + 16*count == commands:
        return count, start, commands
    return None


def _faces(data, cursor, count):
    # The two rendering passes reload the vertex blocks in ROM order. Their
    # materials can differ, but the validated geometry must agree.
    faces = [[], []]
    phase = loaded = slots = base = 0
    while cursor < len(data):
        opcode = data[cursor]
        if opcode == 0:
            if (phase == 1 and loaded == count and faces[0] and faces[0] == faces[1]
                    and len(data) - cursor <= 8 and not any(data[cursor:])):
                return faces[0]
            return None
        length = _PACKETS.get(opcode, 0)
        if not length or cursor + length > len(data):
            return None
        if opcode == 1:
            if loaded == count and phase == 0:
                phase, loaded = 1, 0
            slots, base = data[cursor + 1], loaded
            loaded += slots
            if not 1 <= slots <= 32 or loaded > count:
                return None
        elif opcode in (4, 5):
            for start in range(cursor + 1, cursor + length, 2):
                word = int.from_bytes(data[start:start + 2], 'big')
                indices = tuple((word >> shift) & 31 for shift in (10, 5, 0))
                if max(indices) >= slots:
                    return None
                faces[phase].append(tuple(base + index for index in indices))
        cursor += length
    return None


def _mesh(image, offset):
    try:
        stream = zlib.decompressobj()
        if not (bounds := _bounds(stream.decompress(image[offset:offset + 256], 0x24))):
            return None
        source = image[offset:offset + _LIMIT]
        stream = zlib.decompressobj()
        data = stream.decompress(source, _LIMIT + 1)
    except zlib.error:
        return None
    count, start, commands = bounds
    if not stream.eof or len(data) > _LIMIT or not (faces := _faces(data, commands, count)):
        return None
    vertices = [struct.unpack_from('>3h', data, index) for index in range(start, commands, 16)]
    colors = [list(data[index + 12:index + 16]) for index in range(start, commands, 16)]
    return len(source) - len(stream.unused_data), vertices, colors, faces


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, marker in enumerate(_MARKER.finditer(image)):
        if index % 128 == 0:
            check()
        offset = marker.start()
        if offset % 4 or not (mesh := _mesh(image, offset)):
            continue
        size, vertices, _, faces = mesh
        result.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                           confidence='validated', label=f'Packed mesh · {len(vertices)} vertices',
                           vertices=len(vertices), triangles=len(faces),
                           reason='Both packed passes agree on every triangle after resolving their vertex batches.',
                           preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    offset = asset['offset']
    mesh = _mesh(image, offset)
    if mesh is None or mesh[0] != asset['size']:
        raise AssetError('The compressed mesh changed. Rescan ROM Explorer.')
    _, vertices, colors, faces = mesh
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({index for face in faces for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[colors[i] for i in face], material=0)
                          for face in faces],
                materials=[], details=dict(format='Packed vertex-cache commands', vertices=len(vertices),
                                            triangles=len(faces)),
                note='Local geometry and vertex colors reconstructed from both rendering passes.',
                settings=asset['preview_settings'])

"""Local geometry from consecutive gzip vertex and Fast3D display-list members."""

import re
import struct
import zlib

from ..formats import AssetError

LAYOUT = 'gzip-display-mesh'
MARKER = re.compile(b'\x1f\x8b\x08\x08')
MAX_MEMBER = 1024 * 1024


def _name(image, start):
    if not MARKER.match(image, start):
        return b''
    end = image.find(b'\0', start + 10, start + 96)
    if end < 0:
        return b''
    name = image[start + 10:end]
    return name if re.fullmatch(rb'[A-Za-z0-9_]+\.raw', name) else b''


def _inflate(image, start):
    source = image[start:start + MAX_MEMBER]
    stream = zlib.decompressobj(31)
    try:
        data = stream.decompress(source, MAX_MEMBER + 1)
    except zlib.error:
        return None
    if stream.eof and 0 < len(data) <= MAX_MEMBER:
        return start + len(source) - len(stream.unused_data), data
    return None


def _bounds(geometry, display, segments):
    if len(geometry) < 0x4c:
        return None
    header = struct.unpack_from('>10I', geometry)
    if segments == {6} and header[0] == 0x4c and header[7] == len(geometry):
        return 6, header[5], header[6]
    scenery_size = header[5] - len(geometry)
    if (segments == {9} and header[4] == len(geometry) and header[6] == len(geometry) + 24
            and (scenery_size == len(display) or scenery_size == len(display) - 8 and not any(display[-8:]))):
        return 9, 0x50, header[7]
    if segments == {8} and header[6] in (0xfffffffc, 0xfffffffe) and header[7] in (0, 1):
        # Map geometry starts after its larger collision and scenery directory.
        return 8, 0xc8, header[8]
    return None


def _mesh(geometry, display):
    if len(display) % 8:
        return None
    commands = list(struct.iter_unpack('>2I', display))
    segments = {value >> 24 for word, value in commands if word >> 24 == 4}
    if not (region := _bounds(geometry, display, segments)):
        return None
    segment, start, end = region
    # Scenery objects are display-list fragments. The outer list ends them.
    if segment != 9 and not any(word == 0xb8000000 and value == 0 for word, value in commands):
        return None
    if not 0 < start < end <= len(geometry) or (end - start) % 16:
        return None
    slots, triangles = {}, []
    for word, value in commands:
        opcode = word >> 24
        if opcode == 4:
            count, slot = (word >> 20 & 15) + 1, word >> 16 & 15
            address = value & 0xffffff
            if word & 0xffff != 16 * count or slot + count > 16 or address % 16 or address + 16*count > end-start:
                return None
            slots.update((slot + i, address//16 + i) for i in range(count))
        elif opcode == 0xb8:
            slots.clear()
        elif opcode == 0xbf:
            indices = [value >> shift & 255 for shift in (16, 8, 0)]
            if any(index % 10 or index//10 not in slots for index in indices):
                return None
            triangles.append(tuple(slots[index//10] for index in indices))
    if not triangles:
        return None
    vertices = [struct.unpack_from('>3h', geometry, offset) for offset in range(start, end, 16)]
    return vertices, triangles


def _pair(image, start, name):
    if not (geometry := _inflate(image, start)):
        return None
    middle, vertex_data = geometry
    if _name(image, middle) != name[:-4] + b'_dl.raw' or not (display := _inflate(image, middle)):
        return None
    end, command_data = display
    if mesh := _mesh(vertex_data, command_data):
        return end, mesh
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for marker in MARKER.finditer(image):
        check()
        start = marker.start()
        if not (name := _name(image, start)) or name.endswith(b'_dl.raw'):
            continue
        if pair := _pair(image, start, name):
            end, (vertices, triangles) = pair
            found.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                              confidence='validated', label=name[:-4].decode('ascii'),
                              vertices=len(vertices), triangles=len(triangles),
                              reason='Named gzip geometry and display-list pair with resolved Fast3D vertex indices.',
                              preview_settings=dict(format='auto', source='rom', offset=start)))
    return found


def preview(image, asset, selection):
    start = asset['offset']
    name = _name(image, start)
    pair = _pair(image, start, name) if name else None
    if not pair or pair[0] != start + asset['size']:
        raise AssetError('The compressed display-list pair changed. Rescan ROM Explorer.')
    vertices, triangles = pair[1]
    edges = {tuple(sorted((face[i-1], face[i]))) for face in triangles for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(triangles), edges=sorted(edges),
                points=sorted({index for face in triangles for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in triangles],
                materials=[], details=dict(format='Fast3D', vertices=len(vertices), triangles=len(triangles)),
                note='Local geometry from the paired vertex and display-list members.',
                settings=asset['preview_settings'])

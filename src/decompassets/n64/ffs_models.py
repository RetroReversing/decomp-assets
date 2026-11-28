"""Local polygon groups in CUB files inside a chunked FFS filesystem."""
import math
import re
import struct

from .. import formats, rnc
from . import ffs

LAYOUT = 'ffs-cub-model'
MAX_FILE = 4 * 1024 * 1024


def meshes(data):
    """Read bounded vertex batches and polygon commands; leave materials and placement alone."""
    if len(data) < 8 or data[:4] != b'CUB\0':
        return None
    count = int.from_bytes(data[4:8], 'big')
    if not 1 <= count <= 4096:
        return None
    at = 8
    result = []
    for _ in range(count):
        if at + 60 > len(data):
            return None
        bounds = struct.unpack_from('>10f', data, at)
        if any(not math.isfinite(x) or abs(x) > 1e8 for x in bounds):
            return None
        vertices, commands = struct.unpack_from('>2I', data, at + 40)
        if not 3 <= vertices <= 8192 or not 1 <= commands <= 131072:
            return None
        start = at + 60
        command_at = start + vertices * 16
        end = command_at + commands * 8
        if end > len(data) or data[command_at + 7] != 11:
            return None
        first = loaded = 0
        faces = []
        for pos in range(command_at, end, 8):
            command = data[pos:pos + 8]
            op = command[7]
            if op == 1:
                first = int.from_bytes(command[:4], 'big')
                loaded = command[6]
                if not loaded or first + loaded > vertices:
                    return None
            elif op in (2, 3):
                indices = command[4:7] if op == 2 else command[3:7]
                if not loaded or max(indices) >= loaded:
                    return None
                indices = [first + i for i in indices]
                faces.append(tuple(indices[:3]))
                if len(indices) == 4:
                    faces.append((indices[0], indices[2], indices[3]))
            elif op not in (4, 5, 6, 7, 8, 9, 10, 11):
                return None
        if faces:
            result.append(dict(name=f'Mesh {len(result) + 1}', descriptor=start,
                               vertices=vertices, triangles=len(faces), faces=faces))
        at = end
    return result or None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for match in re.finditer(rb'RNC\x81', image):
        check()
        layout = rnc.chunked(image, match.start())
        if not layout:
            continue
        reader = ffs._Reader(image, layout, check)
        try:
            header = ffs.files(reader.read(0, 12), layout['size'])
            if not header:
                continue
            count, table = header
            for i in range(count):
                if i % 64 == 0:
                    check()
                ident, size, offset = struct.unpack('>3I', reader.read(12 + 24*i, 24 + 24*i))
                if not 8 <= size <= MAX_FILE or offset < table or offset + size > layout['size']:
                    continue
                if reader.read(offset, offset + 4) != b'CUB\0':
                    continue
                parsed = meshes(reader.read(offset, offset + size))
                if not parsed:
                    continue
                at, packed = layout['chunks'][offset // rnc.CHUNK_BYTES]
                descriptions = [{k: v for k, v in m.items() if k != 'faces'} for m in parsed]
                found.append(dict(offset=at, size=packed + (packed & 1), kind='3d model', media='model',
                                  layout=LAYOUT, confidence='validated', stream=match.start(),
                                  file=dict(id=ident, offset=offset, size=size), meshes=descriptions,
                                  label=f'Packed polygon groups ({len(parsed)} meshes)',
                                  vertices=sum(m['vertices'] for m in parsed),
                                  triangles=sum(m['triangles'] for m in parsed),
                                  reason='Bounded vertex batches and polygon indices agree throughout the packed file; '
                                         'placement and materials are separate.',
                                  preview_settings=dict(format='auto', source='rom', offset=at, mesh=0)))
        except (rnc.RncError, struct.error):
            continue
    return found


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    layout = rnc.chunked(image, asset['stream'])
    file = asset['file']
    try:
        data = rnc.unpack_chunked(image, layout, file['offset'], file['offset'] + file['size']) if layout else None
        parsed = meshes(data) if data else None
    except rnc.RncError:
        parsed = None
    if not parsed or index >= len(parsed):
        raise formats.AssetError('The packed model changed. Rescan ROM Explorer.')
    mesh = parsed[index]
    vertices = [struct.unpack_from('>3h', data, mesh['descriptor'] + i * 16) for i in range(mesh['vertices'])]
    faces = mesh['faces']
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                materials=[], details=dict(format='Packed polygon group', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings={**asset['preview_settings'], 'mesh': index})

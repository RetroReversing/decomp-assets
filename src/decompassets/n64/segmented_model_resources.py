"""Model files with a segmented display list and a separate vertex block."""

import re
import struct

from .. import formats
from . import display_meshes

LAYOUT = 'segmented-model-resource'
_MARKER = re.compile(b'\0\0\x08\x0b\x09\x04\x0a\0')
_LIMIT = 4 * 1024 * 1024


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


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for hit in _MARKER.finditer(image):
        check()
        offset = hit.start() - 16
        found = _model(image, offset)
        if not found:
            continue
        vertices, faces, size = found
        mesh = dict(name='Mesh 1', vertices=len(vertices), triangles=len(faces))
        result.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                           label='Segmented display-list model', confidence='validated',
                           reason='Section lengths, vertex records and display-list indices agree.',
                           nodes=0, meshes=[mesh], vertices=len(vertices), triangles=len(faces),
                           preview_settings=dict(source='rom', format='auto', offset=offset)))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
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

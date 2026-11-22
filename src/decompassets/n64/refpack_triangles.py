"""Triangle-list geometry in bounded RefPack resource tables."""
import math
import struct

from .. import formats, refpack

LAYOUT = 'refpack-triangle-list'


def mesh(data):
    if len(data) < 60 or data[:4] != b'\x05\x01\0\0':
        return None
    offsets = struct.unpack_from('<13I', data, 4)
    if offsets[0] != 56 or any(a > b for a, b in zip(offsets, offsets[1:])) or offsets[-1] > len(data):
        return None
    start, end = offsets[:2]
    count = int.from_bytes(data[start:start+4], 'little')
    if not 3 <= count <= 60000 or count % 3 or start+4+count*16 != end:
        return None
    vertices = []
    for i in range(count):
        point = struct.unpack_from('<3f', data, start+4+i*16)
        if any(not math.isfinite(v) or abs(v) > 1000000 for v in point):
            return None
        vertices.append(point)
    if len(set(vertices)) < 3:
        return None
    return vertices


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    at = 0
    while (at := image.find(b'\x10\xfb', at)) >= 0:
        start = at
        at += 2
        check()
        try:
            data, consumed = refpack.unpack(memoryview(image)[start:])
        except ValueError:
            continue
        points = mesh(data)
        if points is None:
            continue
        result.append(dict(offset=start, size=consumed, kind='3d model', media='model', layout=LAYOUT,
                           label=f'Compressed geometry ({len(points)//3} triangles)', confidence='inferred',
                           nodes=1, meshes=[dict(name='Geometry', vertices=len(points), triangles=len(points)//3)],
                           triangles=len(points)//3,
                           reason='The bounded record contains finite XYZ coordinates in groups of three; placement and materials are separate.',
                           preview_settings=dict(format='auto', source='rom', offset=start, mesh=0)))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    try:
        data, _ = refpack.unpack(memoryview(image)[asset['offset']:])
    except ValueError as error:
        raise formats.AssetError('The compressed geometry changed. Rescan ROM Explorer.') from error
    vertices = mesh(data)
    if vertices is None:
        raise formats.AssetError('The geometry changed. Rescan ROM Explorer.')
    faces = [tuple(range(i, i+3)) for i in range(0, len(vertices), 3)]
    edges = {tuple(sorted((f[i-1], f[i]))) for f in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=f, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for f in faces],
                materials=[], details=dict(format='Compressed triangle list', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=dict(asset['preview_settings']))

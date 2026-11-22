"""Static sector walls from compressed, nested N64 IWAD map resources."""

import re
import struct

from .. import formats
from . import iwad_sprites

LAYOUT = 'iwad-map-model'
_MAP = re.compile(r'MAP[0-9][0-9]$')


def geometry(data):
    if len(data) < 12 or data[:4] not in (b'IWAD', b'PWAD'):
        return None
    count, directory = struct.unpack_from('<II', data, 4)
    if not 8 <= count <= 32 or directory + count * 16 > len(data):
        return None
    lumps = {}
    for i in range(count):
        start, size, name = struct.unpack_from('<II8s', data, directory + i * 16)
        name = name.rstrip(b'\0')
        if start + size > directory or name in lumps:
            return None
        lumps[name] = data[start:start+size]
    required = (b'VERTEXES', b'LINEDEFS', b'SIDEDEFS', b'SECTORS')
    if any(name not in lumps for name in required):
        return None
    vert, lines, sides, sectors = (lumps[name] for name in required)
    if (not vert or len(vert) % 8 or not lines or len(lines) % 16 or not sides or len(sides) % 12
            or not sectors or len(sectors) % 24 or len(lines) // 16 > 12000):
        return None
    points = [(x / 65536, y / 65536) for x, y in struct.iter_unpack('<ii', vert)]
    heights = [struct.unpack_from('<hh', sectors, at) for at in range(0, len(sectors), 24)]
    sector_ids = [struct.unpack_from('<h', sides, at + 10)[0] for at in range(0, len(sides), 12)]
    if any(not 0 <= sector < len(heights) for sector in sector_ids):
        return None
    vertices, triangles = [], []

    def wall(a, b, low, high):
        if low >= high:
            return
        index = len(vertices)
        vertices.extend(((a[0], low, a[1]), (b[0], low, b[1]),
                         (b[0], high, b[1]), (a[0], high, a[1])))
        triangles.extend(((index, index+1, index+2), (index, index+2, index+3)))

    for at in range(0, len(lines), 16):
        v1, v2 = struct.unpack_from('<HH', lines, at)
        front, back = struct.unpack_from('<hh', lines, at + 12)
        if v1 >= len(points) or v2 >= len(points) or not 0 <= front < len(sector_ids):
            return None
        a, b = points[v1], points[v2]
        floor, ceiling = heights[sector_ids[front]]
        if back == -1:
            wall(a, b, floor, ceiling)
        elif 0 <= back < len(sector_ids):
            other_floor, other_ceiling = heights[sector_ids[back]]
            wall(a, b, min(floor, other_floor), max(floor, other_floor))
            wall(a, b, min(ceiling, other_ceiling), max(ceiling, other_ceiling))
        else:
            return None
    return (vertices, triangles) if triangles else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, directory, rows in iwad_sprites.archives(image, check):
        for index, (offset, _, name, _) in enumerate(rows):
            if not _MAP.fullmatch(name):
                continue
            check()
            data = iwad_sprites._texture_member(image, base, directory, rows, index, check)
            if not data or not (model := geometry(data)):
                continue
            vertices, faces = model
            end = rows[index+1][0] if index+1 < len(rows) else directory
            result.append(dict(offset=base+offset, size=end-offset, kind='3d model', media='model', layout=LAYOUT,
                               confidence='validated', directory=base, index=index, label=f'{name} · sector walls',
                               vertices=len(vertices), triangles=len(faces),
                               reason='The nested map directory, line vertices, sidedefs and sector heights resolve.',
                               preview_settings=dict(source='rom', format='auto', offset=base+offset)))
    return result


def preview(image, asset, selection):
    for base, directory, rows in iwad_sprites.archives(image, lambda: None):
        index = asset['index']
        if base != asset['directory'] or not 0 <= index < len(rows) or base + rows[index][0] != asset['offset']:
            continue
        data = iwad_sprites._texture_member(image, base, directory, rows, index, lambda: None)
        model = geometry(data) if data else None
        if not model:
            break
        vertices, faces = model
        edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
        return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                    points=[], surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0)
                                         for face in faces], materials=[],
                    details=dict(format='IWAD sector walls', vertices=len(vertices), triangles=len(faces)),
                    note='Static wall geometry from sector heights. Floors, materials and moving sectors are separate.',
                    settings=asset['preview_settings'])
    raise formats.AssetError('The map resource changed. Scan ROM Explorer again.')

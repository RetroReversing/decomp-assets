"""Static sector walls from grouped members of a big-endian IWAD."""
import re
import struct

from .. import formats
from . import be_iwad_images

LAYOUT = 'be-iwad-map'
_MAP = re.compile(r'MAP[0-9][0-9]$')
_REQUIRED = ('VERTEXES', 'LINEDEFS', 'SIDEDEFS', 'SECTORS')


def geometry(lumps):
    if any(name not in lumps or lumps[name] is None for name in _REQUIRED):
        return None
    vert, lines, sides, sectors = (lumps[name] for name in _REQUIRED)
    if (not vert or len(vert) % 4 or not lines or len(lines) % 16 or not sides or len(sides) % 30
            or not sectors or len(sectors) % 26 or len(lines) // 16 > 12000):
        return None
    points = list(struct.iter_unpack('<hh', vert))
    heights = [struct.unpack_from('<hh', sectors, at) for at in range(0, len(sectors), 26)]
    sector_ids = [struct.unpack_from('<h', sides, at + 28)[0] for at in range(0, len(sides), 30)]
    if any(not 0 <= sector < len(heights) for sector in sector_ids):
        return None
    vertices, faces = [], []

    def wall(a, b, low, high):
        if low >= high:
            return
        i = len(vertices)
        vertices.extend(((a[0], low, a[1]), (b[0], low, b[1]),
                         (b[0], high, b[1]), (a[0], high, a[1])))
        faces.extend(((i, i+1, i+2), (i, i+2, i+3)))

    for at in range(0, len(lines), 16):
        v1, v2 = struct.unpack_from('<HH', lines, at)
        front, back = struct.unpack_from('<hh', lines, at+12)
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
    return (vertices, faces) if faces else None


def read_map(image, base, rows, index, check):
    found = {}
    for row in rows[index+1:index+17]:
        if _MAP.fullmatch(row[2]):
            break
        if row[2] in _REQUIRED:
            if row[2] in found:
                return None
            found[row[2]] = be_iwad_images.unpack(image, base, row, check=check)
    return geometry(found)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, rows in be_iwad_images.archives(image, check):
        for index, (offset, size, name) in enumerate(rows):
            if not _MAP.fullmatch(name):
                continue
            check()
            model = read_map(image, base, rows, index, check)
            if not model:
                continue
            vertices, faces = model
            result.append(dict(offset=base+offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                               confidence='validated', directory=base, index=index, label=f'{name} · sector walls',
                               vertices=len(vertices), triangles=len(faces),
                               reason='The map members, line vertices, sidedefs and sector heights resolve.',
                               preview_settings=dict(source='rom', format='auto', offset=base+offset)))
    return result


def preview(image, asset, selection):
    for base, rows in be_iwad_images.archives(image):
        index = asset['index']
        if base != asset['directory'] or not 0 <= index < len(rows) or base + rows[index][0] != asset['offset']:
            continue
        model = read_map(image, base, rows, index, lambda: None)
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

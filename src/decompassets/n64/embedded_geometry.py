"""Local vertex clouds in bounded inline geometry records."""
import re
import struct

from .. import formats

LAYOUT = 'embedded-geometry-points'
_HEADER = re.compile(rb'[A-Z0-9_]{11}\0G[\x00-\x03]..', re.S)


def record(image, at):
    if at < 12 or at+32 > len(image) or not _HEADER.match(image, at-12):
        return None
    size = int.from_bytes(image[at+1:at+4], 'big')
    end = at+4+size
    if size < 32 or end > len(image):
        return None
    vertices, coords = struct.unpack_from('>2H', image, at+12)
    offsets = struct.unpack_from('>4I', image, at+16)
    if (not 3 <= vertices <= 8192 or not 1 <= coords <= 8192
            or any(offset >= size for offset in offsets) or offsets != tuple(sorted(offsets))
            or offsets[0] < 32 or offsets[2]+vertices*8 > offsets[3] or offsets[3]+coords*4 > size):
        return None
    points_at = at+4+offsets[2]
    return size, vertices, points_at


def faces(image, at, info):
    """Decode consecutive checked vertex-cache loads and packed triangle groups."""
    size, vertices, _ = info
    coords = struct.unpack_from('>H', image, at+14)[0]
    uv_offset = struct.unpack_from('>I', image, at+28)[0]
    pos = at+4+uv_offset+coords*4+4
    end = at+4+size
    result = []
    while pos < end:
        command = image[pos]
        if command >> 5 != 1:
            break
        count = (command & 31)+1
        pos += 1
        if pos+count*2 > end:
            break
        cache = list(image[pos:pos+count*2:2])
        texcoords = image[pos+1:pos+count*2:2]
        if any(index >= vertices for index in cache) or any(index >= coords for index in texcoords):
            break
        pos += count*2
        if image[pos:pos+2] == b'\xc0\x00':
            pos += 2
        if pos >= end or image[pos] >> 5 != 4:
            break
        count = image[pos] & 31
        pos += 1
        if not count or pos+count*2 > end:
            break
        group = []
        for i in range(count):
            word = struct.unpack_from('>H', image, pos+i*2)[0]
            indices = ((word >> 10) & 31, (word >> 5) & 31, word & 31)
            if word & 0x8000 or any(index >= len(cache) for index in indices):
                return result
            group.append(tuple(cache[index] for index in indices))
        result.extend(group)
        pos += count*2
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _HEADER.finditer(image):
        at = match.start()+12
        if at % 4 or not (info := record(image, at)):
            continue
        check()
        size, count, _ = info
        triangles = faces(image, at, info)
        result.append(dict(offset=at, size=size+4, kind='3d model', media='model', layout=LAYOUT,
                           confidence='inferred', vertices=count, triangles=len(triangles),
                           label='Embedded geometry · local mesh' if triangles else 'Embedded geometry · vertex cloud',
                           reason='The record bounds and position and coordinate arrays agree.',
                           preview_settings=dict(source='rom', format='auto', offset=at)))
    return result


def preview(image, asset, selection):
    info = record(image, asset['offset'])
    if not info or info[0]+4 != asset['size'] or info[1] != asset['vertices']:
        raise formats.AssetError('The geometry record changed. Scan ROM Explorer again.')
    _, count, start = info
    vertices = [struct.unpack_from('>3h', image, start+8*i) for i in range(count)]
    triangles = faces(image, asset['offset'], info)
    edges = {tuple(sorted((face[i-1],face[i]))) for face in triangles for i in range(3)}
    note = ('Partial local mesh. Additional faces, materials, placement and animation are separate.' if triangles else
            'Vertex cloud only. Faces, materials, placement and animation have not been reconstructed.')
    return dict(media='model', vertices=vertices, triangles=len(triangles), edges=sorted(edges), points=list(range(count)),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255]*4]*3, material=0) for face in triangles],
                materials=[], details=dict(format='Embedded geometry', vertices=count, triangles=len(triangles)),
                note=note,
                settings=asset['preview_settings'])

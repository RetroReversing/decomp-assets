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


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _HEADER.finditer(image):
        at = match.start()+12
        if at % 4 or not (info := record(image, at)):
            continue
        check()
        size, count, _ = info
        result.append(dict(offset=at, size=size+4, kind='3d model', media='model', layout=LAYOUT,
                           confidence='inferred', vertices=count, triangles=0, label='Embedded geometry · vertex cloud',
                           reason='The record bounds and position and coordinate arrays agree.',
                           preview_settings=dict(source='rom', format='auto', offset=at)))
    return result


def preview(image, asset, selection):
    info = record(image, asset['offset'])
    if not info or info[0]+4 != asset['size'] or info[1] != asset['vertices']:
        raise formats.AssetError('The geometry record changed. Scan ROM Explorer again.')
    _, count, start = info
    vertices = [struct.unpack_from('>3h', image, start+8*i) for i in range(count)]
    return dict(media='model', vertices=vertices, triangles=0, edges=[], points=list(range(count)),
                details=dict(format='Embedded geometry positions', vertices=count, triangles=0),
                note='Vertex cloud only. Faces, materials, placement and animation have not been reconstructed.',
                settings=asset['preview_settings'])

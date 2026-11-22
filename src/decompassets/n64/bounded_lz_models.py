"""Model tables and compact vertex-cache commands inside bounded LZ files."""
import re
import struct

from .. import bounded_lz, formats

LAYOUT = 'bounded-lz-cache-mesh'
_TABLE = re.compile(rb'(?=\x00[\x01-\x7f]..\x00[\x01-\x7f]..\x00{8})', re.S)


def geometry(data):
    if len(data) < 32 or data[:8] != b'\0\0\0\0\0\0\0\x01':
        return None
    vertex_at = int.from_bytes(data[8:12], 'big')
    commands_at = int.from_bytes(data[16:20], 'big')
    if not 32 <= vertex_at < commands_at or commands_at+8 > len(data):
        return None
    vertices = int.from_bytes(data[vertex_at:vertex_at+4], 'big')
    commands = int.from_bytes(data[commands_at:commands_at+4], 'big')
    if (not 3 <= vertices <= 20000 or not 1 <= commands <= 100000
            or vertex_at+8+vertices*16 != commands_at or commands_at+8+commands*8 != len(data)):
        return None
    points = [struct.unpack_from('>3h', data, vertex_at+8+i*16) for i in range(vertices)]
    cache = [None]*128
    faces = []
    for i in range(commands):
        at = commands_at+8+i*8
        word, value = struct.unpack_from('>II', data, at)
        op = word >> 16
        if op == 8:
            first, count = word & 127, (word >> 7) & 127
            if not count or first+count > len(cache) or value+count > vertices:
                return None
            cache[first:first+count] = list(range(value, value+count))
        elif op in (10, 11):
            packed = ((word & 0xffff) << 32) | value
            shifts = (35, 28, 21, 14, 7, 0) if op == 10 else (21, 14, 7, 0)
            slots = [(packed >> shift)&127 for shift in shifts]
            if any(cache[slot] is None for slot in slots):
                return None
            ids = [cache[slot] for slot in slots]
            triangles = (ids[:3], ids[3:]) if op == 10 else (ids[:3], [ids[0], ids[2], ids[3]])
            faces.extend(tuple(f) for f in triangles if len(set(f)) == 3)
        elif op > 20:
            return None
    if not faces:
        return None
    return points, faces


def regions(image, *, check=lambda: None, **kwargs):
    candidates = set()
    for match in _TABLE.finditer(image):
        at = match.start()
        lo, hi = struct.unpack_from('>II', image, at)
        if (lo % 16 or hi % 16 or not at < lo < hi <= len(image) or hi-lo > 1024*1024
                or not 128 <= int.from_bytes(image[lo:lo+4], 'little') <= formats.MAX_BYTES):
            continue
        candidates.add((lo, hi))
        if len(candidates) >= 512:
            break
    result = []
    for lo, hi in sorted(candidates):
        check()
        try:
            data, used = bounded_lz.unpack(memoryview(image)[lo:hi])
        except formats.AssetError:
            continue
        parsed = geometry(data)
        if parsed is None:
            continue
        vertices, faces = parsed
        result.append(dict(offset=lo, size=hi-lo, kind='3d model', media='model', layout=LAYOUT,
                           label='Compressed vertex-cache geometry', confidence='inferred',
                           vertices=len(vertices), triangles=len(faces),
                           reason='The source table bounds vertices and recognized cache-indexed faces. Other commands, placement and materials are separate.',
                           preview_settings=dict(format='auto', source='rom', offset=lo)))
    return result


def preview(image, asset, selection):
    lo, hi = asset['offset'], asset['offset']+asset['size']
    try:
        data, _ = bounded_lz.unpack(memoryview(image)[lo:hi])
    except formats.AssetError as error:
        raise formats.AssetError('The compressed model changed. Rescan ROM Explorer.') from error
    parsed = geometry(data)
    if parsed is None:
        raise formats.AssetError('The geometry changed. Rescan ROM Explorer.')
    vertices, faces = parsed
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({point for face in faces for point in face}),
                surfaces=[dict(indices=f, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for f in faces],
                materials=[], details=dict(format='Vertex-cache geometry', vertices=len(vertices), triangles=len(faces)),
                note=asset['reason'], settings=asset['preview_settings'])

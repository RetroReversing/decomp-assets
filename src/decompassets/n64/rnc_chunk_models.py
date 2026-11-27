"""Local triangle meshes inside bounded RNC chunk records."""
import re
import struct

from .. import formats, rnc

LAYOUT = 'rnc-chunk-model'
_LIMIT = 1024 * 1024


def _word(data, at):
    if at < 0 or at+4 > len(data) or at % 4:
        raise ValueError
    return struct.unpack_from('>I', data, at)[0]


def model(image, offset):
    if offset < 0 or image[offset:offset+4] != b'RNC\x01' or offset+18 > len(image):
        return None
    packed = _word(image, offset+8)
    size = 18+packed
    if not packed or offset+size > len(image):
        return None
    try:
        data = rnc.unpack(image[offset:offset+size], max_output=_LIMIT)
        if len(data) < 64 or (_word(data, 0), _word(data, 4), _word(data, 8)) != (1, 16, len(data)):
            return None
        base = 0x28
        count = _word(data, base)
        if not 1 <= count <= 64 or base+4+count*4 > len(data):
            return None
        offsets = [base+_word(data, base+4+4*i) for i in range(count)]
        if offsets != sorted(set(offsets)) or offsets[0] < base+4+4*count:
            return None
        vertices, faces = [], []
        for index, at in enumerate(offsets):
            if (_word(data, at), _word(data, at+4)) != (3, 24):
                return None
            face_at, vertex_at, end = (at+_word(data, at+x) for x in (8, 12, 16))
            next_at = offsets[index+1] if index+1 < count else len(data)
            if not at+24 <= face_at < vertex_at < end <= next_at:
                return None
            if _word(data, face_at) != 2 or (_word(data, vertex_at+4), _word(data, vertex_at+8)) != (1, 16):
                return None
            face_count, vertex_count = _word(data, face_at+4), _word(data, vertex_at+12)
            if (not 1 <= vertex_count <= 32 or not 1 <= face_count <= 4096
                    or face_at+8+2*face_count > vertex_at or vertex_at+16+16*vertex_count > end):
                return None
            initial = len(vertices)
            for i in range(vertex_count):
                vertices.append(struct.unpack_from('>3h', data, vertex_at+16+16*i))
            for i in range(face_count):
                packed_face, = struct.unpack_from('>H', data, face_at+8+2*i)
                indices = ((packed_face >> 10) & 31, (packed_face >> 5) & 31, packed_face & 31)
                if any(item >= vertex_count for item in indices):
                    return None
                faces.append(tuple(initial+item for item in indices))
        return size, vertices, faces
    except (rnc.RncError, struct.error, ValueError):
        return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for index, match in enumerate(re.finditer(b'RNC\x01', image)):
        if index % 32 == 0:
            check()
        offset = match.start()
        if offset % 4 or not (result := model(image, offset)):
            continue
        size, vertices, faces = result
        found.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                          label='RNC local triangle mesh', confidence='validated',
                          vertices=len(vertices), triangles=len(faces),
                          reason='RNC checksums, chunk extents and every triangle index agree.',
                          preview_settings=dict(source='rom', format='auto', offset=offset)))
    return found


def preview(image, asset, selection):
    found = model(image, asset['offset'])
    if not found or found[0] != asset['size']:
        raise formats.AssetError('The compressed model changed. Scan ROM Explorer again.')
    _, vertices, faces = found
    edges = sorted({tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)})
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=edges,
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='RNC chunk mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry only; materials, placement and animation are separate.',
                settings=asset['preview_settings'])

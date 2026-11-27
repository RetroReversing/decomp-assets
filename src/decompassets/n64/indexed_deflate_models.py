"""Meshes in an indexed archive of size-prefixed raw-deflate resources."""
import re
import struct
import zlib

from ..formats import AssetError

LAYOUT = 'indexed-deflate-model'


def archives(image):
    # The directory has 71 bounded sections, followed by a reserved gap.
    for hit in re.finditer(b'\0\0\0G\0\0\0\0', image):
        at = hit.start()
        if at % 4 or at + 0x130 > len(image):
            continue
        sections = struct.unpack_from('>72I', image, at + 4)
        base = at + 0x130
        if sections[0] or base + sections[-1] > len(image) or any(a > b for a, b in zip(sections, sections[1:])):
            continue
        yield base, sections


def members(image, archive, table, data):
    base, sections = archive
    a, b = base + sections[table], base + sections[table + 1]
    data_at, data_end = base + sections[data], base + sections[data + 1]
    offsets = []
    for at in range(a, b - 3, 4):
        value = struct.unpack_from('>I', image, at)[0]
        if value == 0xffffffff:
            break
        offsets.append(value)
    if len(offsets) < 3 or offsets[0] or offsets[-1] > data_end - data_at or any(a > b for a, b in zip(offsets, offsets[1:])):
        return []
    return [(data_at+a, data_at+b) for a,b in zip(offsets, offsets[1:])]


def unpack(image, start, end):
    if end - start < 6 or image[start+4] != 9:
        return None
    size = int.from_bytes(image[start:start+4], 'little')
    if not 0 < size <= 4*1024*1024:
        return None
    decoder = zlib.decompressobj(-15)
    try:
        data = decoder.decompress(image[start+5:end], size+1)
    except zlib.error:
        return None
    return data if decoder.eof and len(data) == size else None


def geometry(data):
    if len(data) < 0x88:
        return None
    nv, nt, nb = struct.unpack_from('>3H', data, 0x12)
    va, ta, ba = struct.unpack_from('>3I', data, 0x1c)
    if not (3 <= nv <= 8192 and 1 <= nt <= 16384 and 1 <= nb <= 4096
            and va + 10*nv <= len(data) and ta + 16*nt <= len(data) and ba + 16*(nb+1) <= len(data)):
        return None
    vertices = [struct.unpack_from('>3h', data, va+10*i) for i in range(nv)]
    faces = []
    for i in range(nb):
        first_v, first_t = struct.unpack_from('>2H', data, ba+16*i+6)
        last_v, last_t = struct.unpack_from('>2H', data, ba+16*(i+1)+6)
        if first_v > last_v or last_v > nv or first_t > last_t or last_t > nt:
            return None
        for n in range(first_t, last_t):
            face = tuple(first_v+x for x in data[ta+16*n+1:ta+16*n+4])
            if len(face) != 3 or max(face) >= last_v:
                return None
            faces.append(face)
    return (vertices, faces) if faces else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for archive in archives(image):
        rows = members(image, archive, 38, 39)
        for i, (start, end) in enumerate(rows):
            if i % 64 == 0:
                check(); progress(dict(phase='Checking indexed model resources', done=i, total=len(rows)))
            data = unpack(image, start, end)
            mesh = geometry(data) if data else None
            if mesh:
                vertices, faces = mesh
                result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                    confidence='validated', label=f'Indexed model {i}', vertices=len(vertices), triangles=len(faces),
                    reason='The indexed compressed resource contains bounded vertices, batches and resolving triangles.',
                    preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    start = asset['offset']
    data = unpack(image, start, start+asset['size'])
    parsed = geometry(data) if data else None
    if not parsed:
        raise AssetError('The model resource changed. Scan ROM Explorer again.')
    vertices, faces = parsed
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}), materials=[],
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                details=dict(format='Indexed model', vertices=len(vertices), triangles=len(faces)),
                note='Local mesh geometry; materials and animation are separate.', settings=asset['preview_settings'])

TEXTURE = 'indexed-deflate-texture'
_TEXTURE_FORMATS = [('rgba8888', 32), ('rgba5551-be', 16), ('i8', 8), ('i4', 4),
                    ('ia16', 16), ('ia8', 8), ('ia4', 4)]


def texture_data(image, start, end):
    stored = image[start:end]
    if len(stored) < 0x20:
        return None
    data = unpack(image, start+0x20, end) if stored[0x19] else stored
    if data is None or len(data) < 0x20:
        return None
    width, height, kind = data[0], data[1], data[2] & 15
    if not width or not height or kind >= len(_TEXTURE_FORMATS):
        return None
    fmt, bits = _TEXTURE_FORMATS[kind]
    row = (width*bits+7)//8
    if 0x20 + row*height > len(data):
        return None
    pixels = bytearray(data[0x20:0x20+row*height])
    half = 8 if bits == 32 else 4
    for y in range(1, height, 2):
        for x in range(0, row-2*half+1, 2*half):
            at = y*row+x
            pixels[at:at+2*half] = pixels[at+half:at+2*half]+pixels[at:at+half]
    return bytes(pixels), width, height, fmt


def texture_regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for archive in archives(image):
        for table, data in ((1, 0), (3, 2)):
            rows = members(image, archive, table, data)
            for i, (start, end) in enumerate(rows):
                if i % 128 == 0:
                    check(); progress(dict(phase='Checking indexed texture resources', done=i, total=len(rows)))
                texture = texture_data(image, start, end)
                if texture:
                    _, width, height, fmt = texture
                    result.append(dict(offset=start, size=end-start, kind='image', media='image', layout=TEXTURE,
                        label=f'Indexed texture {table}:{i} · {width}×{height}', confidence='validated',
                        width=width, height=height, format=fmt, frames=1, palettes=0,
                        levels=[dict(width=width, height=height, offset=0)],
                        reason='The indexed texture header and complete pixel data fit the resource.',
                        preview_settings=dict(source='rom', format='auto', offset=start, width=width, height=height)))
    return result


def preview_texture(image, asset, selection):
    from .. import formats
    start = asset['offset']
    texture = texture_data(image, start, start+asset['size'])
    if not texture:
        raise AssetError('The texture resource changed. Scan ROM Explorer again.')
    pixels, width, height, fmt = texture
    result = formats.preview(pixels, dict(format=fmt, offset=0, width=width, height=height))
    result['details']['note'] = 'Decoded indexed texture; runtime use is not established.'
    result['settings'] = asset['preview_settings']
    return result

"""Local meshes in relative indexed file tables with optionally compressed members.

The table ends where its last relative offset points; inline TEX files corroborate
its base. Mesh and LZSS layouts: https://vpw.ajworld.net/vpwstudio/Manual/appendix_c.html#AkiModel
"""
import re
import struct

from .. import formats
from . import aki_lzss, aki_textures

LAYOUT = 'aki-directory-model'
_START = re.compile(b'(?=\0\0\0[\0\1](?:\0\0(?:[\x01-\xff][\x00-\xff]|\0[\x10-\xff])|\0\1\0\0))')
_MAX_MESH = 8 + 127*8 + 127*3


def _decode(source):
    result = aki_lzss.unpack(source, _MAX_MESH)
    return result[0] if result else None


def _mesh(data):
    if not data or len(data) < 8:return None
    nv, nf = data[1] & 127, data[2] & 127
    if nv < 3 or nf < 1 or len(data) != 8+nv*8+nf*3:return None
    vertices = [struct.unpack_from('bbb', data, 8+i*8) for i in range(nv)]
    if len(set(vertices)) < 3:return None
    start = 8+nv*8
    faces = [tuple(data[start+i*3:start+i*3+3]) for i in range(nf)]
    if any(max(face) >= nv or len(set(face)) != 3 for face in faces):return None
    return vertices, faces


def _directories(image, check):
    size = len(image)
    for match in _START.finditer(image):
        at = match.start()
        if at % 2 or at+20 > size:continue
        check()
        first = struct.unpack_from('>5I', image, at)
        if (not 16 <= first[1] <= 65536 or
                any((a & ~1) >= (b & ~1) for a, b in zip(first, first[1:]))):
            continue
        entries, prev, pos = [], -1, at
        while pos+4 <= size and len(entries) < 65536:
            word = struct.unpack_from('>I', image, pos)[0]
            value = word & ~1
            if value > at or (prev >= 0 and (value <= prev or value-prev > 524288)):break
            entries.append(word)
            prev = value
            pos += 4
        if len(entries) < 256:continue
        base = at-prev
        # The table's sentinel locates the table itself. Multiple full TEX
        # records at independently indexed file starts identify its base.
        anchors = 0
        for word, nxt in zip(entries, entries[1:]):
            start, end = base+(word & ~1), base+(nxt & ~1)
            if word & 1 and image[start+4:start+9] == b'\xffTEX\0':
                decoded = aki_lzss.unpack(image[start:end], formats.MAX_BYTES, check)
                record = decoded and aki_textures._read(decoded[0], 0)
                if record and record[-1] == len(decoded[0]):anchors += 1
            elif image[start:start+4] == b'TEX\0':
                record = aki_textures._read(image, start)
                if record and start+record[-1] <= end:anchors += 1
            if anchors >= 3:break
        if anchors >= 3:
            yield base, entries


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for base, entries in _directories(image, check):
        for index, (word, nxt) in enumerate(zip(entries, entries[1:])):
            if not index % 128:check()
            at, end = base+(word & ~1), base+(nxt & ~1)
            source = image[at:end]
            if word & 1:
                data = _decode(source)
            else:
                data = source if len(source) <= _MAX_MESH else None
            mesh = _mesh(data)
            if mesh is None:continue
            vertices, faces = mesh
            result.append(dict(offset=at, size=end-at, kind='3d model', media='model', layout=LAYOUT,
                               label='Indexed local mesh', confidence='validated', encoded=bool(word & 1),
                               vertices=len(vertices), triangles=len(faces),
                               meshes=[dict(name='Mesh 1', vertices=len(vertices), triangles=len(faces))],
                               reason='An indexed file has a complete mesh header and in-range triangle indices. '
                                      'Scene placement, materials and animation are not established.',
                               preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
    at, end = asset['offset'], asset['offset']+asset['size']
    if at < 0 or end > len(image):raise formats.AssetError('The mesh is outside the image. Rescan ROM Explorer.')
    source = image[at:end]
    mesh = _mesh(_decode(source) if asset.get('encoded') else source)
    if mesh is None:raise formats.AssetError('The indexed mesh changed. Rescan ROM Explorer.')
    vertices, faces = mesh
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(len(vertices))),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255, 255, 255, 255]]*3, material=0)
                          for face in faces], materials=[],
                details=dict(format='Indexed local mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local geometry; scale, scene placement, textures and animation are separate.',
                settings=dict(format='auto', source='rom', offset=at, mesh=0))

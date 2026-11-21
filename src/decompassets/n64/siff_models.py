"""Size-prefixed LZ archives with Siff pdt2 meshes and their CI8 textures."""

import re
import struct
from itertools import pairwise

from .. import formats
from . import sized_lz_catalog

MODEL = 'siff-pdt2-models'
TEXTURE = 'siff-pdt2-textures'
_TABLE = re.compile(rb'\0{16}(?=\0[\x01-\x7f]..)')


def _archives(image, check):
    limit = min(len(image), 0x200000)
    for match in _TABLE.finditer(image, 0, limit):
        start = match.end()
        if start % 4:
            continue
        check()
        offsets = set()
        for at in range(start, min(limit - 3, start + 128 * 4), 4):
            offset = struct.unpack_from('>I', image, at)[0]
            if not at < offset < len(image) or offset % 16 or offset in offsets:
                break
            offsets.add(offset)
        if len(offsets) >= 3:
            yield tuple(pairwise((*sorted(offsets), len(image))))


def _node(data, start, end):
    if end - start < 28:
        return
    groups, vertex_count, face_count = struct.unpack_from('>3H', data, start + 22)
    cursor = start + 28
    vertices, faces = [], []
    for _ in range(groups):
        if cursor + 4 > end:
            return
        count, triangles = struct.unpack_from('>2H', data, cursor)
        cursor += 4
        triangle_start = cursor + count * 16
        group_end = triangle_start + triangles * 4
        if count > 16 or group_end > end:
            return
        base = len(vertices)
        vertices.extend(struct.unpack_from('>3h', data, pos) for pos in range(cursor, triangle_start, 16))
        for pos in range(triangle_start, group_end, 4):
            indices = data[pos:pos + 3]
            if max(indices) >= count:
                return
            faces.append(tuple(base + index for index in indices))
        cursor = group_end
    if cursor == end and len(vertices) == vertex_count and len(faces) == face_count:
        return vertices, faces


def _texture(data, start, end):
    if end - start < 532:
        return
    width, height = struct.unpack_from('>2H', data, start)
    if not (0 < width <= 512 and 0 < height <= 512 and end - start == 532 + width * height):
        return
    return dict(label=f'CI8 {width}×{height}', frames=1, palettes=1,
                levels=[dict(width=width, height=height, offset=0)],
                preview_settings=dict(format='ci8', width=width, height=height, offset=start + 532,
                                      palette_offset=start + 20, palette_format='rgba5551-be'))


def _member(data, start, end):
    if end - start < 24 or data[start:start + 4] != b'Siff':
        return
    if struct.unpack_from('>I', data, start + 4)[0] != end - start - 8:
        return
    if data[start + 8:start + 24] != b'type\0\0\0\x08pdt2\0\0\0\0':
        return
    cursor = start + 24
    vertices, faces, textures = [], [], []
    while cursor + 8 <= end:
        tag, size = struct.unpack_from('>4sI', data, cursor)
        payload = cursor + 8
        cursor = payload + size
        if cursor > end:
            return
        if tag == b'node':
            if (parsed := _node(data, payload, cursor)) is None:
                return
            points, triangles = parsed
            base = len(vertices)
            faces.extend(tuple(base + index for index in face) for face in triangles)
            vertices.extend(points)
        elif tag == b'text':
            if not (texture := _texture(data, payload, cursor)):
                return
            textures.append(texture)
    if cursor == end and faces:
        return vertices, faces, textures


def _collect(data, check=lambda: None):
    meshes, textures = [], []
    for index, (start, end) in enumerate(sized_lz_catalog.member_spans(data)):
        check()
        if not (parsed := _member(data, start, end)):
            return [], []
        vertices, faces, items = parsed
        meshes.append(dict(label=f'Model {index + 1} · {len(vertices)} vertices', vertices=len(vertices),
                           triangles=len(faces), start=start, end=end))
        textures.extend(items)
    return meshes, textures


def regions(image, *, check=lambda: None, progress=lambda _: None):
    known = {}
    for spans in _archives(image, check):
        rows = {}
        for offset, end in spans:
            decoded = sized_lz_catalog.unpack(image, offset, end, check)
            if not decoded:
                continue
            size, data = decoded
            meshes, textures = _collect(data, check)
            if not meshes:
                continue
            common = dict(offset=offset, size=size, confidence='validated',
                          preview_settings=dict(source='rom', format='auto', offset=offset))
            rows[offset] = [dict(common, kind='3d model', media='model', layout=MODEL,
                                 label=f'{len(meshes)} Siff meshes', meshes=meshes, nodes=len(meshes),
                                 reason='Every triangle references vertices in its native Siff vertex group.')]
            if textures:
                rows[offset].append(dict(common, kind='image', layout=TEXTURE,
                                         label=f'{len(textures)} Siff textures', textures=textures,
                                         texture_count=len(textures), frames=1, palettes=1,
                                         levels=textures[0]['levels'],
                                         reason='Siff texture chunks contain matching CI8 dimensions, palettes and pixels.'))
        if len(rows) >= 3:
            known.update(rows)
    return [row for rows in known.values() for row in rows]


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    decoded = sized_lz_catalog.unpack(image, offset, offset + size)
    if not decoded or decoded[0] != size:
        raise formats.AssetError('The compressed Siff archive changed. Rescan ROM Explorer.')
    data = decoded[1]
    settings = asset['preview_settings']
    if asset['layout'] == TEXTURE:
        index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures']) - 1)
        item = asset['textures'][index]
        result = formats.preview(data, item['preview_settings'])
        result['details'].update(texture=index, note=asset['reason'])
        result['settings'] = dict(settings, texture=index, frame=0, palette=0, mip=0)
        return result
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    mesh = asset['meshes'][index]
    if not (parsed := _member(data, mesh['start'], mesh['end'])):
        raise formats.AssetError('The Siff mesh changed. Rescan ROM Explorer.')
    vertices, faces, _ = parsed
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, edges=sorted(edges), points=list(range(len(vertices))),
                triangles=len(faces), materials=[],
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                details=dict(format='Siff pdt2', vertices=len(vertices), triangles=len(faces)),
                note='Local mesh geometry. Preview embedded textures separately.',
                settings=dict(settings, mesh=index))

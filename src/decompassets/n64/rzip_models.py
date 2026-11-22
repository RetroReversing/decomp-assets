"""Local display-list geometry stored in indexed deflate resource banks."""

import struct

from ..formats import AssetError
from . import rzip_catalog

MODEL = 'rzip-catalog-models'
_VERTEX = struct.Struct('>3h10x')
_STATE = frozenset((0xd7, 0xd9, 0xda, 0xdb, 0xdc, 0xde, 0xe2, 0xe3)) | frozenset(range(0xe6, 0x100))


def segments(data):
    """Yield direct resources and checked contiguous subresources."""
    yield 0, data
    if len(data) < 32:
        return
    size = struct.unpack_from('>I', data)[0]
    if size < 32 or size > len(data) or size % 8 or size > 8192:
        return
    parts = []
    end = size
    for at in range(0, size, 8):
        offset, flags = struct.unpack_from('>II', data, at)
        length = flags & 0x0fffffff
        if (flags & 0x70000000 or bool(flags & 0x80000000) != (at == size - 8)
                or offset != end or offset % 8 or length % 8 or offset + length > len(data)):
            return
        parts.append((offset, length))
        end = offset + length
    if end == len(data):
        for offset, length in parts:
            yield offset, data[offset:offset + length]


def geometry(data):
    if len(data) < 48:
        return None
    header = struct.unpack_from('>10I', data)
    start, size = header[:2]
    if (start < 0x28 or (start - 0x28) % 16 or not size or size % 8
            or start + size > len(data) or data[start + size - 8:start + size] != b'\xdf' + bytes(7)
            or header[6] or header[7]):
        return None
    vertices = list(_VERTEX.iter_unpack(data[0x28:start]))
    if not vertices or len(vertices) > 65536 or size > 0x20000:
        return None
    cache, faces = [None] * 32, []
    for at in range(start, start + size, 8):
        word, arg = struct.unpack_from('>II', data, at)
        opcode = word >> 24
        if opcode == 1:
            count, end = (word >> 12) & 0xff, (word >> 1) & 0x7f
            ptr = arg & 0xffffff
            if arg >> 24 == 0:
                ptr -= 0x28
            elif arg >> 24 != 1:
                return None
            if ptr < 0 or ptr % 16 or not count or not count <= end <= 32 or ptr // 16 + count > len(vertices):
                return None
            cache[end - count:end] = range(ptr // 16, ptr // 16 + count)
        elif opcode in (5, 6) or 0x10 <= opcode <= 0x1f:
            if opcode in (5, 6):
                encoded = word.to_bytes(4, 'big')[1:]
                if opcode == 6:
                    encoded += arg.to_bytes(4, 'big')[1:]
                if any(value % 2 for value in encoded):
                    return None
                indices = tuple(value // 2 for value in encoded)
            else:
                indices = ((arg >> 25) & 31, (arg >> 20) & 31, (arg >> 15) & 31,
                           (arg >> 10) & 31, (arg >> 5) & 31, arg & 31,
                           (word >> 10) & 31, (word >> 5) & 31, word & 31,
                           (word >> 23) & 31, (word >> 18) & 31,
                           ((arg >> 30) & 3) | (((word >> 15) & 7) << 2))
            if any(index >= 32 or cache[index] is None for index in indices):
                return None
            faces.extend(tuple(cache[i] for i in indices[n:n + 3]) for n in range(0, len(indices), 3))
        elif opcode == 0xdf:
            if at != start + size - 8 or word != 0xdf000000 or arg:
                return None
        elif opcode not in _STATE:
            return None
    return (vertices, faces) if faces else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for _, indexed, _ in rzip_catalog.catalogs(image, check=check):
        models = []
        for start, end, flags in indexed:
            check()
            if flags & 1:
                chunk = rzip_catalog._chunk(image, start, end)
                if not chunk or chunk[0] != end:
                    continue
                raw = chunk[1]
            else:
                raw = image[start:end]
            for part, data in segments(raw):
                parsed = geometry(data)
                if not parsed:
                    continue
                vertices, faces = parsed
                models.append(dict(offset=start, size=end-start, compressed=bool(flags & 1), part=part,
                                   length=len(data), vertices=len(vertices), triangles=len(faces),
                                   name=f'Mesh {len(models) + 1}', label=f'Mesh · {len(vertices)} vertices'))
        if models:
            start = min(model['offset'] for model in models)
            end = max(model['offset'] + model['size'] for model in models)
            result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=MODEL,
                               confidence='validated', label=f'{len(models)} indexed meshes', meshes=models,
                               nodes=len(models), vertices=sum(model['vertices'] for model in models),
                               triangles=sum(model['triangles'] for model in models),
                               reason='Resource headers and every loaded triangle resolve inside each local model.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    from .. import formats

    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    model = asset['meshes'][index]
    start, end = model['offset'], model['offset'] + model['size']
    chunk = rzip_catalog._chunk(image, start, end) if model['compressed'] else (end, image[start:end])
    if not chunk or chunk[0] != end:
        raise AssetError('The compressed model changed. Rescan ROM Explorer.')
    raw = chunk[1][model['part']:model['part'] + model['length']]
    if not (parsed := geometry(raw)):
        raise AssetError('The model geometry changed. Rescan ROM Explorer.')
    vertices, faces = parsed
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                materials=[], details=dict(format=model['label'], vertices=len(vertices), triangles=len(faces)),
                note='Local geometry; animation transforms and materials are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

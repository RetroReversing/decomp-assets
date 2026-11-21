"""Local mesh batches in the model table of prefixed-deflate resources."""

import struct

from .. import formats
from . import display_meshes, prefixed_texture_catalog, rzip_catalog

LAYOUT = 'prefixed-deflate-models'


def models(data):
    if len(data) < 24:
        return []
    _, _, count, table, _, vertices = struct.unpack_from('>6I', data)
    if not 1 <= count <= 512 or table < 24 or table + count * 16 != vertices or vertices > len(data):
        return []
    found = []
    for number in range(count):
        _, length, _, batches = struct.unpack_from('>4I', data, table + number * 16)
        count_batches = length >> 16
        if not 1 <= count_batches <= 256 or not 0 < batches <= table - count_batches * 8:
            continue
        pieces = []
        patched = bytearray(data)
        commands = 0
        for index in range(count_batches):
            size, start = struct.unpack_from('>II', data, batches + index * 8)
            if size & 0xff or not 1 <= size >> 8 <= 4096:
                break
            commands += size >> 8
            if commands > 8192:
                break
            end = start + (size >> 8) * 8
            if start % 8 or not 24 <= start < end <= batches:
                break
            for at in range(start, end, 8):
                word, address = struct.unpack_from('>II', data, at)
                if word >> 24 == 1:
                    count_vertices = (word >> 12) & 0xff
                    if (address >> 24 or address < vertices or (address - vertices) % 16
                            or address + count_vertices * 16 > len(data)):
                        break
                    struct.pack_into('>I', patched, at + 4, address | 0x01000000)
            else:
                # Batch sizes are explicit; the runtime chains lists without an
                # end command. Terminate this local copy for the shared reader.
                tail = bytes(patched[end:end + 8])
                patched[end:end + 8] = b'\xdf' + bytes(7)
                piece = display_meshes.geometry(patched, start, end + 8, {1: 0}, vertex_flag_mask=0xffff)
                patched[end:end + 8] = tail
                if piece:
                    pieces.append((piece[1], piece[2]))
                    continue
            break
        else:
            if pieces:
                found.append((number, pieces))
    return found


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for rows in prefixed_texture_catalog.catalogs(image, check):
        for start, end in rows:
            check()
            chunk = rzip_catalog._chunk(image, start, end)
            parsed = models(chunk[1]) if chunk else []
            meshes = []
            for number, pieces in parsed:
                vertices = sum(len(v) for v, _ in pieces)
                triangles = sum(len(f) for _, f in pieces)
                meshes.append(dict(number=number, vertices=vertices, triangles=triangles,
                                   label=f'Model · {vertices} vertices'))
            if meshes:
                result.append(dict(offset=start, size=end-start, kind='3d model', media='model', layout=LAYOUT,
                                   confidence='validated', label=f'{len(meshes)} compressed models', meshes=meshes,
                                   nodes=len(meshes), preview_settings=dict(source='rom', format='auto', offset=start),
                                   reason='Model records locate bounded display-list batches and their local vertices.'))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(asset['meshes']) - 1)
    start, end = asset['offset'], asset['offset'] + asset['size']
    if not 0 <= start < end <= len(image) or not (chunk := rzip_catalog._chunk(image, start, end)):
        raise formats.AssetError('The compressed model pack changed. Rescan ROM Explorer.')
    parsed = dict(models(chunk[1]))
    model = asset['meshes'][index]
    if model['number'] not in parsed:
        raise formats.AssetError('The model geometry changed. Rescan ROM Explorer.')
    vertices, faces = [], []
    for points, triangles in parsed[model['number']]:
        base = len(vertices)
        vertices.extend(points)
        faces.extend(tuple(base + i for i in face) for face in triangles)
    if len(vertices) != model['vertices'] or len(faces) != model['triangles']:
        raise formats.AssetError('The model geometry changed. Rescan ROM Explorer.')
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                materials=[], details=dict(format=model['label'], vertices=len(vertices), triangles=len(faces)),
                note='Local model geometry; scene transforms and materials are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

"""Segmented level meshes in bounded size-prefixed raw-deflate resources."""

import re
import struct
import zlib

from .. import formats

LAYOUT = 'deflate-level-model'
_MAX_EXPANDED = 128 * 1024 * 1024


def unpack(image, start, end):
    if start < 0 or end > len(image) or end - start < 6 or image[start + 4] != 9:
        return None
    size = int.from_bytes(image[start:start + 4], 'little')
    if not 0x100 <= size <= 4 * 1024 * 1024:
        return None
    decoder = zlib.decompressobj(-15)
    try:
        data = decoder.decompress(memoryview(image)[start + 5:end], size + 1)
    except zlib.error:
        return None
    if not decoder.eof or len(data) != size:
        return None
    return data, end - start - len(decoder.unused_data)


def geometry(data):
    if len(data) < 0x30:
        return None
    textures, segments = struct.unpack_from('>II', data)
    ntextures, count = struct.unpack_from('>HH', data, 0x18)
    if not (textures == 0x30 and 1 <= ntextures <= 1024 and 1 <= count <= 512
            and segments == textures + ntextures * 8 and segments + count * 0x40 <= len(data)):
        return None
    meshes = []
    for number in range(count):
        at = segments + number * 0x40
        vertices, triangles, _, batches = struct.unpack_from('>4I', data, at)
        nv, nt, nb = struct.unpack_from('>3H', data, at + 0x20)
        if not (3 <= nv <= 8192 and 1 <= nt <= 16384 and 1 <= nb <= 4096
                and vertices + nv * 10 <= len(data) and triangles + nt * 16 <= len(data)
                and batches + (nb + 1) * 16 <= len(data)):
            return None
        points = [struct.unpack_from('>3h', data, vertices + i * 10) for i in range(nv)]
        ranges = [struct.unpack_from('>2H', data, batches + i * 16 + 6) for i in range(nb + 1)]
        if ranges[0] != (0, 0) or ranges[-1] != (nv, nt):
            return None
        faces = []
        for (first_v, first_t), (last_v, last_t) in zip(ranges, ranges[1:]):
            if not (first_v <= last_v <= nv and first_t <= last_t <= nt):
                return None
            for i in range(first_t, last_t):
                face = tuple(first_v + x for x in data[triangles + i * 16 + 1:triangles + i * 16 + 4])
                if len(face) != 3 or max(face) >= last_v:
                    return None
                faces.append(face)
        if not faces:
            return None
        meshes.append((points, faces))
    return meshes


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result, expanded = [], 0
    # The five-byte wrapper has no magic. Bound candidate attempts and require
    # the complete decoded size and every segment, batch and triangle to agree.
    for number, match in enumerate(re.finditer(rb'(?=...\x00\x09)', image, re.DOTALL)):
        start = match.start()
        if start % 16:
            continue
        if number % 256 == 0:
            check()
        end = min(len(image), start + 4 * 1024 * 1024 + 5)
        decoded = unpack(image, start, end)
        if not decoded:
            continue
        data, used = decoded
        expanded += len(data)
        if expanded > _MAX_EXPANDED:
            break
        meshes = geometry(data)
        if not meshes:
            continue
        entries = [dict(label=f'Segment {i + 1}', vertices=len(v), triangles=len(f))
                   for i, (v, f) in enumerate(meshes)]
        result.append(dict(offset=start, size=used, kind='3d model', media='model', layout=LAYOUT,
                           label=f'{len(entries)} level segments', confidence='validated', nodes=len(entries),
                           vertices=sum(len(v) for v, _ in meshes), triangles=sum(len(f) for _, f in meshes),
                           meshes=entries, reason='The complete decoded level bounds every segment, batch and triangle.',
                           preview_settings=dict(source='rom', format='auto', offset=start)))
    return result


def preview(image, asset, selection):
    decoded = unpack(image, asset['offset'], asset['offset'] + asset['size'])
    meshes = geometry(decoded[0]) if decoded else None
    if not meshes:
        raise formats.AssetError('The level model changed. Scan ROM Explorer again.')
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(meshes) - 1)
    vertices, faces = meshes[index]
    edges = sorted({tuple(sorted((face[i], face[(i + 1) % 3]))) for face in faces for i in range(3)})
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=edges,
                points=sorted({i for face in faces for i in face}), materials=[],
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0)
                          for face in faces],
                details=dict(format='Compressed level segment', vertices=len(vertices), triangles=len(faces)),
                note='Local segment geometry; textures, placement and animation are separate.',
                settings=dict(asset['preview_settings'], mesh=index))

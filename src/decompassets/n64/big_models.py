"""Geometry in tagged resources in a checked paged archive."""

import re
import struct

from .. import formats
from . import big_audio, big_pages, big_sam_audio, big_tagged_models, big_tagged_textures, big_textures

LAYOUT = 'big-resource-model'


def _mesh(data, start, size, index, *, geometry=False):
    if start + size > len(data) or size < 36:
        return None
    count, = struct.unpack_from('>I', data, start)
    if not 1 <= count <= 4096 or 4 + count * 32 > size or not 0 <= index < count:
        return None
    pointer, = struct.unpack_from('>I', data, start + 4 + index * 32)
    if not 0 < pointer <= size - 16:
        return None
    vertices, vertex_at, commands, command_at = struct.unpack_from('>4I', data, start + pointer)
    if (not 3 <= vertices <= 8192 or not 1 <= commands <= 65536
            or vertex_at + vertices * 16 > size or command_at + commands * 4 > size):
        return None
    faces = []
    first, active = 0, 0
    for at in range(start + command_at, start + command_at + commands * 4, 4):
        op, a, b, c = struct.unpack_from('>4B', data, at)
        if op == 0x10:
            first, active = (b << 8) | c, a
            if not active or first + active > vertices:
                return None
        elif op == 0x30:
            if max(a, b, c) >= active:
                return None
            faces.append((first + a, first + b, first + c))
        elif op & 0xf0 != 0x20:
            return None
    if not faces:
        return None
    if not geometry:
        return vertices, len(faces)
    points = [struct.unpack_from('>3h', data, start + vertex_at + i * 16) for i in range(vertices)]
    return points, faces


def regions(image, *, images=None, audio=None, check=lambda: None, progress=lambda _: None):
    result, tagged, tagged_models = [], [], []
    for archive in big_pages.archives(image):
        if not (data := big_pages.unpack(image, archive, check)):
            continue
        tagged_models.extend(big_tagged_models.from_archive(archive, data, check))
        if images is not None:
            images.extend(big_textures.from_archive(image, archive, data, check))
            tagged.extend(big_tagged_textures.from_archive(image, archive, data, check))
        if audio is not None:
            audio.extend(big_audio.from_archive(image, archive, data, check))
            audio.extend(big_sam_audio.from_archive(image, archive, data, check))
        for match in re.finditer(b'ARN\0', data):
            at = match.start()
            if at + 12 > len(data):
                continue
            size, count = struct.unpack_from('<I', data, at + 4)[0], struct.unpack_from('>I', data, at + 8)[0]
            start = at + 8
            if size > len(data) - start or not 1 <= count <= 4096 or 4 + count * 32 > size:
                continue
            meshes = []
            for index in range(count):
                if mesh := _mesh(data, start, size, index):
                    meshes.append((index, *mesh))
            if not meshes or len(meshes) * 2 < count:
                continue
            meshes.sort(key=lambda row: row[2], reverse=True)
            lo, hi = big_pages.physical(archive, at, size + 8)
            result.append(dict(offset=lo, size=hi-lo, kind='3d model', media='model', layout=LAYOUT,
                               confidence='validated', label=f'Paged model resource ({len(meshes)} meshes)',
                               meshes=[dict(name=f'Mesh {index}', vertices=vertices, triangles=faces)
                                       for index, vertices, faces in meshes],
                               nodes=len(meshes), triangles=sum(row[2] for row in meshes),
                               archive=archive[0], resource=at, resource_size=size, mesh_indices=[row[0] for row in meshes],
                               members=[dict(resource=at, resource_size=size, mesh_indices=[row[0] for row in meshes])],
                               reason='A paged archive contains bounded vertex arrays and resolving triangle commands.',
                               preview_settings=dict(source='rom', format='auto', offset=lo, mesh=0)))
    groups = {}
    for asset in result:
        key = asset['archive'], asset['offset']
        if key not in groups:
            groups[key] = asset
        else:
            group = groups[key]
            group['members'].extend(asset['members'])
            group['meshes'].extend(asset['meshes'])
            group['mesh_indices'].extend(asset['mesh_indices'])
            group['nodes'] += asset['nodes']
            group['triangles'] += asset['triangles']
            group['size'] = max(group['size'], asset['size'])
            group['label'] = f"Paged model resources ({group['nodes']} meshes)"
    if images is not None:
        images[:] = big_textures.merge(images) + tagged
    return list(groups.values()) + tagged_models


def preview(image, asset, selection):
    archive = next((item for item in big_pages.archives(image) if item[0] == asset['archive']), None)
    mesh = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    selected = mesh
    member = None
    for item in asset['members']:
        if selected < len(item['mesh_indices']):
            member = item
            break
        selected -= len(item['mesh_indices'])
    if not archive or not member or not (data := big_pages.extract(
            image, archive, member['resource'], member['resource_size'] + 8)):
        raise formats.AssetError('The model archive changed. Rescan ROM Explorer.')
    decoded = _mesh(data, 8, member['resource_size'], member['mesh_indices'][selected], geometry=True)
    if not decoded:
        raise formats.AssetError('The model resource changed. Rescan ROM Explorer.')
    vertices, faces = decoded
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    settings = dict(asset['preview_settings'], mesh=mesh)
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({index for face in faces for index in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Paged resource mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local mesh geometry; scene placement, materials, and animation are separate.', settings=settings)

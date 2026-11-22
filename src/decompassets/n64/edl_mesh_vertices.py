"""Bounded positions and compact triangle commands in compressed model packs."""

import struct

from .. import formats
from . import edl, edl_indexed_textures

LAYOUT = 'eurocom-edl-mesh-vertices'


def _faces(data, entry, vertex_count):
    """Decode the validated subset of the game's compact graphics command stream."""
    expected = struct.unpack_from('>H', data, entry)[0]
    packed = struct.unpack_from('>I', data, entry + 28)[0]
    pos = entry + 28 + (packed >> 8)
    if pos + 7 > len(data):
        return None
    if data[pos:pos + 2] == b'\0\x9f':
        if pos + 28 > len(data) or vertex_count != 4 or expected != 2:
            return None
        texture = data[pos + 12]
        texture = (texture + (packed & 255)) & 255 if texture != 255 else None
        # The renderer writes these bytes as 10.5 texture coordinates scaled
        # by 64, then applies its 0x8000 texture scale.
        corners = [(i, data[pos + 14 + i], data[pos + 18 + i]) for i in range(4)]
        return [((corners[0], corners[2], corners[1]), texture),
                ((corners[1], corners[2], corners[3]), texture)]
    if packed & 255 or data[pos:pos + 2] != b'\0\x1f':
        return None
    pos += 6
    cache, faces, texture = [], [], None
    try:
        for _ in range(10000):
            command = data[pos]
            pos += 1
            op, high = command & 15, command >> 4
            if command == 6:
                # The game stops at this command; the header can exceed the emitted count.
                return faces if 0 < len(faces) <= expected else None
            if op == 0:
                if command & 0x20:
                    return None
                count = data[pos]
                pos += 2
                if not 1 <= count <= 32:
                    return None
                cache = []
                for _ in range(count):
                    index = data[pos]
                    pos += 1
                    if command & 0x80:
                        index = (index << 8) | data[pos]
                        pos += 1
                    u, v = data[pos], data[pos + 1]
                    pos += 2
                    if v & 0x80:
                        pos += 1 if u & 0x80 else 3
                    if index >= vertex_count or pos > len(data):
                        return None
                    cache.append((index, u & 127, v & 127))
            elif op in (1, 7):
                pos += 3
            elif op in (2, 8, 10):
                pass
            elif op in (3, 4):
                texture = data[pos + 1]
                pos += 2
            elif op == 9:
                texture = data[pos]
                pos += 1
            elif op in (11, 13):
                pos += 1
            elif op == 12:
                pos += 1 + high
            elif op in (5, 14):
                if op == 5:
                    count = data[pos]
                    pos += 1
                else:
                    count = high + 1
                while count:
                    word = data[pos] | (data[pos + 1] << 8)
                    pos += 2
                    count -= 1
                    a, b, c = word & 31, (word >> 5) & 31, (word >> 10) & 31
                    faces.append(((cache[a], cache[b], cache[c]), texture))
                    if word & 0x8000:
                        if not count:
                            return None
                        extra = data[pos]
                        pos += 1
                        count -= 1
                        faces.append(((cache[extra], cache[a], cache[c]), texture))
            else:
                return None
            if pos >= len(data) or len(faces) > expected:
                return None
    except IndexError:
        return None
    return None


def meshes(data):
    if len(data) < 0x40 or data[:4] != b'\0\x15\0\x11':
        return []
    count = struct.unpack_from('>I', data, 0x30)[0]
    if not 1 <= count <= 1024 or 0x3c + (count - 1) * 40 + 32 > len(data):
        return []
    result = []
    for i in range(count):
        entry = 0x3c + i * 40
        _, flags, relative = struct.unpack_from('>HHI', data, entry)
        packed = struct.unpack_from('>I', data, entry + 28)[0]
        start = entry + 4 + relative
        end = entry + 28 + (packed >> 8)
        size = end - start
        if (flags not in (4, 5, 6, 7) or size < 36
                or not 0 <= start < end <= len(data) or size > 16 + 8192 * 8):
            continue
        # Some arrays end immediately after the final position; others have
        # four padding bytes before the command stream.
        if (size - 12) % 8 == 0:
            pad = 0
        elif (size - 16) % 8 == 0 and data[end - 4:end] == bytes(4):
            pad = 4
        else:
            continue
        bounds = struct.unpack_from('>6h', data, start)
        vertices = list(struct.iter_unpack('>3h2x', data[start + 12:end - pad if pad else end]))
        if not all(bounds[0] <= x <= bounds[3] and bounds[4] <= y <= bounds[1]
                   and bounds[2] <= z <= bounds[5] for x, y, z in vertices):
            continue
        faces = _faces(data, entry, len(vertices))
        if (flags != 4 or not pad or packed & 255) and not faces:
            continue
        result.append(dict(name=f'Mesh {i + 1}' if faces else f'Mesh {i + 1} (vertices)', descriptor=entry,
                           vertices=len(vertices), triangles=len(faces) if faces else 0))
    return result


def regions(image, blocks, check):
    result = []
    pairs = {}
    for offset, (_, stored, decoded) in sorted(blocks.items()):
        if decoded > formats.MAX_BYTES:
            continue
        check()
        try:
            data = edl.unpack(image, offset)
        except formats.AssetError:
            continue
        if edl_indexed_textures.textures(data):
            next_offset = (offset + stored + 15) & ~15
            if next_offset in blocks:
                pairs[next_offset] = offset
        items = meshes(data)
        if items:
            result.append(dict(offset=offset, size=stored, kind='3d model', media='model', layout=LAYOUT,
                               confidence='validated', label='Compressed model geometry', meshes=items,
                               vertices=sum(m['vertices'] for m in items),
                               triangles=sum(m['triangles'] for m in items), nodes=0,
                               reason='Relative pointers resolve to position arrays inside declared bounds.',
                               texture_offset=pairs.get(offset),
                               preview_settings=dict(source='rom', format='auto', offset=offset)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    data = edl.unpack(image, asset['offset'])
    items = meshes(data)
    if index >= len(items) or items[index] != asset['meshes'][index]:
        raise formats.AssetError('The model pack changed. Scan ROM Explorer again.')
    entry = items[index]['descriptor']
    start = entry + 4 + struct.unpack_from('>I', data, entry + 4)[0]
    count = items[index]['vertices']
    vertices = list(struct.iter_unpack('>3h2x', data[start + 12:start + 12 + count * 8]))
    records = _faces(data, entry, count) or []
    texture_offset = asset.get('texture_offset')
    texture_data = edl.unpack(image, texture_offset) if texture_offset is not None else b''
    textures = edl_indexed_textures.textures(texture_data)
    used = {texture for _, texture in records if texture is not None and texture < len(textures)}
    materials = [dict(name='Untextured')]
    material_index = {}
    image_bytes = 0
    for texture in sorted(used):
        settings = textures[texture]['preview_settings']
        rendered = formats.preview(texture_data, settings)
        image_bytes += len(rendered['data_url'])
        if image_bytes > 16 * 1024 * 1024:
            continue
        material_index[texture] = len(materials)
        materials.append(dict(name=f'Texture {texture}', image=rendered['data_url'], state='linked', wrap='repeat'))
    edges, surfaces = set(), []
    for corners, texture in records:
        face = tuple(corner[0] for corner in corners)
        edges.update(tuple(sorted((face[i], face[(i + 1) % 3]))) for i in range(3))
        if texture in material_index:
            settings = textures[texture]['preview_settings']
            uv = [[corner[1] / settings['width'], corner[2] / settings['height']] for corner in corners]
        else:
            uv = [[0, 0]] * 3
        surfaces.append(dict(indices=face, uv=uv, colors=[[255, 255, 255, 255]] * 3,
                             material=material_index.get(texture, 0)))
    note = ('Textures follow an adjacent resource pack; runtime placement and effects are not shown.'
            if material_index else 'Untextured local geometry; runtime placement and effects are not shown.')
    if not records:
        note = 'Vertex positions only; the surface commands for this mesh have not yet been decoded.'
    return dict(media='model', vertices=vertices, triangles=len(records), edges=sorted(edges),
                points=list(range(count)), surfaces=surfaces, materials=materials,
                details=dict(format='Compressed model geometry', vertices=count, triangles=len(records)), note=note,
                settings=dict(source='rom', format='auto', offset=asset['offset'], mesh=index))

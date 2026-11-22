"""Bounded position arrays in compressed model packs.

These packs also contain a compact surface stream; its commands are not yet
understood. Expose positions as points until their topology can be decoded.
"""

import struct

from .. import formats
from . import edl

LAYOUT = 'eurocom-edl-mesh-vertices'


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
        if (flags != 4 or packed & 255 or size < 40 or (size - 16) % 8
                or not 0 <= start < end <= len(data) or size > 16 + 8192 * 8
                or data[end - 4:end] != bytes(4)):
            continue
        bounds = struct.unpack_from('>6h', data, start)
        vertices = list(struct.iter_unpack('>3h2x', data[start + 12:end - 4]))
        if not all(bounds[0] <= x <= bounds[3] and bounds[4] <= y <= bounds[1]
                   and bounds[2] <= z <= bounds[5] for x, y, z in vertices):
            continue
        result.append(dict(name=f'Mesh {i + 1} (vertices)', descriptor=entry,
                           vertices=len(vertices), triangles=0))
    return result


def regions(image, blocks, check):
    result = []
    for offset, (_, stored, decoded) in blocks.items():
        if decoded > formats.MAX_BYTES:
            continue
        check()
        try:
            data = edl.unpack(image, offset)
        except formats.AssetError:
            continue
        items = meshes(data)
        if items:
            result.append(dict(offset=offset, size=stored, kind='3d model', media='model', layout=LAYOUT,
                               confidence='validated', label='Compressed model vertices', meshes=items,
                               vertices=sum(m['vertices'] for m in items), triangles=0, nodes=0,
                               reason='Relative pointers resolve to position arrays inside declared bounds.',
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
    return dict(media='model', vertices=vertices, triangles=0, edges=[], points=list(range(count)),
                surfaces=[], materials=[], details=dict(format='Compressed model positions', vertices=count),
                note='Vertex positions only; the surface and texture commands have not been decoded.',
                settings=dict(source='rom', format='auto', offset=asset['offset'], mesh=index))

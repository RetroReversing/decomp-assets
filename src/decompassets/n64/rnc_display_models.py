"""F3DEX meshes in a relocatable RNC scene record."""

import struct

from .. import formats
from . import display_meshes

LAYOUT = 'rnc-display-model'
_MARKERS = {b'palette ': 48, b'texture ': 64}
_PIPE_SYNC = b'\xe7\0\0\0\0\0\0\0'


def _scene(data, check):
    if len(data) < 128:
        return None
    count, vertex_base = struct.unpack_from('>II', data)
    offset = 8+count*8  # each bounding sphere contains four 16-bit values
    if (not 1 <= count <= 512 or not offset < vertex_base < len(data)
            or vertex_base%8 or (len(data)-vertex_base)%16):
        return None
    image = bytearray(data)
    markers = 0
    for start in range(offset, vertex_base, 8):
        if size := _MARKERS.get(data[start:start+8]):
            end = start+size
            if end > vertex_base or any(data[start+8:end-4]):
                return None
            # Runtime texture commands replace these reservations. Leave the
            # vertex loads and triangles alone for the geometry preview.
            image[start:end] = _PIPE_SYNC*(size//8)
            markers += 1
    if not markers:
        return None
    meshes = []
    for slot in range(count):
        check()
        parsed = display_meshes.geometry(image, offset, vertex_base, {0: vertex_base})
        if parsed is None:
            return None
        end, vertices, faces = parsed
        meshes.append(dict(name=f'Display list {slot+1}', offset=offset, size=end-offset,
                           vertices=len(vertices), triangles=len(faces)))
        offset = end
    return (image, vertex_base, meshes) if offset == vertex_base else None


def asset(data, start, end, check):
    scene = _scene(data, check)
    if scene is None:
        return None
    _, _, meshes = scene
    return dict(kind='3d model', media='model', offset=start, size=end-start, label='RNC scene meshes',
                layout=LAYOUT, confidence='validated', meshes=meshes, nodes=len(meshes),
                vertices=sum(mesh['vertices'] for mesh in meshes),
                triangles=sum(mesh['triangles'] for mesh in meshes),
                reason='Every scene list closes and its relative vertex and triangle references resolve.',
                preview_settings=dict(format='auto', offset=start, source='rom'))


def preview(data, asset, selection):
    if not (scene := _scene(data, lambda: None)):
        raise formats.AssetError('The compressed scene layout changed. Rescan ROM Explorer.')
    image, vertex_base, meshes = scene
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(meshes)-1)
    record = dict(meshes[index], label=asset['label'], address_maps={0: vertex_base},
                  preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(image, record, selection)

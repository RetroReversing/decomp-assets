"""Local F3DEX2 meshes in paired cartridge resources."""

import re

from .. import formats
from . import display_meshes, paired_resources

LAYOUT = 'paired-resource-models'
_SEGMENTS = {6: 0}
_VERTEX_LOAD = re.compile(rb'\x01...\x06...', re.DOTALL)


def meshes(data):
    result = []
    previous_end = 0
    for command in _VERTEX_LOAD.finditer(data):
        start = command.start()
        if start % 8 or start < previous_end:
            continue
        mesh = display_meshes.geometry(data, start, len(data), _SEGMENTS, vertex_end=start)
        if mesh is None:
            continue
        end, vertices, faces = mesh
        result.append(dict(label=f'Mesh {len(result) + 1} · 0x{start:X}', model_offset=start,
                           model_size=end - start, vertices=len(vertices), triangles=len(faces)))
        previous_end = end
    return result


def asset(offset, size, directory, entries):
    return dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                directory=directory, label=f'{len(entries)} local F3DEX2 meshes', confidence='validated',
                meshes=entries, nodes=len(entries),
                reason='The local vertex loads and triangles resolve before the display list ends.',
                preview_settings=dict(format='auto', source='rom', offset=offset))


def preview(image, asset, selection):
    decoded = paired_resources.unpack_asset(image, asset)
    if not decoded:
        raise formats.AssetError('The compressed model resource changed. Rescan ROM Explorer.')
    entries = asset['meshes']
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(entries) - 1)
    entry = entries[index]
    start = entry['model_offset']
    local = dict(offset=start, size=entry['model_size'], address_maps=_SEGMENTS,
                 vertex_end=start, label=entry['label'], preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(decoded, local, selection)

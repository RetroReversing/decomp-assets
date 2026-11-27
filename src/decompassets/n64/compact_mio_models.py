"""Local F3DEX2 meshes in compact MIO directory members."""
from .. import formats
from . import compact_mio_textures, display_meshes

LAYOUT = 'compact-mio-models'


def meshes(data, check=lambda: None):
    """Find closed lists whose segment-one vertex references stay in the member."""
    result = []
    at = 0
    while at + 8 <= len(data):
        if not at % 0x10000:
            check()
        parsed = display_meshes.geometry(data, at, len(data), {1: 0}) if data[at] in (1, 4) else None
        if parsed:
            end, vertices, faces = parsed
            if len(vertices) >= 4 and len(faces) >= 2:
                result.append(dict(label=f'Mesh {len(result)+1}', model_offset=at, model_size=end-at,
                                   vertices=len(vertices), triangles=len(faces)))
                at = end
                continue
        at += 8
    return result


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for rows in compact_mio_textures.directories(image, check):
        for i, (start, end, size) in enumerate(rows):
            if not i % 16:
                check()
            data = compact_mio_textures.unpack(image, start, end, size) if size else None
            if not data:
                continue
            items = meshes(data, check)
            if items:
                found.append(dict(offset=start, size=end-start, unpacked=size, kind='3d model', media='model',
                                  layout=LAYOUT, label=f'{len(items)} compact MIO meshes',
                                  confidence='validated', meshes=items,
                                  vertices=sum(item['vertices'] for item in items),
                                  triangles=sum(item['triangles'] for item in items),
                                  reason='A bounded compressed member contains closed F3DEX lists with resolved local vertices and triangles.',
                                  preview_settings=dict(format='auto', source='rom', offset=start)))
    return found


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(asset['meshes'])-1)
    data = compact_mio_textures.unpack(image, asset['offset'], asset['offset']+asset['size'], asset['unpacked'])
    if data is None:
        raise formats.AssetError('The compressed model changed. Scan ROM Explorer again.')
    item = asset['meshes'][index]
    local = dict(offset=item['model_offset'], size=item['model_size'], address_maps=[(1, 0)],
                 label=item['label'], vertex_end=len(data), preview_settings=asset['preview_settings'])
    return display_meshes.preview(data, local, selection)

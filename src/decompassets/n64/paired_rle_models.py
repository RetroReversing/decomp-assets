"""Local F3DEX and F3DEX2 meshes in paired-address compressed resources."""

from .. import formats
from . import display_meshes, paired_rle_images

LAYOUT = 'paired-rle-models'
_MAX_EXPANDED = 1024*1024
_MAX_TOTAL = 64*1024*1024
_MAX_MESHES = 512


def meshes(data, check=lambda: None):
    result = []
    accepted_end = 0
    for at in range(0, len(data)-8, 8):
        if at < accepted_end or data[at] not in (1, 4):
            continue
        check()
        # The source has file-relative vertex addresses; require all loaded
        # vertices to precede this list and every face to use a loaded slot.
        parsed = display_meshes.geometry(data, at, len(data), {0: 0}, vertex_end=at)
        if parsed is None:
            continue
        end, vertices, faces = parsed
        if len(faces) < 2:
            continue
        result.append(dict(name=f'Mesh {len(result)+1}', offset=at, size=end-at,
                           vertices=len(vertices), triangles=len(faces)))
        accepted_end = end
        if len(result) >= _MAX_MESHES:
            break
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result, expanded = [], 0
    for start, end in paired_rle_images.blocks(image, check):
        data = paired_rle_images.decode(image[start:end], max_output=_MAX_EXPANDED, expected=None)
        if data is None:
            continue
        expanded += len(data)
        if expanded > _MAX_TOTAL:
            break
        if not (items := meshes(data, check)):
            continue
        result.append(dict(kind='3d model', media='model', offset=start, size=end-start,
                           label=f'Packed model resource · {len(items)} mesh(es)', confidence='validated',
                           layout=LAYOUT, nodes=len(items), meshes=items,
                           vertices=sum(item['vertices'] for item in items),
                           triangles=sum(item['triangles'] for item in items),
                           reason='The resource directory and decoder lead to closed display lists whose '
                                  'relative vertex loads and triangle slots resolve within the same resource.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = paired_rle_images.decode(image[start:start+size], max_output=_MAX_EXPANDED, expected=None)
    items = meshes(data) if data is not None else []
    if not items:
        raise formats.AssetError('The packed model resource changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(items)-1)
    local = dict(items[index], address_maps=[(0, 0)], vertex_end=items[index]['offset'],
                 label=asset['label'], preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(data, local, selection)

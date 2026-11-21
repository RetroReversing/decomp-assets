"""F3DEX meshes whose segment-two pointers address an unpacked resource."""

from .. import formats
from . import display_meshes, paged_lz

LAYOUT = 'paged-lz-display-meshes'


def _cull(w0, w1):
    # Culling bounds select even vertex-cache indexes and do not add geometry.
    first, last = w0 & 0xffffff, w1
    return w0 >> 24 == 0xbe and 0 <= first <= last < 64 and not (first | last) & 1


def meshes(data):
    found = []
    for kind, _, offset in paged_lz.records(data):
        if kind not in (0, 5):
            continue
        parsed = display_meshes.geometry(data, offset, len(data), {2: 0}, extra_state=_cull)
        if parsed is None:
            continue
        end, vertices, faces = parsed
        found.append(dict(name=f'Mesh {len(found) + 1}', offset=offset, size=end-offset,
                          vertices=len(vertices), triangles=len(faces)))
    return found


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for _, members in paged_lz.regions(image, check):
        for index, offset, size in members:
            check()
            data = paged_lz.unpack(image[offset:offset + size])
            if data is None or not (items := meshes(data)):
                continue
            result.append(dict(offset=offset, size=size, kind='3d model', media='model',
                               confidence='validated', layout=LAYOUT, nodes=len(items), meshes=items,
                               vertices=sum(item['vertices'] for item in items),
                               triangles=sum(item['triangles'] for item in items),
                               label=f'Model resource {index} · {len(items)} mesh(es)',
                               reason='The resource directory locates closed F3DEX lists with local vertex pointers.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = paged_lz.unpack(image[start:start + size])
    if data is None or not (items := meshes(data)):
        raise formats.AssetError('The archived model resource changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(items) - 1)
    settings = dict(asset['preview_settings'], mesh=index)
    local = dict(items[index], address_maps=[(2, 0)], label=asset['label'], preview_settings=settings)
    return display_meshes.preview(data, local, selection, extra_state=_cull)

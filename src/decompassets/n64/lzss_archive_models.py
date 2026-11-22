"""F3DEX meshes in mixed compressed resource directories."""

import struct

from .. import formats
from . import display_meshes, lzss_archive_images

LAYOUT = 'ring-lzss-models'


def _state(word, value):
    return (word, value) == (0xdb060000, 0) or (word >> 24 == 0xbe and not (word | value) & 1
                                                   and (word & 0xffffff) <= value < 64)


def meshes(data):
    if not data or len(data) < 24 or data[0] != 5:
        return []
    offsets = []
    for at in range(0, min(len(data), 4096), 4):
        value, = struct.unpack_from('>I', data, at)
        if value == 0:
            break
        if value >> 24 != 5 or value & 7 or (value & 0xffffff) >= len(data):
            return []
        offsets.append(value & 0xffffff)
    if len(offsets) < 2 or offsets != sorted(set(offsets)) or offsets[0] < (len(offsets) + 1) * 4:
        return []
    found = []
    for offset in offsets:
        parsed = display_meshes.geometry(data, offset, len(data), {5: 0}, extra_state=_state)
        if parsed:
            end, vertices, faces = parsed
            found.append(dict(name=f'Mesh {len(found) + 1}', offset=offset, size=end-offset,
                              vertices=len(vertices), triangles=len(faces)))
    return found



def textures(data, items):
    """Read image and palette pointers from validated local display lists."""
    found = {}
    for item in items:
        image = palette = None
        size = bottom = None
        width = 0
        for at in range(item['offset'], item['offset'] + item['size'], 8):
            word, value = struct.unpack_from('>2I', data, at)
            op = word >> 24
            if op == 0xfd:
                image = value & 0xffffff if value >> 24 == 5 else None
                width = (word & 0x3ff) + 1
            elif op == 0xf5:
                size = (word >> 19) & 3
            elif op == 0xf0 and image is not None:
                count = ((value >> 14) & 1023) + 1
                palette = (image, count) if count in (16, 256) and image + count * 2 <= len(data) else None
                image = None
            elif op == 0xf4:
                bottom = (value & 0xfff) // 4 + 1
            elif op == 0xf2 and image is not None:
                height = bottom or ((value & 0xfff) // 4 + 1)
                bits = 8 if size == 1 and palette and palette[1] == 256 else 4 if size == 0 and palette and palette[1] == 16 else 0
                pixels = width * height * bits // 8
                if bits and 2 <= width <= 512 and 2 <= height <= 512 and image + pixels <= len(data):
                    found[image] = dict(offset=image, width=width, height=height, bits=bits, palette=palette[0])
                image = None
                bottom = None
    return list(found.values())

def regions(image, *, images=None, check=lambda: None, **kwargs):
    result = []
    for base, rows in lzss_archive_images.archives(image):
        for index, row in enumerate(rows):
            if row[2] > 1024 * 1024:
                continue
            data = lzss_archive_images.unpack(image, base, row)
            items = meshes(data)
            if items:
                offset, _, _, packed = row
                pictures = textures(data, items)
                if images is not None and pictures:
                    images.append(dict(offset=base+offset, size=packed, kind='image', layout='ring-lzss-model-images',
                                       archive=base, member=index, frames=len(pictures), confidence='inferred',
                                       width=pictures[0]['width'], height=pictures[0]['height'],
                                       label=f'Model texture resource ({len(pictures)} images)',
                                       reason='Display-list texture and palette pointers resolve inside the resource; dimensions are inferred.',
                                       preview_settings=dict(format='auto', source='rom', offset=base+offset, frame=0)))
                result.append(dict(offset=base+offset, size=packed, kind='3d model', media='model',
                                   layout=LAYOUT, archive=base, member=index, nodes=len(items), meshes=items,
                                   triangles=sum(item['triangles'] for item in items), confidence='validated',
                                   label=f'Compressed model ({len(items)} meshes)',
                                   reason='The archive contains local display-list pointers and resolving vertex batches.',
                                   preview_settings=dict(format='auto', source='rom', offset=base+offset, mesh=0)))
            check()
    return result


def preview(image, asset, selection):
    rows = next((rows for base, rows in lzss_archive_images.archives(image) if base == asset['archive']), None)
    if rows is None or asset['member'] >= len(rows):
        raise formats.AssetError('The model archive changed. Rescan ROM Explorer.')
    data = lzss_archive_images.unpack(image, asset['archive'], rows[asset['member']])
    items = meshes(data)
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(items) - 1)
    local = dict(items[index], address_maps=[(5, 0)], label=asset['label'],
                 preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(data, local, selection, extra_state=_state)


def preview_image(image, asset, selection):
    rows = next((rows for base, rows in lzss_archive_images.archives(image) if base == asset['archive']), None)
    if rows is None or asset['member'] >= len(rows):
        raise formats.AssetError('The texture archive changed. Rescan ROM Explorer.')
    data = lzss_archive_images.unpack(image, asset['archive'], rows[asset['member']])
    pictures = textures(data, meshes(data))
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, len(pictures)-1)
    item = pictures[frame]
    settings = dict(format='ci8' if item['bits'] == 8 else 'ci4', offset=item['offset'],
                    width=item['width'], height=item['height'], palette_offset=item['palette'],
                    palette_format='rgba5551-be')
    result = formats.preview(data, settings)
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result

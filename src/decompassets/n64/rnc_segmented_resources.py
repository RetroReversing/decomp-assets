"""Segmented display lists, texture payloads and vertices in consecutive RNC blocks."""
import re
import struct

from .. import formats, rnc
from . import display_lists, segmented_model_resources

TEXTURE = 'rnc-segmented-textures'
MODEL = 'rnc-segmented-model'
_MAGIC = re.compile(rb'RNC[\x01\x02]')
_LIMIT = 4 * 1024 * 1024


def _next(image, at):
    # Packed members are stored back to back, with at most one alignment byte.
    for offset in dict.fromkeys((at, at+(at & 1))):
        if image[offset:offset+4] in (b'RNC\1', b'RNC\2'):
            try:
                data, size = rnc.unpack_at(image, offset, max_output=_LIMIT, max_packed=_LIMIT)
                return offset, data, size
            except rnc.RncError:
                return None
    return None


def _read(image, start):
    """Require all three checksummed streams and the original section boundaries."""
    try:
        commands, size = rnc.unpack_at(image, start, max_output=_LIMIT, max_packed=_LIMIT)
    except rnc.RncError:
        return None
    if (len(commands) < 40 or len(commands) % 8 or int.from_bytes(commands[:4], 'big') != len(commands)-16
            or commands[4:12] != segmented_model_resources._MARKER.pattern):
        return None
    texture = _next(image, start+size)
    if texture is None:
        return None
    texture_at, pixels, texture_size = texture
    if len(pixels) < 8 or struct.unpack_from('>II', pixels) != (len(pixels)-8, 0):
        return None
    vertex = _next(image, texture_at+texture_size)
    if vertex is None:
        return None
    vertex_at, vertices, vertex_size = vertex
    if (len(vertices) < 56 or (len(vertices)-8) % 16 or int.from_bytes(vertices[:2], 'big') != (len(vertices)-8)//16
            or any(vertices[4:8])):
        return None
    source = bytes(4)+struct.pack('<3I', len(commands), len(vertices), 0)+commands+vertices
    mesh = segmented_model_resources._model(source, 4)
    if mesh is None:
        return None
    return commands, pixels, vertices, mesh, (size, texture_at, texture_size, vertex_at, vertex_size)


def _textures(commands, pixels):
    vertices, loads = display_lists._commands(commands, lambda: None)
    groups = display_lists._files(vertices, loads)
    found = {}
    for group in groups:
        for tile in display_lists._textures(commands, group):
            # The segment marker describes the image and palette buffer; both
            # must fit the validated payload, with a complete palette.
            if (tile['space'] != 11 or tile.get('palette_space') != 11
                    or tile['fmt'] not in ('ci4', 'ci8') or tile.get('palette_entries') not in (16, 256)
                    or tile['fmt'] == 'ci4' and tile.get('palette_entries') != 16):
                continue
            width, height = tile['width'], tile['height']
            row = (width*(4 if tile['fmt'] == 'ci4' else 8)+7)//8
            data_at, palette_at = 8+tile['address'], 8+tile['palette_address']
            count = tile['palette_entries']
            if (tile['swapped'] and row % 8 or data_at < 8 or data_at+row*height > len(pixels)
                    or palette_at < 8 or palette_at+count*2 > len(pixels)):
                continue
            if tile['fmt'] == 'ci8' and count < 256 and max(pixels[data_at:data_at+row*height], default=0) >= count:
                continue
            key = (data_at, palette_at, tile['fmt'], width, height, tile['palette_format'], tile['swapped'])
            found[key] = dict(offset=data_at, palette_offset=palette_at, format=tile['fmt'], width=width,
                              height=height, palette_format=tile['palette_format'], palette_entries=count,
                              swapped=tile['swapped'])
    return list(found.values())


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for hit in _MAGIC.finditer(image):
        check()
        start = hit.start()
        found = _read(image, start)
        if found is None:
            continue
        commands, pixels, _, mesh, blocks = found
        size, texture_at, texture_size, vertex_at, vertex_size = blocks
        reason = ('Three consecutive checksum-verified streams contain a complete segmented display list, '
                  'a sized texture payload and indexed vertices. Scene transforms and animation are not established.')
        common = dict(offset=start, size=size, confidence='validated', reason=reason,
                      preview_settings=dict(format='auto', source='rom', offset=start),
                      texture_block=texture_at, texture_size=texture_size, vertex_block=vertex_at, vertex_size=vertex_size)
        points, faces, _ = mesh
        result.append(dict(**common, kind='3d model', media='model', layout=MODEL,
                           label='RNC segmented model', vertices=len(points), triangles=len(faces),
                           meshes=[dict(name='Mesh 1', vertices=len(points), triangles=len(faces))]))
        if items := _textures(commands, pixels):
            result.append(dict(**common, kind='image', layout=TEXTURE, label='RNC segmented textures',
                               textures=[dict(name=f'Texture {i+1}', width=t['width'], height=t['height'],
                                              preview_settings=dict(format=t['format'], width=t['width'], height=t['height']))
                                         for i, t in enumerate(items)], texture_count=len(items),
                               width=items[0]['width'], height=items[0]['height']))
    return result


def preview(image, asset, selection):
    found = _read(image, asset['offset'])
    if found is None:
        raise formats.AssetError('The compressed segmented asset changed. Rescan ROM Explorer.')
    commands, pixels, _, mesh, _ = found
    if asset['layout'] == MODEL:
        formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
        vertices, faces, _ = mesh
        edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
        return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                    points=list(range(len(vertices))),
                    surfaces=[dict(indices=face, uv=[[0, 0]]*3, colors=[[255, 255, 255, 255]]*3, material=0)
                              for face in faces], materials=[],
                    details=dict(format='RNC segmented model', vertices=len(vertices), triangles=len(faces)),
                    note='Local geometry; scene transforms, textures and animation are separate.',
                    settings=dict(format='auto', source='rom', offset=asset['offset'], mesh=0))
    textures = _textures(commands, pixels)
    if asset['layout'] != TEXTURE or not textures:
        raise formats.AssetError('The compressed texture bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures)-1)
    tile = textures[index]
    row = (tile['width']*(4 if tile['format'] == 'ci4' else 8)+7)//8
    bitmap = bytearray(pixels[tile['offset']:tile['offset']+row*tile['height']])
    if tile['swapped']:
        for y in range(1, tile['height'], 2):
            at = y*row
            for x in range(0, row, 8):
                bitmap[at+x:at+x+8] = bitmap[at+x+4:at+x+8]+bitmap[at+x:at+x+4]
    count = tile['palette_entries']
    palette = pixels[tile['palette_offset']:tile['palette_offset']+count*2]
    expected = 256 if tile['format'] == 'ci8' else 16
    raw = bitmap+palette+bytes((expected-count)*2)
    result = formats.preview(raw, dict(format=tile['format'], width=tile['width'], height=tile['height'],
                                       offset=0, palette_offset=len(bitmap), palette_format=tile['palette_format']))
    result['details'].update(texture=index, palette_colours=count, note='Texture and palette from the checked segment buffer.')
    result['settings'] = dict(format='auto', source='rom', offset=asset['offset'], texture=index)
    return result

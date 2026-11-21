"""Packed runtime scene resources with local F3DEX2 display lists."""

import re
import struct

from .. import formats
from . import display_meshes

IMAGE = 'yay0-scene-textures'
MODEL = 'yay0-scene-models'
_MAGIC = re.compile(rb'Yay0')
_COMMAND = struct.Struct('>II')
_PIXEL_FORMATS = {(0, 2): 'rgba5551-be', (0, 3): 'rgba8888', (2, 0): 'ci4', (2, 1): 'ci8'}
_HEADER_SIZE = 120


def _lists(data):
    if (len(data) < _HEADER_SIZE or data[:8] not in (b'niff\x05\0\x01\0', b'niff\x04\x02\x01\0')
            or int.from_bytes(data[12:16], 'big') != len(data)):
        return
    table = int.from_bytes(data[60:64], 'big')
    count = int.from_bytes(data[88:90], 'big')
    if not count or table % 4 or not _HEADER_SIZE <= table <= len(data)-4*count:
        return
    for entry, in struct.iter_unpack('>I', data[table:table+4*count]):
        if not _HEADER_SIZE <= entry <= table-32:
            continue
        start, vertex, _, *segments = struct.unpack_from('>8I', data, entry)
        if not _HEADER_SIZE <= vertex < start < entry or start % 8:
            continue
        result = display_meshes.geometry(data, start, entry, {4: vertex}, vertex_end=start)
        if result:
            yield start, vertex, result, dict(enumerate(segments, 5))


def _address(pointer, segments, end, size):
    base = segments.get(pointer >> 24, 0)
    address = base + (pointer & 0xffffff)
    if _HEADER_SIZE <= base <= address <= end-size:
        return address
    return None


def _textures(data, start, end, segments):
    # The load commands use a temporary tile. The render tile declares the
    # actual texel format, row pitch and bounds.
    tiles = {}
    pointer = palette = image = None
    tlut = 0
    for word, value in _COMMAND.iter_unpack(data[start:end]):
        operation, slot = word >> 24, (value >> 24) & 7
        if word == 0xe3001001:
            tlut = (value >> 14) & 3
        elif operation == 0xfd:
            pointer = value
        elif operation == 0xf5:
            tiles[slot] = ((word >> 21) & 7, (word >> 19) & 3, (word >> 9) & 511)
        elif operation == 0xf0 and pointer is not None:
            entries = ((value >> 14) & 1023) + 1
            palette = _address(pointer, segments, start, entries*2), entries
        elif operation == 0xf3:
            image = pointer
        elif operation == 0xf2 and image is not None and slot in tiles:
            kind, size, pitch = tiles[slot]
            fmt = _PIXEL_FORMATS.get((kind, size))
            if fmt is None or word & 0xffffff or value & 0x003003:
                continue
            width, height = ((value >> 14) & 1023) + 1, ((value >> 2) & 1023) + 1
            stride = (width * (4 << size) + 7)//8
            if pitch*8 != (stride//2 if size == 3 else stride):
                continue
            offset = _address(image, segments, start, stride*height)
            if offset is None:
                continue
            settings = dict(format=fmt, width=width, height=height, offset=offset)
            if kind == 2:
                if tlut not in (2, 3) or not palette or palette[0] is None or palette[1] != (16 if size == 0 else 256):
                    continue
                settings.update(palette_offset=palette[0], palette_format='ia16' if tlut == 3 else 'rgba5551-be')
            yield settings


def _assets(data):
    meshes, textures = [], {}
    for start, vertex, (end, vertices, faces), segments in _lists(data):
        meshes.append(dict(name=f'Mesh {len(meshes)+1}', offset=start, size=end-start, vertex_base=vertex,
                           vertices=len(vertices), triangles=len(faces)))
        for settings in _textures(data, start, end, segments):
            textures[tuple(settings.values())] = settings
    return meshes, list(textures.values())


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _MAGIC.finditer(image):
        check()
        offset = match.start()
        expanded = int.from_bytes(image[offset+4:offset+8], 'big')
        chunks = int.from_bytes(image[offset+12:offset+16], 'big')
        if (not _HEADER_SIZE <= expanded <= formats.MAX_BYTES or not 16 <= chunks < formats.MAX_BYTES
                or image[offset+chunks:offset+chunks+4] != b'niff'):
            continue
        try:
            data, _, size = formats.unpack_extent(image[offset:offset+formats.MAX_BYTES])
        except formats.AssetError:
            continue
        meshes, textures = _assets(data)
        base = dict(offset=offset, size=size, confidence='validated',
                    reason='The scene directory and closed display lists corroborate the local segment addresses.',
                    preview_settings=dict(format='auto', source='rom', offset=offset))
        if meshes:
            result.append(dict(base, kind='3d model', media='model', layout=MODEL, nodes=len(meshes), meshes=meshes,
                               vertices=sum(mesh['vertices'] for mesh in meshes),
                               triangles=sum(mesh['triangles'] for mesh in meshes),
                               label=f'Scene resource · {len(meshes)} mesh(es)'))
        if textures:
            items = [dict(label=f"{tex['format'].upper()} {tex['width']}×{tex['height']}",
                          frames=1, palettes=int('palette_offset' in tex), frame_offsets=[0],
                          levels=[dict(width=tex['width'], height=tex['height'], offset=0)],
                          preview_settings=tex) for tex in textures]
            result.append(dict(base, kind='image', layout=IMAGE, textures=items, texture_count=len(items),
                               label=f'Scene resource · {len(items)} texture(s)', frames=1, frame_offsets=[0],
                               levels=items[0]['levels'], palettes=items[0]['palettes']))
    return result


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    data, _ = formats.unpack(image[offset:offset+size])
    meshes, textures = _assets(data)
    if asset['layout'] == MODEL and meshes:
        index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(meshes)-1)
        mesh = meshes[index]
        settings = dict(asset['preview_settings'], mesh=index)
        local = dict(mesh, address_maps=[(4, mesh['vertex_base'])], vertex_end=mesh['offset'],
                     label=asset['label'], preview_settings=settings)
        return display_meshes.preview(data, local, selection)
    if asset['layout'] == IMAGE and textures:
        index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures)-1)
        result = formats.preview(data, textures[index])
        result['details'].update(texture=index, note=asset['reason'])
        result['settings'] = dict(source='rom', format='auto', offset=offset, texture=index, frame=0, palette=0, mip=0)
        return result
    raise formats.AssetError('The archived scene changed. Rescan ROM Explorer.')

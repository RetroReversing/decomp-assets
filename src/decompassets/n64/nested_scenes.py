"""Length-prefixed LZSS scene members with segment-relative graphics."""

import re

from .. import formats
from . import display_meshes, paged_lz, paged_lz_models, rdp_textures

IMAGE = 'nested-scene-textures'
MODEL = 'nested-scene-models'
_HEADER = b'64\x008'
_MARKER = re.compile(re.escape(_HEADER))
_MAX_INPUT = 256 * 1024


def unpack(stream):
    """The little-endian prefix counts input bytes and the ring starts at 0xfee."""
    if len(stream) < 5 or int.from_bytes(stream[:4], 'little') != len(stream)-4:
        return None
    ring = bytearray(4096)
    out = bytearray()
    cursor, write, bit = 4, 0xfee, 0
    while cursor < len(stream):
        if not bit:
            flags = stream[cursor]
            cursor += 1
            bit = 1
        if flags & bit:
            if cursor == len(stream):
                return None
            values = (stream[cursor],)
            cursor += 1
        else:
            if cursor+2 > len(stream):
                return None
            low, high = stream[cursor:cursor+2]
            cursor += 2
            index, count = low | (high & 0xf0) << 4, (high & 15)+3
            values = (ring[(index+step) & 4095] for step in range(count))
        bit = (bit << 1) & 255
        for value in values:
            out.append(value)
            ring[write] = value
            write = (write+1) & 4095
        if len(out) > formats.MAX_BYTES:
            return None
    return bytes(out)


def _graphs(data):
    if not data or not paged_lz.records(data):
        return [], []
    meshes, textures = [], {}
    for match in _MARKER.finditer(data):
        base = match.start()
        if base % 8:
            continue
        local = data[base:]
        candidates = paged_lz_models.meshes(local)
        if not candidates:
            continue
        floor = 12 + 12*int.from_bytes(local[4:8], 'big')
        for mesh in candidates:
            start = mesh['offset']
            end = start+mesh['size']
            meshes.append(dict(mesh, name=f'Mesh {len(meshes)+1}', offset=base+start, vertex_base=base))
            for settings in rdp_textures.textures(local, start, end, {2: 0}, floor=floor, tlut_command=0xba000e02):
                settings['offset'] += base
                if 'palette_offset' in settings:
                    settings['palette_offset'] += base
                textures[tuple(settings.values())] = settings
    return meshes, list(textures.values())


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _MARKER.finditer(image):
        check()
        offset = match.start()-5
        if offset < 0 or offset%16 or image[offset+4] & 15 != 15:
            continue
        size = int.from_bytes(image[offset:offset+4], 'little')+4
        if not 9 <= size <= _MAX_INPUT or offset+size > len(image):
            continue
        data = unpack(image[offset:offset+size])
        meshes, textures = _graphs(data)
        common = dict(offset=offset, size=size, confidence='validated',
                      reason='Closed display lists resolve segment-two references inside the decoded scene.',
                      preview_settings=dict(format='auto', source='rom', offset=offset))
        if meshes:
            result.append(dict(common, kind='3d model', media='model', layout=MODEL, nodes=len(meshes), meshes=meshes,
                               vertices=sum(mesh['vertices'] for mesh in meshes),
                               triangles=sum(mesh['triangles'] for mesh in meshes), label='Compressed scene geometry'))
        if textures:
            items = [dict(label=f"{tex['format'].upper()} {tex['width']}×{tex['height']}", frames=1,
                          palettes=int('palette_offset' in tex), frame_offsets=[0],
                          levels=[dict(width=tex['width'], height=tex['height'], offset=0)],
                          preview_settings=tex) for tex in textures]
            result.append(dict(common, kind='image', layout=IMAGE, textures=items, texture_count=len(items),
                               label='Compressed scene textures', frames=1, frame_offsets=[0],
                               levels=items[0]['levels'], palettes=items[0]['palettes']))
    return result


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    data = unpack(image[offset:offset+size])
    meshes, textures = _graphs(data)
    if asset['layout'] == MODEL and meshes:
        index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(meshes)-1)
        mesh = meshes[index]
        local = dict(mesh, label=asset['label'], address_maps=[(2, mesh['vertex_base'])],
                     preview_settings=dict(asset['preview_settings'], mesh=index))
        return display_meshes.preview(data, local, selection, extra_state=paged_lz_models._cull)
    if asset['layout'] == IMAGE and textures:
        index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures)-1)
        result = formats.preview(data, textures[index])
        result['details'].update(texture=index, note=asset['reason'])
        result['settings'] = dict(source='rom', format='auto', offset=offset, texture=index, frame=0, palette=0, mip=0)
        return result
    raise formats.AssetError('The compressed scene changed. Rescan ROM Explorer.')

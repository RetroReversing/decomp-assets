"""Native raw-deflate archives with their own F3DEX lists and segment tables."""

import re
import struct
import zlib
from itertools import pairwise

from .. import formats
from . import display_lists, display_meshes

TEXTURE = 'raw-deflate-list-textures'
MODEL = 'raw-deflate-list-models'
_DMA_ROW = struct.Struct('>4I')
_DMA_PREFIX = re.compile(rb'\x80[\0-\x7f]..\0[\0-\x3f]..\0...\0...', re.S)
_HEADER = struct.Struct('>12I')
_LIMIT = 4 * 1024 * 1024


def _directories(image, check):
    """Use a repeated RAM destination, capacity and paired cartridge extents."""
    limit = min(len(image), 0x100000)
    skipped = 0
    for match in _DMA_PREFIX.finditer(image, 0, limit):
        start = match.start()
        if start % 4 or start < skipped:
            continue
        check()
        rows = []
        for at in range(start, min(limit - 15, start + 256 * _DMA_ROW.size), _DMA_ROW.size):
            dest, capacity, end, offset = _DMA_ROW.unpack_from(image, at)
            if (not 0x80000400 <= dest < dest + capacity <= 0x80800000
                    or not 16 <= capacity <= _LIMIT or (dest | capacity | end | offset) % 16
                    or not at + _DMA_ROW.size < offset < end <= len(image)):
                break
            rows.append((offset, end))
        skipped = start + _DMA_ROW.size * len(rows)
        spans = sorted(set(rows))
        if (len(spans) >= 4 and all(left[1] <= right[0] for left, right in pairwise(spans))
                and sum(left[1] == right[0] for left, right in pairwise(spans)) >= 3):
            yield spans


def members(image, offset, size, marker):
    if not 0 <= offset <= len(image) - size or not 16 <= size <= _LIMIT:
        return []
    inflater = zlib.decompressobj(-15)
    try:
        data = inflater.decompress(image[offset:offset + size], _LIMIT + 1)
    except zlib.error:
        return []
    if not (inflater.eof and len(inflater.unused_data) < 16 and 16 <= len(data) <= _LIMIT
            and data[:2] == marker):
        return []
    count = int.from_bytes(data[2:4], 'big')
    if not 1 <= count <= 512 or 8 + count * 4 > len(data):
        return []
    offsets = struct.unpack_from(f'>{count}I', data, 4)
    first = (8 + count * 4 + 15) & ~15
    if (offsets[0] != first or any(start % 16 or not start < stop
                                   for start, stop in pairwise((*offsets, len(data))))):
        return []
    return [data[start:stop] for start, stop in pairwise((*offsets, len(data)))]


def _member_layout(member):
    if len(member) < _HEADER.size:
        return None
    header = _HEADER.unpack_from(member)
    display, vertex, texels = header[2], header[3], header[7]
    if (not header[0] & 0xffff or not header[1] or texels != _HEADER.size
            or not texels < vertex < display < len(member) or (vertex | display) % 8):
        return None
    end = min((offset for offset in header[4:] if display < offset <= len(member)), default=len(member))
    return display, vertex, texels, end


def _textures(member, display, vertex, texels, end):
    textures = {}
    for tile in display_lists._textures(member[:end], {'start': display, 'end': end}):
        offset = texels + tile['address']
        if tile['space'] != 4 or offset + tile['bytes'] > vertex:
            continue
        fmt, width, height = tile['fmt'], tile['width'], tile['height']
        settings = dict(format=fmt, width=width, height=height, offset=offset)
        if 'palette_address' in tile:
            palette = texels + tile['palette_address']
            entries = 16 if fmt == 'ci4' else 256
            if (tile['palette_space'] != 4 or palette + entries * 2 > vertex
                    or tile['palette_entries'] != entries):
                continue
            settings.update(palette_offset=palette, palette_format=tile['palette_format'])
        key = (offset, fmt, width, height, settings.get('palette_offset'))
        palettes = int('palette_offset' in settings)
        textures[key] = dict(label=f'{display_lists.NAMES[fmt]} {width}×{height}', frames=1, palettes=palettes,
                             levels=[dict(width=width, height=height, offset=0)], preview_settings=settings)
    return textures.values()


def _collect(members, check):
    textures, meshes = [], []
    for index, member in enumerate(members):
        check()
        if not (layout := _member_layout(member)):
            continue
        display, vertex, texels, end = layout
        textures.extend(dict(texture, member=index) for texture in _textures(member, *layout))
        parsed = display_meshes.geometry(member, display, end, {3: vertex},
                                         vertex_end=display, allow_padded_load=True)
        if parsed:
            stop, vertices, faces = parsed
            meshes.append(dict(member=index, label=f'Model {index + 1} · {len(vertices)} vertices',
                               display=display, size=stop - display, vertex=vertex,
                               vertices=len(vertices), triangles=len(faces)))
    return textures, meshes


def archive_spans(image, check):
    return sorted({(offset, end) for spans in _directories(image, check) for offset, end in spans})


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for offset, end in archive_spans(image, check):
        check()
        textures, meshes = _collect(members(image, offset, end - offset, b'\xaa\xaa'), check)
        common = dict(offset=offset, size=end - offset, confidence='validated',
                      preview_settings=dict(source='rom', format='auto', offset=offset))
        if textures:
            result.append(dict(common, kind='image', layout=TEXTURE, label=f'{len(textures)} local textures',
                               textures=textures, texture_count=len(textures), frames=1,
                               palettes=textures[0]['palettes'], levels=textures[0]['levels'],
                               reason='Native display-list commands place the texture pixels and palettes in each member.'))
        if meshes:
            result.append(dict(common, kind='3d model', media='model', layout=MODEL,
                               label=f'{len(meshes)} F3DEX meshes', meshes=meshes, nodes=len(meshes),
                               reason='Native resource headers identify the display lists and their local vertex arrays.'))
    return result


def preview(image, asset, selection):
    decoded = members(image, asset['offset'], asset['size'], b'\xaa\xaa')
    if not decoded:
        raise formats.AssetError('The compressed display-list archive changed. Rescan ROM Explorer.')
    if asset['layout'] == TEXTURE:
        index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures']) - 1)
        texture = asset['textures'][index]
        result = formats.preview(decoded[texture['member']], texture['preview_settings'])
        result['details'].update(texture=index, note=asset['reason'])
        result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
        return result
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    mesh = asset['meshes'][index]
    local = dict(offset=mesh['display'], size=mesh['size'], vertex_end=mesh['display'],
                 address_maps={3: mesh['vertex']}, label=mesh['label'],
                 preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(decoded[mesh['member']], local, selection, allow_padded_load=True)

"""Recognize model textures in a deflated asset table of the kind a Rare platformer sequel uses.

The table is a count, 0xFFFFFFFF, then one word per asset whose top 24 bits are its offset in words from
the table's end; an asset is a two-byte header and a raw deflate stream that must end inside its slot.
A model starts with 0x0000000B; the halfword at 8 points to its texture list: a byte size, a count, then
eight bytes per texture (data offset, type, width, height) and the texture data, a palette before its
pixels. Types: 1 CI4, 2 CI8, 4 RGBA16, 8 RGBA32, 16 IA8; 0x8000 marks smaller mip levels after the first,
which is the one shown. A model is taken only when its first texture starts the data, every later one starts after it, and all fit.
"""
from __future__ import annotations

import re
import struct
import zlib

from .. import formats as asset_formats
from ..formats import AssetError

MAX_ASSETS = 65535
MAX_MODEL = 4 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MODEL = b'\0\0\0\x0b'
TYPES = {1: ('ci4', 16, 4), 2: ('ci8', 256, 8), 4: ('rgba5551-be', 0, 16), 8: ('rgba8888', 0, 32), 16: ('ia8', 0, 8)}


def tables(image, check=lambda: None):
    """Each asset table: (where its entries start, the base their offsets count from, the entries)."""
    found = []
    for match in re.finditer(rb'\x00\x00..\xff\xff\xff\xff\x00\x00\x00', image, re.S):
        check()
        at = match.start()
        if at % 4:continue
        count = int.from_bytes(image[at:at+4], 'big')
        start = at + 8
        if not 16 <= count <= MAX_ASSETS or start + 4*count > len(image):continue
        entries = struct.unpack_from(f'>{count}I', image, start)
        words = [e >> 8 for e in entries]
        base = start + 4*count
        if words[0] or any(b < a for a, b in zip(words, words[1:])) or base + 4*words[-1] > len(image):continue
        found.append((start, base, entries))
    return found


def _inflate(data, limit):
    stream = zlib.decompressobj(-15)
    try:out = stream.decompress(data[2:], limit)
    except zlib.error:return None
    return out if stream.eof else None


def texture_list(model):
    """The model's textures as preview items relative to the model, or None when the list doesn't hold."""
    if model[:4] != MODEL or len(model) < 16:return None
    setup = int.from_bytes(model[8:10], 'big')
    if not setup or setup + 8 > len(model):return None
    count = int.from_bytes(model[setup+4:setup+6], 'big')
    data = setup + 8 + 8*count
    if not 0 < count <= 256 or data > len(model):return None
    items, last = [], -1
    for index in range(count):
        offset, kind, width, height = struct.unpack_from('>IHBB', model, setup + 8 + 8*index)
        if kind & 0x7FFF not in TYPES or not width or not height or offset <= last or not index and offset:return None
        fmt, entries, bits = TYPES[kind & 0x7FFF]
        start, pixels = data + offset, (width*bits + 7)//8*height
        if start + 2*entries + pixels > len(model):return None
        last = offset
        settings = dict(format=fmt, width=width, height=height, offset=start + 2*entries)
        if entries:settings.update(palette_offset=start, palette_format='rgba5551-be')
        items.append(dict(preview_settings=settings, frames=1, palettes=1 if entries else 0, frame_offsets=[settings['offset']],
                          palette_offsets=[start] if entries else [], palette_entries=[entries] if entries else [],
                          levels=[dict(width=width, height=height, offset=0)], mipmapped=bool(kind & 0x8000)))
    return items


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per model asset whose texture list checks out, holding all its textures."""
    from .rare_assets import mesh_region

    results, expanded = [], 0
    for start, base, entries in tables(image, check):
        for index, (entry, following) in enumerate(zip(entries, entries[1:])):
            if index % 256 == 0:
                check();progress(dict(phase='Reading the deflated asset table', done=index, total=len(entries)))
            offset, end = base + 4*(entry >> 8), base + 4*(following >> 8)
            if end - offset < 4:continue
            head = zlib.decompressobj(-15)
            try:
                if head.decompress(image[offset+2:end], 4) != MODEL:continue
            except zlib.error:continue
            model = _inflate(image[offset:end], MAX_MODEL)
            if not model:continue
            expanded += len(model)
            if expanded > MAX_EXPANDED:return results
            if mesh := mesh_region(index,offset,end,model,modern=True):
                results.append(mesh)
            items = texture_list(model)
            if not items:continue
            first = items[0]['preview_settings']
            results.append(dict(offset=offset, size=end-offset, kind='image', confidence='validated', layout='rare-model',
                                label=f'Model {index} · {len(items)} texture(s)', asset_index=index, textures=items,
                                **{k: v for k, v in items[0].items() if k != 'preview_settings'},
                                preview_settings={**first, 'source': 'rom', 'offset': offset},
                                reason='The asset table entry and its deflate stream end together; the model\'s texture list '
                                       'has rising offsets and every texture fits. Runtime use is not established.'))
    return results


def preview(image, asset, selection):
    """Inflate the model again and show the chosen texture's first level."""
    model = _inflate(image[asset['offset']:asset['offset']+asset['size']], MAX_MODEL)
    from .rare_assets import SEQUEL_MESH, mesh_preview

    if model and asset['layout'] == SEQUEL_MESH:
        return mesh_preview(model,asset,selection)
    items = model and texture_list(model)
    if not items:raise AssetError('The model asset changed. Rescan the ROM.')
    texture = asset_formats.integer(selection.get('texture', 0), 'Texture', 0, len(items)-1)
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    item = items[texture]
    result = asset_formats.preview(model, item['preview_settings'])
    result['details'].update(texture=texture, frame=0, palette=0 if item['palettes'] else 'none', note=asset['reason'])
    result['decoded'] = dict(codec='deflate', bytes=len(model), block_offset=asset['offset'], member=f"asset {asset['asset_index']}")
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=texture, frame=0, palette=0, mip=0)
    return result

"""Recognize I64 images in an FFS filesystem packed as one chunked RNC stream.

The stream (method byte 0x81) holds the whole filesystem in 4 KB chunks, each packed on its own
(`rnc.chunked`). Unpacked, it starts with "FFS\\0", a file count and one 24-byte record per file: an id,
a size and an offset, with no names. An I64 image is "I64\\0", width, height and a format word, then the
palette (if any) and the pixels; its file size must be exactly that. The formats seen are 0 CI4, 1 CI8,
4 I4 and 5 I8, palettes RGBA 5551. Only the chunks holding a file's first bytes are unpacked to find it.
"""
from __future__ import annotations

import re
import struct

from .. import formats as asset_formats
from .. import rnc
from ..formats import AssetError

MAX_FILES = 16384
FORMATS = {0: ('ci4', 16), 1: ('ci8', 256), 4: ('i4', 0), 5: ('i8', 0)}
BITS = {'ci4': 4, 'ci8': 8, 'i4': 4, 'i8': 8}


class _Reader:
    """Output bytes of a chunked stream, keeping the chunks already unpacked."""

    def __init__(self, image, layout, check):
        self.image, self.layout, self.check, self.chunks = image, layout, check, {}

    def read(self, start, end):
        out = bytearray()
        for index in range(start // rnc.CHUNK_BYTES, (max(start, end-1)) // rnc.CHUNK_BYTES + 1):
            if index not in self.chunks:
                self.check()
                at = index * rnc.CHUNK_BYTES
                self.chunks[index] = rnc.unpack_chunked(self.image, self.layout, at, min(self.layout['size'], at + rnc.CHUNK_BYTES))
            out += self.chunks[index]
        base = start // rnc.CHUNK_BYTES * rnc.CHUNK_BYTES
        return bytes(out[start-base:end-base])


def files(head, size):
    """The filesystem's records (id, size, offset), each inside the stream, or None when it isn't one."""
    if head[:4] != b'FFS\0':return None
    count = int.from_bytes(head[4:8], 'big')
    table = 12 + 24*count
    if not 0 < count <= MAX_FILES or table > size:return None
    return count, table


def image_layout(header, file_size):
    """An I64 image's preview settings, relative to its file, when its size is exactly what it says."""
    if header[:4] != b'I64\0':return None
    width, height, code = struct.unpack_from('>3I', header, 4)
    if code not in FORMATS or not 1 <= width <= 1024 or not 1 <= height <= 1024:return None
    fmt, entries = FORMATS[code]
    pixels = (width*BITS[fmt] + 7)//8*height
    if 16 + 2*entries + pixels != file_size:return None
    settings = dict(format=fmt, width=width, height=height, offset=16 + 2*entries)
    item = dict(preview_settings=settings, frames=1, palettes=1 if entries else 0, frame_offsets=[settings['offset']],
                palette_offsets=[16] if entries else [], palette_entries=[entries] if entries else [],
                levels=[dict(width=width, height=height, offset=0)])
    if entries:settings.update(palette_offset=16, palette_format='rgba5551-be')
    return item


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per packed chunk that starts an I64 image, holding every image that starts in it."""
    results = []
    for match in re.finditer(rb'RNC\x81', image):
        check()
        layout = rnc.chunked(image, match.start())
        if not layout:continue
        reader = _Reader(image, layout, check)
        try:
            found = files(reader.read(0, 12), layout['size'])
            if not found:continue
            count, table = found
            records = [struct.unpack_from('>3I', reader.read(12 + 24*i, 24 + 24*i)) for i in range(count)]
        except rnc.RncError:continue
        groups = {}
        for index, (ident, size, offset) in enumerate(records):
            if index % 64 == 0:progress(dict(phase='Reading the packed filesystem', done=index, total=count))
            if size < 16 or offset < table or offset + size > layout['size']:continue
            try:item = image_layout(reader.read(offset, offset + 16), size)
            except rnc.RncError:continue
            if not item:continue
            item['file'] = dict(id=ident, offset=offset, size=size)
            groups.setdefault(offset // rnc.CHUNK_BYTES, []).append(item)
        for chunk, items in sorted(groups.items()):
            at, packed = layout['chunks'][chunk]
            first = items[0]['preview_settings']
            label = (f"FFS file {items[0]['file']['id']:#x} · {first['format'].upper()} {first['width']}×{first['height']}"
                     if len(items) == 1 else f'FFS images ({len(items)})')
            results.append(dict(offset=at, size=packed + (packed & 1), kind='image', label=label, confidence='validated',
                                layout='ffs-i64', stream=match.start(), textures=items,
                                **{k: v for k, v in items[0].items() if k not in ('file', 'preview_settings')},
                                preview_settings={**first, 'source': 'rom', 'offset': at},
                                reason='Every chunk read unpacked to its full 4 KB; the FFS record and the I64 header agree '
                                       'with the file size exactly. Runtime use is not established.'))
    return results


def preview(image, asset, selection):
    """Unpack only the chosen image's file and show it with its own palette."""
    layout = rnc.chunked(image, asset['stream'])
    texture = asset_formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    file = asset['textures'][texture]['file']
    try:raw = rnc.unpack_chunked(image, layout, file['offset'], file['offset'] + file['size']) if layout else None
    except rnc.RncError:raw = None
    item = raw and image_layout(raw[:16], len(raw))
    if not item:raise AssetError('The packed filesystem changed. Rescan the ROM.')
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    result = asset_formats.preview(raw, item['preview_settings'])
    result['details'].update(texture=texture, frame=0, palette=0 if item['palettes'] else 'none', note=asset['reason'])
    result['decoded'] = dict(codec='RNC chunked (method 0x81)', bytes=len(raw), block_offset=asset['offset'], member=f"FFS file {file['id']:#x}")
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=texture, frame=0, palette=0, mip=0)
    return result

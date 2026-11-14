"""Recognize texture banks, raw or packed with FLA2, the LZ variant a platformer about a magic glove uses.

FLA2 (formats as the MIT-licensed libgarib project documents them): "FLA2", the unpacked size (32 bits, little
endian), then groups of a flag byte read high bit first and eight items: bit 0 a literal byte, bit 1 two bytes
naming a run in a 4 KB window (length = low nibble of the first + 2, distance = its high nibble × 256 + the
second). Two zero bytes in place of a run end the stream.

A texture bank is a count, then per texture a 36-byte header (an id, palette animation, flags, width, height,
masks, its length with the header, a colour format, a texel format, a data pointer the game fills in, the
palette's offset from the header) and its data; the texture names follow. Texel formats: 0 CI4, 1 CI8 (palette
of RGBA16 colours at the palette offset, to the texture's end), 2 16-bit (RGBA16, or IA16 when the colour format
is 3), 3 RGBA32.
"""
from __future__ import annotations

import re
import struct

from .. import formats as asset_formats
from ..formats import AssetError

MAX_OUTPUT = 4 * 1024 * 1024
MAX_TEXTURES = 4096
HEADER = 36


def unpack(data, limit=MAX_OUTPUT):
    return _unpack(data, limit)[0]


def _unpack(data, limit=MAX_OUTPUT):
    """The unpacked bytes and how many packed bytes the stream took."""
    if data[:4] != b'FLA2':raise AssetError('No FLA2 stream starts here.')
    size = int.from_bytes(data[4:8], 'little')
    if not 0 < size <= limit:raise AssetError('The FLA2 stream unpacks beyond the limit.')
    window, cursor, out, i = bytearray(0x1000), 0, bytearray(), 8
    while True:
        if i >= len(data):raise AssetError('The FLA2 stream ends early. Rescan the ROM.')
        flags = data[i];i += 1
        for bit in range(7, -1, -1):
            if not flags >> bit & 1:
                if i >= len(data):raise AssetError('The FLA2 stream ends early. Rescan the ROM.')
                value = data[i];i += 1
                out.append(value);window[cursor] = value;cursor = (cursor + 1) & 0xFFF
                continue
            if i + 1 >= len(data):raise AssetError('The FLA2 stream ends early. Rescan the ROM.')
            first, second = data[i], data[i+1];i += 2
            if not first and not second:
                if len(out) != size:raise AssetError('The FLA2 stream ends before its size.')
                return bytes(out), i
            start = cursor - (((first & 0xF0) << 4) + second)
            for k in range((first & 0x0F) + 2):
                value = window[(start + k) & 0xFFF]
                out.append(value);window[cursor] = value;cursor = (cursor + 1) & 0xFFF
            if len(out) > size:raise AssetError('The FLA2 stream unpacks past its size.')


def textures(bank):
    """A texture bank's textures as preview items relative to the bank, or None when it isn't one."""
    if len(bank) < 4 + HEADER:return None
    count = int.from_bytes(bank[:4], 'big')
    if not 0 < count <= MAX_TEXTURES:return None
    items, at = [], 4
    for _ in range(count):
        if at + HEADER > len(bank):return None
        _ident, _low, _high, _flags, _inc, _counter, width, height, _s, _t, length, colour, texel, _ptr, palette = \
            struct.unpack_from('>IBBHhhHHHHIHHII', bank, at)
        if length < HEADER or at + length > len(bank) or not 0 < width <= 1024 or not 0 < height <= 1024:return None
        if texel > 3 or colour > 4:return None
        bits = (4, 8, 16, 32)[texel]
        data = at + HEADER
        pixels = (width*bits + 7)//8*height
        if HEADER + pixels > length:return None
        fmt = ('ci4', 'ci8', 'ia16' if colour == 3 else 'rgba5551-be', 'rgba8888')[texel]
        settings = dict(format=fmt, width=width, height=height, offset=data)
        entries = 0
        if texel < 2:
            entries = (length - palette)//2
            if palette < HEADER + pixels or palette >= length or entries < 1:return None
            settings.update(palette_offset=at + palette, palette_format='rgba5551-be')
        items.append(dict(preview_settings=settings, frames=1, palettes=1 if entries else 0, frame_offsets=[data],
                          palette_offsets=[at + palette] if entries else [], palette_entries=[entries] if entries else [],
                          levels=[dict(width=width, height=height, offset=0)]))
        at += length
    return items


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per FLA2 stream that unpacks to a texture bank."""
    results = []
    matches = [m.start() for m in re.finditer(rb'FLA2', image)]
    for number, at in enumerate(matches):
        check();progress(dict(phase='Unpacking FLA2 banks', done=number, total=len(matches)))
        size = int.from_bytes(image[at+4:at+8], 'little')
        if not 0 < size <= MAX_OUTPUT or int.from_bytes(image[at+8:at+12], 'big') == 0 and size < 4:continue
        try:bank, used = _unpack(bytes(image[at:at + 2*size + 64]))
        except AssetError:continue
        items = textures(bank)
        if not items:continue
        first = items[0]['preview_settings']
        results.append(dict(offset=at, size=used, kind='image', confidence='validated',
                            layout='fla2-texbank', textures=items, label=f'Texture bank · {len(items)} texture(s)',
                            **{k: v for k, v in items[0].items() if k != 'preview_settings'},
                            preview_settings={**first, 'source': 'rom', 'offset': at},
                            reason='The FLA2 stream unpacks to exactly its size, and every texture header in the bank fits it, '
                                   'one after another. Runtime use is not established.'))
    return results


def preview(image, asset, selection):
    bank = unpack(bytes(image[asset['offset']:asset['offset'] + asset['size']]))
    items = textures(bank)
    if not items:raise AssetError('The texture bank changed. Rescan the ROM.')
    texture = asset_formats.integer(selection.get('texture', 0), 'Texture', 0, len(items)-1)
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    result = asset_formats.preview(bank, items[texture]['preview_settings'])
    result['details'].update(texture=texture, frame=0, palette=0 if items[texture]['palettes'] else 'none', note=asset['reason'])
    result['decoded'] = dict(codec='FLA2', bytes=len(bank), block_offset=asset['offset'], member=f'texture {texture}')
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=texture, frame=0, palette=0, mip=0)
    return result

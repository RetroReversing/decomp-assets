"""Recognize textures in the "UV" filesystem of IFF-style FORM files that a flight-simulation studio's games use.

Each file is "FORM", a length and a type; inside are tagged chunks: "PAD " fillers, and "COMM", either raw or
wrapped in a "GZIP" chunk (the inner tag, the unpacked size, then a MIO0 stream). A texture file (UVTX) has a
COMM of: the texel bytes' size and the display list's command count (two halfwords), a header of floats (20 bytes
in all in one game, 28 in another), the texels, the display list, then the width and height. The display list is
what the game draws the texture with, so its tile commands give the format and size exactly; its first texture
image is the file's own texels, at the address it names (the game adds the texels' RAM address to it).

A file is taken when its display list ends where the counts say and its first drawn tile reads only its own
texels. Colour-indexed tiles whose palette is another file are left out: which file that is comes from the level.
"""
from __future__ import annotations

import re
import struct

from .. import formats as asset_formats
from ..formats import AssetError
from . import display_lists

HEADERS = (20, 28)
MAX_FILE = 1024 * 1024
END = b'\xdf' + bytes(7)


def comm(image, at, file_type=b'UVTX'):
    """The file's COMM bytes and how they were stored ('raw' or 'MIO0'), or None when the FORM type does not match."""
    if image[at:at+4] != b'FORM' or image[at+8:at+12] != file_type:return None
    end = at + 8 + int.from_bytes(image[at+4:at+8], 'big')
    if end > len(image) or end - at > MAX_FILE:return None
    p = at + 12
    while p + 8 <= end:
        tag, size = image[p:p+4], int.from_bytes(image[p+4:p+8], 'big')
        body = image[p+8:p+8+size]
        if p + 8 + size > end:return None
        if tag == b'COMM':return body, 'raw'
        if tag == b'GZIP' and body[:4] == b'COMM' and body[8:12] == b'MIO0':
            expected = int.from_bytes(body[4:8], 'big')
            if not 0 < expected <= MAX_FILE:return None
            try:data, _codec = asset_formats.unpack(body[8:])
            except AssetError:return None
            return (data, 'MIO0') if len(data) == expected else None
        if tag != b'PAD ':return None
        p += 8 + size
    return None


def _tile(commands):
    """The first tile drawn from TMEM a block or tile load filled: (format, width, height, address, palette).

    The tile's width is its TMEM row (`line`, in 64-bit words) and its height what the load put there, so a
    tile whose size is drawn half a texel in (as one game clamps them) is still read whole; the height is
    as many rows as the load filled. Last comes the row size when odd rows are stored swapped, else False. The palette is the
    load-table's address, or None, or False when it came from another image than the texels'."""
    timg = None;images = 0;tiles = {};loaded = {};palette = None
    for k in range(0, len(commands), 8):
        w0, w1 = struct.unpack_from('>II', commands, k)
        cmd = w0 >> 24
        if cmd == display_lists.G_SETTIMG:
            images += 1;timg = dict(siz=(w0 >> 19) & 3, width=(w0 & 0xFFF)+1, address=w1 & 0xFFFFFF, own=images == 1)
        elif cmd == display_lists.G_SETTILE:
            tiles[(w1 >> 24) & 7] = dict(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3, line=(w0 >> 9) & 0x1FF, tmem=w0 & 0x1FF)
        elif cmd in (display_lists.G_LOADBLOCK, display_lists.G_LOADTILE, display_lists.G_LOADTLUT) and timg:
            tile = tiles.get((w1 >> 24) & 7)
            if not tile:continue
            if cmd == display_lists.G_LOADTLUT:
                palette = timg['address'] if timg['own'] else False
            elif timg['own']:
                bits = display_lists.BITS[timg['siz']]
                if cmd == display_lists.G_LOADBLOCK:size = (((w1 >> 12) & 0xFFF)+1)*bits//8
                else:size = (((w1 >> 12) & 0xFFF)//4 - ((w0 >> 12) & 0xFFF)//4 + 1)*((w1 & 0xFFF)//4 - (w0 & 0xFFF)//4 + 1)*bits//8
                # A block load with no row step (dxt 0) copies bytes as they are: the game stored them as TMEM
                # wants them, each odd row's 32-bit words swapped in pairs.
                loaded[tile['tmem']] = dict(timg, bytes=size, swapped=cmd == display_lists.G_LOADBLOCK and not w1 & 0xFFF)
        elif cmd == display_lists.G_SETTILESIZE:
            tile = tiles.get((w1 >> 24) & 7);source = tile and loaded.get(tile['tmem'])
            fmt = tile and display_lists.FORMATS.get((tile['fmt'], tile['siz']))
            if not source or not fmt or not tile['line']:continue
            row = 8*tile['line'];bits = display_lists.BITS[tile['siz']]
            width, height = row*8//bits, -(-source['bytes']//row)
            if not height or (w1 >> 12 & 0xFFF)//4 >= width or (w1 & 0xFFF)//4 >= height + 1:continue
            return fmt, width, height, source['address'], palette, source['swapped'] and row
    return None


def texture(data):
    """The texture a COMM block draws, as preview settings relative to the block, or None."""
    if len(data) < 24:return None
    size, count = struct.unpack_from('>HH', data)
    for header in HEADERS:
        start = header + size
        if not count or start + 8*count + 4 > len(data):continue
        last = data[start+8*count-8:start+8*count]
        if last[0] not in display_lists.END_LISTS or any(last[1:]):continue
        found = _tile(data[start:start+8*count])
        if not found:return None
        fmt, width, height, address, palette, swapped = found
        # The trailer's height is the image's own; the tile may be drawn a texel short of it (clamped).
        shown = int.from_bytes(data[start+8*count+2:start+8*count+4], 'big')
        if 0 < shown <= height:height = shown
        bits = {'rgba8888': 32, 'rgba5551-be': 16, 'ia16': 16, 'ci8': 8, 'ia8': 8, 'i8': 8}.get(fmt, 4)
        entries = {'ci4': 16, 'ci8': 256}.get(fmt, 0)
        if address + width*height*bits//8 > size:return None
        settings = dict(format=fmt, width=width, height=height, offset=header + address)
        palettes = []
        if entries:
            if palette is None or palette is False or palette + 2*entries > size:return None
            palettes = [header + palette]
            settings.update(palette_offset=palettes[0], palette_format='rgba5551-be')
        return dict(preview_settings=settings, swapped_rows=swapped if fmt != 'rgba8888' else False, frames=1, palettes=len(palettes), frame_offsets=[settings['offset']],
                    palette_offsets=palettes, palette_entries=[entries] if palettes else [],
                    levels=[dict(width=width, height=height, offset=0)])
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per UVTX file whose display list names a texture in its own texels."""
    results = []
    matches = [m.start() for m in re.finditer(rb'FORM.{4}UVTX', image, re.S) if not m.start() & 3]
    for index, at in enumerate(matches):
        if index % 64 == 0:
            check();progress(dict(phase='Reading UV texture files', done=index, total=len(matches)))
        stored = comm(image, at)
        item = stored and texture(stored[0])
        if not item:continue
        settings = item['preview_settings']
        names = display_lists.NAMES[settings['format']]
        results.append(dict(offset=at, size=8 + int.from_bytes(image[at+4:at+8], 'big'), kind='image',
                            confidence='validated', layout='uv-texture', codec=stored[1],
                            label=f"UV texture {len(results)} · {names} {settings['width']}×{settings['height']}",
                            **{k: v for k, v in item.items() if k not in ('preview_settings', 'swapped_rows')},
                            preview_settings={**settings, 'source': 'rom', 'offset': at},
                            reason='The UVTX file\'s chunks fit it exactly and its own display list, which ends where its '
                                   'counts say, loads and draws this tile from the file\'s texels. Runtime use is not established.'))
    return results


def preview(image, asset, selection):
    """Unpack the file again and draw its texture as its display list sets it up."""
    stored = comm(image, asset['offset'])
    item = stored and texture(stored[0])
    if not item:raise AssetError('The UV texture file changed. Rescan the ROM.')
    asset_formats.integer(selection.get('texture', 0), 'Texture', 0, 0)
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    data, row = stored[0], item['swapped_rows']
    if row:
        settings = item['preview_settings']
        data = bytearray(data)
        for at in range(settings['offset'] + row, settings['offset'] + row*settings['height'], 2*row):
            for word in range(at, min(at + row, len(data)) - 7, 8):
                data[word:word+8] = data[word+4:word+8] + data[word:word+4]
        data = bytes(data)
    result = asset_formats.preview(data, item['preview_settings'])
    result['details'].update(texture=0, frame=0, palette=0 if item['palettes'] else 'none', note=asset['reason'])
    result['decoded'] = dict(codec=stored[1], bytes=len(data), block_offset=asset['offset'], member='COMM')
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=0, frame=0, palette=0, mip=0)
    return result
